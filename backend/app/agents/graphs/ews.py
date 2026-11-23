"""Graph 3: early-warning portfolio scan (SPEC 4.2).

Parent graph `ews_scan`:
    scan_portfolio (deterministic rules) -> create_ews_records -> fan_out
`fan_out` creates one child run per company with NEW signals; `drive_scan` then runs each child.
Children run after the parent finishes, as their own threads, so each pauses and resumes on its
own approval.

Child graph `ews_review`, one per flagged company:
    load_signals -> analyse_root_cause (LLM, cited) -> draft_outreach (LLM, cited) -> one approval:
      HIGH or CRITICAL signal         -> escalation (ESCALATE_EWS, four-eyes: a credit officer)
      otherwise, contact has email    -> outreach   (SEND_EMAIL, simulated)
      otherwise                       -> call       (CREATE_TASK)
"""

import uuid
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import runtime
from app.agents.context import current
from app.agents.hitl import Proposal, add_approval_step
from app.agents.llm import mock_handler
from app.agents.runtime import register_graph
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models import AgentRun, Company, Contact, EarlyWarningSignal, User
from app.models.base import utcnow
from app.models.enums import ActionType, EwsStatus, EwsTrigger, Severity
from app.services import audit
from app.services.ews_rules import evaluate, load_inputs, worst

SCAN = "ews_scan"
REVIEW = "ews_review"
_NS = uuid.UUID("5d0c7a52-3f0e-4b51-8f6a-0c2b9a7e1d34")

ESCALATE = {Severity.HIGH.value, Severity.CRITICAL.value}

TRIGGER_TEXT = {
    EwsTrigger.CASHFLOW_DROP: "average bank balance fell sharply",
    EwsTrigger.UTILIZATION_SPIKE: "working-capital line has stayed close to its limit",
    EwsTrigger.BOUNCED_CHEQUES: "cheques bounced last month",
    EwsTrigger.DOC_EXPIRY: "a licence or CR certificate is about to expire",
    EwsTrigger.COVENANT_BREACH: "a facility covenant failed on the latest figures",
}


# ---------------- parent: scan ----------------


class ScanState(TypedDict, total=False):
    findings: dict[str, list[dict[str, Any]]]
    flagged: list[dict[str, Any]]
    result: dict[str, Any]


async def scan_portfolio(state: ScanState) -> ScanState:
    ctx = current()
    s = get_settings()
    today = utcnow().date()
    async with get_sessionmaker()() as session:
        inputs = await load_inputs(session)
    findings: dict[str, list[dict[str, Any]]] = {}
    for inp in inputs:
        found = evaluate(inp, s, today)
        if found:
            findings[str(inp.company.id)] = [
                {
                    "trigger": f.trigger.value,
                    "severity": f.severity.value,
                    "metrics": {
                        **f.metrics,
                        "source_record_ids": [str(i) for i in f.source_record_ids],
                    },
                }
                for f in found
            ]
    ctx.tool(
        "scan_portfolio",
        {
            "companies": len(inputs),
            "thresholds": {
                "balance_drop_pct": str(s.ews_balance_drop_pct),
                "utilization_pct": str(s.ews_utilization_pct),
                "utilization_days": s.ews_utilization_days,
                "doc_expiry_days": s.ews_doc_expiry_days,
            },
        },
        {cid: [f["trigger"] for f in fs] for cid, fs in findings.items()},
    )
    return {"findings": findings}


def _source_key(metrics: dict[str, Any]) -> str:
    return ",".join(metrics.get("source_record_ids", []))


async def create_ews_records(state: ScanState) -> ScanState:
    """Insert new signals; refresh the metrics of ones already open. Safe to re-run."""
    ctx = current()
    new: dict[str, list[str]] = {}
    refreshed = 0
    async with get_sessionmaker()() as session:
        # One scan writes signals at a time, so two concurrent scans can't double-insert.
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('ews_scan'))"))
        for company_id, items in state["findings"].items():
            cid = uuid.UUID(company_id)
            open_signals = list(
                await session.scalars(
                    select(EarlyWarningSignal).where(
                        EarlyWarningSignal.company_id == cid,
                        EarlyWarningSignal.status != EwsStatus.RESOLVED,
                    )
                )
            )
            for item in items:
                match = next(
                    (
                        sig
                        for sig in open_signals
                        if sig.trigger.value == item["trigger"]
                        and _source_key(sig.metrics) == _source_key(item["metrics"])
                    ),
                    None,
                )
                if match is not None:
                    match.metrics = item["metrics"]
                    match.severity = Severity(item["severity"])
                    refreshed += 1
                    continue
                sig_id = uuid.uuid5(
                    _NS,
                    f"{ctx.thread_id}:{company_id}:{item['trigger']}:{_source_key(item['metrics'])}",
                )
                if await session.get(EarlyWarningSignal, sig_id) is None:
                    session.add(
                        EarlyWarningSignal(
                            id=sig_id,
                            company_id=cid,
                            trigger=EwsTrigger(item["trigger"]),
                            severity=Severity(item["severity"]),
                            status=EwsStatus.OPEN,
                            metrics=item["metrics"],
                            detected_at=utcnow(),
                        )
                    )
                    await session.flush()
                    await audit.record(
                        session,
                        action="ews.detected",
                        entity_type="early_warning_signal",
                        entity_id=sig_id,
                        payload={"company_id": company_id, **item},
                        actor_agent=SCAN,
                        actor_user_id=ctx.user_id,
                    )
                new.setdefault(company_id, []).append(str(sig_id))
        await session.commit()
    ctx.tool(
        "create_ews_records",
        {"companies_with_findings": len(state["findings"])},
        {"new_signals": sum(len(v) for v in new.values()), "refreshed_signals": refreshed},
    )
    return {"flagged": [{"company_id": c, "signal_ids": ids} for c, ids in new.items()]}


