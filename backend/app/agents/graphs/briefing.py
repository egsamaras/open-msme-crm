"""Graph 1: pre-meeting briefing and next-best-product (SPEC 4.2). Read-only, no approval.

    fetch_account_context -> compute_health_metrics (deterministic) -> synthesize_briefing (LLM)

Health status and product ideas are chosen by fixed rules on computed metrics; the model writes
the talking points and pitches around them and may only pitch products the rules put forward.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import current
from app.agents.llm import mock_handler
from app.agents.runtime import register_graph
from app.db.session import get_sessionmaker
from app.models import (
    Company,
    Deal,
    Document,
    EarlyWarningSignal,
    Facility,
    FacilityUtilization,
    FinancialSnapshot,
    Interaction,
)
from app.models.base import utcnow
from app.models.enums import (
    PRODUCT_LABEL,
    DealStage,
    DocumentType,
    EwsStatus,
    PeriodType,
    Product,
    Severity,
    VerificationStatus,
)
from app.services import financial_math as fm
from app.services.ews_rules import WORKING_CAPITAL_PRODUCTS
from app.services.pipeline import REQUIRED_DOCUMENTS

AGENT = "briefing"
TASK = f"{AGENT}.synthesize"

HIGH_UTILIZATION_PCT = Decimal(85)
HIGH_UTILIZATION_DAYS = 56  # 8 weekly points
SEASONAL_SPREAD_PCT = Decimal(15)
DSCR_COMFORT = Decimal("1.25")
DOC_HORIZON_DAYS = 60


class State(TypedDict, total=False):
    company_id: str
    facts: dict[str, Any]
    metrics: dict[str, Any]
    result: dict[str, Any]


class ProductPitch(BaseModel):
    product: Product
    pitch: str = Field(min_length=20, max_length=600)


class Briefing(BaseModel):
    headline: str = Field(min_length=10, max_length=300)
    talking_points: list[str] = Field(min_length=2, max_length=6)
    gaps: list[str] = Field(max_length=8)
    product_ideas: list[ProductPitch] = Field(max_length=2)
    source_record_ids: list[uuid.UUID]


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


async def fetch_account_context(state: State) -> State:
    ctx = current()
    cid = uuid.UUID(state["company_id"])
    today = utcnow().date()
    async with get_sessionmaker()() as session:
        company = await session.get(Company, cid)
        if company is None:
            raise LookupError("No such account")
        facilities = list(await session.scalars(select(Facility).where(Facility.company_id == cid)))
        since = today - timedelta(weeks=12)
        util = list(
            await session.scalars(
                select(FacilityUtilization)
                .where(
                    FacilityUtilization.facility_id.in_([f.id for f in facilities]),
                    FacilityUtilization.as_of >= since,
                )
                .order_by(FacilityUtilization.as_of)
            )
        )
        snaps = list(
            await session.scalars(
                select(FinancialSnapshot)
                .where(
                    FinancialSnapshot.company_id == cid,
                    FinancialSnapshot.period_type == PeriodType.MONTHLY,
                )
                .order_by(FinancialSnapshot.period_end)
            )
        )[-6:]
        docs = list(await session.scalars(select(Document).where(Document.company_id == cid)))
        signals = list(
            await session.scalars(
                select(EarlyWarningSignal).where(
                    EarlyWarningSignal.company_id == cid,
                    EarlyWarningSignal.status != EwsStatus.RESOLVED,
                )
            )
        )
        interactions = list(
            await session.scalars(
                select(Interaction)
                .where(Interaction.company_id == cid)
                .order_by(Interaction.occurred_at.desc())
                .limit(3)
            )
        )
        deals = list(
            await session.scalars(
                select(Deal).where(
                    Deal.company_id == cid,
                    Deal.stage.not_in([DealStage.DISBURSED, DealStage.LOST]),
                )
            )
        )
    by_fac: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for u in util:
        by_fac.setdefault(u.facility_id, []).append(
            {"as_of": u.as_of.isoformat(), "utilized": str(u.utilized_amount)}
        )
    facts = {
        "today": today.isoformat(),
        "company": {
            "id": str(company.id),
            "name": company.trading_name or company.legal_name,
            "industry": company.industry,
            "currency": company.currency,
            "annual_turnover": str(company.annual_turnover),
            "kyb_status": company.kyb_status.value,
            "kyb_next_review": company.kyb_next_review.isoformat()
            if company.kyb_next_review
            else None,
        },
        "facilities": [
            {
                "id": str(f.id),
                "product": f.product.value,
                "limit": str(f.sanctioned_limit),
                "utilized": str(f.utilized_amount),
                "weekly": by_fac.get(f.id, []),
            }
            for f in facilities
        ],
        "snapshots": [
            {
                "id": str(s.id),
                "period_end": s.period_end.isoformat(),
                "revenue": str(s.revenue),
                "ebitda": str(s.ebitda),
                "interest_expense": str(s.interest_expense),
                "principal_repayment": str(s.principal_repayment),
                "avg_bank_balance": str(s.avg_bank_balance),
                "bounced_cheques": s.bounced_cheques,
            }
            for s in snaps
        ],
        "documents": [
            {
                "id": str(d.id),
                "doc_type": d.doc_type.value,
                "file_name": d.file_name,
                "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
                "verification_status": d.verification_status.value,
            }
            for d in docs
        ],
        "open_signals": [
            {
                "id": str(s.id),
                "trigger": s.trigger.value,
                "severity": s.severity.value,
                "root_cause": s.root_cause_summary,
            }
            for s in signals
        ],
        "recent_interactions": [
            {
                "id": str(i.id),
                "type": i.interaction_type.value,
                "occurred_at": i.occurred_at.date().isoformat(),
                "summary": i.summary,
            }
            for i in interactions
        ],
        "open_deals": [
            {"id": str(d.id), "title": d.title, "stage": d.stage.value, "product": d.product.value}
            for d in deals
        ],
    }
    ctx.tool(
        "fetch_account_context",
        {"company_id": state["company_id"]},
        {k: len(v) if isinstance(v, list) else "…" for k, v in facts.items()},
    )
    return {"facts": facts}


def compute_metrics(facts: dict[str, Any]) -> dict[str, Any]:
    """Pure: health status, gaps and candidate products from the account facts."""
    today = date.fromisoformat(facts["today"])
    held = {Product(f["product"]) for f in facts["facilities"]}
    snaps = facts["snapshots"]

    facilities = []
    long_high: list[dict[str, Any]] = []
    for f in facts["facilities"]:
        limit = Decimal(f["limit"])
        pct = fm.utilization_pct(Decimal(f["utilized"]), limit)
        points = [
            (date.fromisoformat(w["as_of"]), p)
            for w in f["weekly"]
            if (p := fm.utilization_pct(Decimal(w["utilized"]), limit)) is not None
        ]
        days_high = fm.days_continuously_above(points, HIGH_UTILIZATION_PCT)
        row = {
            "id": f["id"],
            "product": f["product"],
            "utilization_pct": _s(pct),
            "days_above_85": days_high,
        }
        facilities.append(row)
        if Product(f["product"]) in WORKING_CAPITAL_PRODUCTS and days_high >= HIGH_UTILIZATION_DAYS:
            long_high.append(row)

    dscr_latest = dscr_first = balance_change = revenue_change = spread = None
    if snaps:
        last, first = snaps[-1], snaps[0]
        dscr_latest = fm.dscr(
            Decimal(last["ebitda"]),
            Decimal(last["interest_expense"]),
            Decimal(last["principal_repayment"]),
        )
        dscr_first = fm.dscr(
            Decimal(first["ebitda"]),
            Decimal(first["interest_expense"]),
            Decimal(first["principal_repayment"]),
        )
        revenue_change = fm.pct_change(Decimal(first["revenue"]), Decimal(last["revenue"]))
        spread = fm.spread_pct([Decimal(s["avg_bank_balance"]) for s in snaps])
        if len(snaps) >= 3:
            balance_change = fm.pct_change(
                Decimal(snaps[-3]["avg_bank_balance"]), Decimal(last["avg_bank_balance"])
            )

    gaps: list[dict[str, Any]] = []
    present = {d["doc_type"] for d in facts["documents"]}
    for required in REQUIRED_DOCUMENTS:
        if required.value not in present:
            gaps.append({"kind": "missing", "doc_type": required.value, "id": None})
    for d in facts["documents"]:
        if d["verification_status"] != VerificationStatus.VERIFIED.value:
            gaps.append(
                {"kind": d["verification_status"].lower(), "doc_type": d["doc_type"], "id": d["id"]}
            )
        if d["expiry_date"]:
            days = (date.fromisoformat(d["expiry_date"]) - today).days
            if days <= DOC_HORIZON_DAYS:
                gaps.append(
                    {
                        "kind": "expiring",
                        "doc_type": d["doc_type"],
                        "days_left": days,
                        "id": d["id"],
                    }
                )

    serious = [
        s for s in facts["open_signals"] if s["severity"] in (Severity.HIGH, Severity.CRITICAL)
    ]
    hot = any(
        f["utilization_pct"] and Decimal(f["utilization_pct"]) > HIGH_UTILIZATION_PCT
        for f in facilities
    )
    if serious or (dscr_latest is not None and dscr_latest < DSCR_COMFORT):
        health = "CONCERN"
    elif facts["open_signals"] or hot or any(g["kind"] == "expiring" for g in gaps):
        health = "WATCH"
    else:
        health = "GOOD"

    ideas: list[dict[str, Any]] = []
    for row in long_high:
        ideas.append(
            {
                "product": Product.TERM_LOAN.value,
                "reason": (
                    f"{PRODUCT_LABEL[Product(row['product'])]} above 85% drawn for "
                    f"{row['days_above_85']} days: review the limit or term out the hard-core part"
                ),
                "source_record_ids": [row["id"]],
            }
        )
    if Product.TRADE_FINANCE_LC in held and Product.FX_LINE not in held:
        lc = next(f for f in facts["facilities"] if f["product"] == Product.TRADE_FINANCE_LC)
        ideas.append(
            {
                "product": Product.FX_LINE.value,
                "reason": "uses letters of credit, so likely pays suppliers in foreign currency, "
                "with no FX line to hedge it",
                "source_record_ids": [lc["id"]],
            }
        )
    if spread is not None and spread >= SEASONAL_SPREAD_PCT and snaps:
        product = Product.WORKING_CAPITAL if Product.MURABAHA in held else Product.MURABAHA
        ideas.append(
            {
                "product": product.value,
                "reason": f"average balance swings {spread}% from peak to trough over six months: "
                "a seasonal working-capital line would smooth the dips",
                "source_record_ids": [snaps[0]["id"], snaps[-1]["id"]],
            }
        )
    if Product.CASH_MANAGEMENT not in held:
        ideas.append(
            {
                "product": Product.CASH_MANAGEMENT.value,
                "reason": "no cash-management service yet: sweeping and payables automation",
                "source_record_ids": [facts["company"]["id"]],
            }
        )
    return {
        "health": health,
        "facilities": facilities,
        "dscr_latest": _s(dscr_latest),
        "dscr_six_months_ago": _s(dscr_first),
        "revenue_change_pct": _s(revenue_change),
        "balance_change_two_months_pct": _s(balance_change),
        "balance_spread_pct": _s(spread),
        "gaps": gaps,
        "product_candidates": ideas[:2],
    }


async def compute_health_metrics(state: State) -> State:
    ctx = current()
    metrics = compute_metrics(state["facts"])
    ctx.tool("compute_health_metrics", {"company_id": state["company_id"]}, metrics)
    return {"metrics": metrics}


def _allowed(facts: dict[str, Any]) -> set[uuid.UUID]:
    ids = {uuid.UUID(facts["company"]["id"])}
    for key in ("facilities", "snapshots", "documents", "open_signals", "recent_interactions"):
        ids.update(uuid.UUID(x["id"]) for x in facts[key])
    ids.update(uuid.UUID(d["id"]) for d in facts["open_deals"])
    return ids


async def synthesize_briefing(state: State) -> State:
    ctx = current()
    facts, metrics = state["facts"], state["metrics"]
    context = {**facts, "computed": metrics}
    out = await ctx.generate(
        task=TASK,
        system=(
            "You prepare a bank relationship manager for a client meeting. Write a one-line "
            "headline, 3-5 talking points, the open document or compliance gaps, and pitches ONLY "
            "for the products in `computed.product_candidates`, tied to the reason given. Use only "
            "the figures provided; never compute new ones. Cite the record ids you relied on."
        ),
        prompt=f"Account facts and computed metrics (JSON): {context}",
        schema=Briefing,
        context=context,
        allowed_sources=_allowed(facts),
    )
    allowed_products = {c["product"] for c in metrics["product_candidates"]}
    kept = [p for p in out.product_ideas if p.product.value in allowed_products]
    if len(kept) != len(out.product_ideas):
        ctx.tool(
            "drop_unsupported_pitches",
            {"proposed": [p.product.value for p in out.product_ideas]},
            {"kept": [p.product.value for p in kept]},
        )
    briefing = out.model_copy(update={"product_ideas": kept}).model_dump(mode="json")
    return {"result": {"company_id": state["company_id"], "metrics": metrics, "briefing": briefing}}


@register_graph(AGENT)
def build() -> StateGraph[Any]:
    g: StateGraph[Any] = StateGraph(State)
    g.add_node("fetch_account_context", fetch_account_context)
    g.add_node("compute_health_metrics", compute_health_metrics)
    g.add_node("synthesize_briefing", synthesize_briefing)
    g.add_edge(START, "fetch_account_context")
    g.add_edge("fetch_account_context", "compute_health_metrics")
    g.add_edge("compute_health_metrics", "synthesize_briefing")
    g.add_edge("synthesize_briefing", END)
    return g


# ---------------- mock LLM output ----------------

_DOC_TEXT = {
    DocumentType.TRADE_LICENSE: "trade licence",
    DocumentType.CR_CERTIFICATE: "CR certificate",
    DocumentType.FINANCIAL_STATEMENT: "financial statements",
    DocumentType.BANK_STATEMENT: "bank statements",
    DocumentType.TAX_RETURN: "tax return",
    DocumentType.UBO_DECLARATION: "UBO declaration",
}

_GAP_TEXT = {
    "missing": "missing",
    "pending": "awaiting verification",
    "rejected": "rejected and needs replacing",
}


@mock_handler(TASK)
def _mock(ctx: dict[str, Any]) -> Briefing:
    m, c = ctx["computed"], ctx["company"]
    name = c["name"]
    points = []
    if m["dscr_latest"]:
        then = m["dscr_six_months_ago"]
        points.append(
            f"Debt service cover is {Decimal(m['dscr_latest']):.2f}x this month"
            + (f" (it was {Decimal(then):.2f}x six months ago)." if then else ".")
        )
    if m["revenue_change_pct"]:
        points.append(f"Monthly revenue has moved {m['revenue_change_pct']}% over six months.")
    busiest = max(
        (f for f in m["facilities"] if f["utilization_pct"]),
        key=lambda f: Decimal(f["utilization_pct"]),
        default=None,
    )
    if busiest:
        points.append(
            f"The {PRODUCT_LABEL[Product(busiest['product'])]} line is "
            f"{busiest['utilization_pct']}% drawn."
        )
    for s in ctx["open_signals"]:
        points.append(
            f"Open {s['severity'].lower()} alert: {s['trigger'].replace('_', ' ').lower()}. "
            "Ask how trading has been."
        )
    if len(points) < 2:
        points.append("Ask about plans for the next two quarters and any upcoming large payments.")
    gaps = []
    for g in m["gaps"]:
        label = _DOC_TEXT[DocumentType(g["doc_type"])]
        if g["kind"] == "expiring":
            days = g["days_left"]
            gaps.append(
                f"The {label} expires in {days} days." if days >= 0 else f"The {label} has expired."
            )
        else:
            verb = "are" if label.endswith("statements") else "is"
            gaps.append(f"The {label} {verb} {_GAP_TEXT.get(g['kind'], g['kind'])}.")
    cites = {uuid.UUID(c["id"])}
    cites.update(uuid.UUID(f["id"]) for f in m["facilities"])
    cites.update(uuid.UUID(s["id"]) for s in ctx["snapshots"][-1:])
    cites.update(uuid.UUID(s["id"]) for s in ctx["open_signals"])
    cites.update(uuid.UUID(g["id"]) for g in m["gaps"] if g.get("id"))
    for cand in m["product_candidates"]:
        cites.update(uuid.UUID(i) for i in cand["source_record_ids"])
    health = {"GOOD": "in good shape", "WATCH": "worth watching", "CONCERN": "a concern"}[
        m["health"]
    ]
    return Briefing(
        headline=f"{name} is {health}: {len(ctx['open_signals'])} open alert(s), "
        f"{len(gaps)} document gap(s).",
        talking_points=points[:5],
        gaps=gaps,
        product_ideas=[
            ProductPitch(
                product=Product(cand["product"]),
                pitch=f"{PRODUCT_LABEL[Product(cand['product'])][:1].upper()}"
                f"{PRODUCT_LABEL[Product(cand['product'])][1:]}: {cand['reason']}.",
            )
            for cand in m["product_candidates"]
        ],
        source_record_ids=sorted(cites, key=str),
    )