async def fan_out(state: ScanState) -> ScanState:
    """Create one child run per company with new signals. `drive_scan` executes them."""
    ctx = current()
    out = []
    async with get_sessionmaker()() as session:
        existing = {
            r.company_id: r
            for r in await session.scalars(
                select(AgentRun).where(AgentRun.parent_run_id == ctx.run_id)
            )
        }
        for f in state["flagged"]:
            cid = uuid.UUID(f["company_id"])
            child = existing.get(cid) or await runtime.create_run(
                session,
                agent_name=REVIEW,
                user_id=ctx.user_id,
                company_id=cid,
                parent_run_id=ctx.run_id,
            )
            company = await session.get(Company, cid)
            assert company is not None
            out.append(
                {
                    "company_id": f["company_id"],
                    "company_name": company.trading_name or company.legal_name,
                    "signal_ids": f["signal_ids"],
                    "child_run_id": str(child.id),
                }
            )
        await session.commit()
    total_findings = sum(len(v) for v in state["findings"].values())
    result = {
        "companies_flagged": len(state["findings"]),
        "signals_found": total_findings,
        "new_signals": sum(len(f["signal_ids"]) for f in out),
        "reviews": out,
    }
    ctx.tool(
        "fan_out", {"companies": len(out)}, {"child_run_ids": [o["child_run_id"] for o in out]}
    )
    return {"result": result}


@register_graph(SCAN)
def build_scan() -> StateGraph[Any]:
    g: StateGraph[Any] = StateGraph(ScanState)
    g.add_node("scan_portfolio", scan_portfolio)
    g.add_node("create_ews_records", create_ews_records)
    g.add_node("fan_out", fan_out)
    g.add_edge(START, "scan_portfolio")
    g.add_edge("scan_portfolio", "create_ews_records")
    g.add_edge("create_ews_records", "fan_out")
    g.add_edge("fan_out", END)
    return g


async def start_scan(session: AsyncSession, user_id: uuid.UUID | None) -> AgentRun:
    run = await runtime.create_run(session, agent_name=SCAN, user_id=user_id)
    await audit.record(
        session,
        action="agent.started",
        entity_type="agent_run",
        entity_id=run.id,
        payload={"agent": SCAN},
        actor_user_id=user_id,
    )
    return run


async def drive_scan(run_id: uuid.UUID) -> None:
    """Run the parent, then each child review in turn (each stops at its own approval)."""
    await runtime.execute(run_id, {})
    async with get_sessionmaker()() as session:
        parent = await session.get(AgentRun, run_id)
        assert parent is not None
        reviews = (parent.result or {}).get("reviews", [])
    for r in reviews:
        await runtime.execute(
            uuid.UUID(r["child_run_id"]),
            {"company_id": r["company_id"], "signal_ids": r["signal_ids"]},
        )


# ---------------- child: review one company ----------------


class ReviewState(TypedDict, total=False):
    company_id: str
    signal_ids: list[str]
    context: dict[str, Any]
    analysis: dict[str, Any]
    draft: dict[str, Any]
    approvals: dict[str, dict[str, Any]]
    result: dict[str, Any]


class RootCause(BaseModel):
    summary: str = Field(min_length=20, max_length=1500)
    likely_causes: list[str] = Field(min_length=1, max_length=5)
    source_record_ids: list[uuid.UUID]


class OutreachDraft(BaseModel):
    email_subject: str = Field(min_length=3, max_length=255)
    email_body: str = Field(min_length=20, max_length=4000)
    call_task_title: str = Field(min_length=3, max_length=255)
    escalation_summary: str = Field(min_length=20, max_length=4000)
    source_record_ids: list[uuid.UUID]


def _allowed(facts: dict[str, Any]) -> set[uuid.UUID]:
    ids = {uuid.UUID(facts["company"]["id"])}
    for sig in facts["signals"]:
        ids.add(uuid.UUID(sig["id"]))
        ids.update(uuid.UUID(i) for i in sig["metrics"].get("source_record_ids", []))
    return ids


async def load_signals(state: ReviewState) -> ReviewState:
    ctx = current()
    cid = uuid.UUID(state["company_id"])
    async with get_sessionmaker()() as session:
        company = await session.get(Company, cid)
        assert company is not None
        signals = list(
            await session.scalars(
                select(EarlyWarningSignal).where(
                    EarlyWarningSignal.id.in_([uuid.UUID(i) for i in state["signal_ids"]])
                )
            )
        )
        contact = await session.scalar(
            select(Contact)
            .where(Contact.company_id == cid)
            .order_by(Contact.is_primary.desc(), Contact.full_name)
            .limit(1)
        )
        rm = await session.get(User, company.rm_id) if company.rm_id else None
    facts = {
        "company": {
            "id": str(company.id),
            "name": company.trading_name or company.legal_name,
            "currency": company.currency,
        },
        "relationship_manager": rm.full_name if rm else None,
        "contact": (
            {"name": contact.full_name, "title": contact.title, "email": contact.email}
            if contact
            else None
        ),
        "signals": [
            {
                "id": str(s.id),
                "trigger": s.trigger.value,
                "severity": s.severity.value,
                "metrics": s.metrics,
            }
            for s in signals
        ],
    }
    ctx.tool("load_signals", {"company_id": state["company_id"]}, facts)
    return {"context": facts}


async def analyse_root_cause(state: ReviewState) -> ReviewState:
    ctx = current()
    facts = state["context"]
    out = await ctx.generate(
        task=f"{REVIEW}.root_cause",
        system=(
            "You are a credit risk analyst at a bank. Explain the likely root cause of these "
            "early-warning signals for a small business. Use only the figures given; never compute "
            "new numbers. Say what is uncertain. Cite the record ids you relied on."
        ),
        prompt=f"Signals and account facts (JSON): {facts}",
        schema=RootCause,
        context=facts,
        allowed_sources=_allowed(facts),
    )
    async with get_sessionmaker()() as session:
        for sig in await session.scalars(
            select(EarlyWarningSignal).where(
                EarlyWarningSignal.id.in_([uuid.UUID(i) for i in state["signal_ids"]])
            )
        ):
            sig.root_cause_summary = out.summary
        await session.commit()
    return {"analysis": out.model_dump(mode="json")}


async def draft_outreach(state: ReviewState) -> ReviewState:
    ctx = current()
    facts = {**state["context"], "analysis": state["analysis"]}
    out = await ctx.generate(
        task=f"{REVIEW}.draft",
        system=(
            "You draft follow-ups for a bank relationship manager. Write (1) a short, courteous "
            "email to the client asking to talk, which must NOT reveal internal risk ratings or "
            "say 'early warning'; (2) a call-task title; (3) a factual note to a credit officer. "
            "Use only the figures given. Cite the record ids you relied on."
        ),
        prompt=f"Facts (JSON): {facts}",
        schema=OutreachDraft,
        context=facts,
        allowed_sources=_allowed(state["context"]),
    )
    return {"draft": out.model_dump(mode="json")}


def choose_action(state: ReviewState) -> str:
    severities = {s["severity"] for s in state["context"]["signals"]}
    if severities & ESCALATE:
        return "propose_escalation"
    contact = state["context"]["contact"]
    return "propose_outreach" if contact and contact.get("email") else "propose_call"


def _rationale(state: dict[str, Any]) -> str:
    return str(state["analysis"]["summary"])[:2000]


def propose_escalation(state: dict[str, Any]) -> Proposal:
    return {
        "target_id": state["company_id"],
        "payload": {
            "company_id": state["company_id"],
            "signal_ids": state["signal_ids"],
            "summary": state["draft"]["escalation_summary"],
            "rm_task_title": state["draft"]["call_task_title"],
            "rationale": _rationale(state),
        },
    }


def propose_outreach(state: dict[str, Any]) -> Proposal:
    return {
        "target_id": state["company_id"],
        "payload": {
            "company_id": state["company_id"],
            "to_address": state["context"]["contact"]["email"],
            "subject": state["draft"]["email_subject"],
            "body": state["draft"]["email_body"],
        },
    }


def propose_call(state: dict[str, Any]) -> Proposal:
    return {
        "target_id": state["company_id"],
        "payload": {
            "company_id": state["company_id"],
            "title": state["draft"]["call_task_title"],
            "rationale": _rationale(state),
        },
    }


async def summarise(state: ReviewState) -> ReviewState:
    decided = {k: v.get("decision") for k, v in (state.get("approvals") or {}).items()}
    return {
        "result": {
            "company_id": state["company_id"],
            "signals": len(state["signal_ids"]),
            "root_cause": state["analysis"]["summary"],
            "decisions": decided,
        }
    }


@register_graph(REVIEW)
def build_review() -> StateGraph[Any]:
    g: StateGraph[Any] = StateGraph(ReviewState)
    g.add_node("load_signals", load_signals)
    g.add_node("analyse_root_cause", analyse_root_cause)
    g.add_node("draft_outreach", draft_outreach)
    g.add_node("summarise", summarise)
    steps = {
        "escalation": (ActionType.ESCALATE_EWS, propose_escalation),
        "outreach": (ActionType.SEND_EMAIL, propose_outreach),
        "call": (ActionType.CREATE_TASK, propose_call),
    }
    for name, (action, propose) in steps.items():
        add_approval_step(
            g, name=name, action=action, propose=propose, then="summarise", on_reject="summarise"
        )
    g.add_edge(START, "load_signals")
    g.add_edge("load_signals", "analyse_root_cause")
    g.add_edge("analyse_root_cause", "draft_outreach")
    g.add_conditional_edges(
        "draft_outreach", choose_action, ["propose_escalation", "propose_outreach", "propose_call"]
    )
    g.add_edge("summarise", END)
    return g


# ---------------- mock LLM output ----------------


def _sig_line(sig: dict[str, Any], currency: str) -> str:
    m = sig["metrics"]
    match sig["trigger"]:
        case "CASHFLOW_DROP":
            return (
                f"average bank balance fell {m['change_pct'].lstrip('-')}% between "
                f"{m['from_period']} and {m['to_period']} "
                f"({currency} {Decimal(m['from_balance']):,.2f} to "
                f"{Decimal(m['to_balance']):,.2f})"
            )
        case "UTILIZATION_SPIKE":
            return (
                f"the working-capital line has been above {m['threshold_pct']}% drawn for "
                f"{m['days_above']} days (latest {m['latest_utilization_pct']}%)"
            )
        case "BOUNCED_CHEQUES":
            return f"{m['count']} cheques bounced in the month to {m['period']}"
        case "DOC_EXPIRY":
            doc = m["document_type"].replace("_", " ").lower()
            return f"the {doc} expires on {m['expiry_date']} ({m['days_left']} days)"
        case _:
            test = f"{m['operator']} {m['threshold']}"
            return f"the {m['metric']} covenant ({test}) failed at {m['actual']}"


def _cite(facts: dict[str, Any]) -> list[uuid.UUID]:
    return sorted(_allowed(facts), key=str)


@mock_handler(f"{REVIEW}.root_cause")
def _mock_root_cause(facts: dict[str, Any]) -> RootCause:
    name = facts["company"]["name"]
    lines = [_sig_line(s, facts["company"]["currency"]) for s in facts["signals"]]
    causes = [TRIGGER_TEXT[EwsTrigger(s["trigger"])] for s in facts["signals"]]
    return RootCause(
        summary=(
            f"For {name}: " + "; ".join(lines) + ". Together these point to short-term liquidity "
            "pressure rather than a single event, but the figures alone can't show whether it is "
            "seasonal. A conversation with the client should come first."
        ),
        likely_causes=causes,
        source_record_ids=_cite(facts),
    )


@mock_handler(f"{REVIEW}.draft")
def _mock_draft(facts: dict[str, Any]) -> OutreachDraft:
    name = facts["company"]["name"]
    contact = (facts.get("contact") or {}).get("name") or "team"
    rm = facts.get("relationship_manager") or "your relationship manager"
    worst_sev = worst([Severity(s["severity"]) for s in facts["signals"]]).value.title()
    return OutreachDraft(
        email_subject=f"Catching up on {name}'s banking needs",
        email_body=(
            f"Dear {contact.split()[0] if contact != 'team' else 'team'},\n\n"
            "I hope business is going well. I'd like to set up a short call this week to hear how "
            "trading has been recently and whether your current facilities still fit your "
            "needs.\n\n"
            f"Would Tuesday or Wednesday suit you?\n\nKind regards,\n{rm}"
        ),
        call_task_title=f"Call {name} about recent account activity",
        escalation_summary=(
            f"{worst_sev}-severity early-warning signals on {name}. "
            + facts["analysis"]["summary"]
            + " Recommend a credit review of current limits before any new drawdowns."
        ),
        source_record_ids=_cite(facts),
    )
