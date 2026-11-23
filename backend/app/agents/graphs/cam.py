"""Graph 4: credit appraisal memo (CAM) drafting (SPEC 4.2).

    gather_deal_and_exposure -> calculate_ratios (deterministic, incl. pro-forma DSCR)
      -> fetch_benchmarks (static table) -> draft_cam_sections (LLM, cited)
      -> propose_cam_submission -> await_cam_submission -> apply_cam_submission

Approval is four-eyes: a credit officer who didn't start the run reviews (and may edit) the memo.
Applying moves the deal to APPROVAL, records the memo on the deal and assigns that officer.
The LLM writes prose around numbers computed here; the risk grade is a transparent scorecard.
"""

import uuid
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import current
from app.agents.hitl import Proposal, add_approval_step
from app.agents.llm import mock_handler
from app.agents.runtime import register_graph
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models import (
    BeneficialOwner,
    Company,
    Deal,
    Document,
    EarlyWarningSignal,
    Facility,
    FinancialSnapshot,
)
from app.models.base import utcnow
from app.models.enums import PRODUCT_LABEL, ActionType, EwsStatus, PeriodType, Product
from app.services import benchmarks
from app.services import financial_math as fm
from app.services.pipeline import build_checklist

AGENT = "cam_draft"
TASK = f"{AGENT}.sections"

# Pricing and tenor assumptions for the pro-forma. Illustrative; a bank would use its own grid.
# None = revolving, serviced interest-only. Non-funded lines add no debt service.
TERMS: dict[Product, tuple[Decimal, int | None]] = {
    Product.TERM_LOAN: (Decimal("7.50"), 60),
    Product.IJARA: (Decimal("7.25"), 60),
    Product.WORKING_CAPITAL: (Decimal("8.00"), None),
    Product.MURABAHA: (Decimal("7.75"), None),
    Product.TRADE_FINANCE_LC: (Decimal("6.50"), None),
    Product.POS_MERCHANT: (Decimal("8.00"), None),
}
NON_FUNDED = frozenset({Product.LETTER_OF_GUARANTEE, Product.FX_LINE, Product.CASH_MANAGEMENT})

SECTIONS = [
    ("executive_summary", "Executive summary"),
    ("business_overview", "Business overview"),
    ("financial_analysis", "Financial analysis"),
    ("facility_structure", "Proposed facility structure"),
    ("risks_and_mitigants", "Risks and mitigants"),
    ("recommendation", "Preliminary risk grade and recommendation"),
]


class State(TypedDict, total=False):
    deal_id: str
    facts: dict[str, Any]
    ratios: dict[str, Any]
    benchmark: dict[str, Any]
    result: dict[str, Any]
    approvals: dict[str, dict[str, Any]]


class CamDraft(BaseModel):
    executive_summary: str = Field(min_length=40, max_length=3000)
    business_overview: str = Field(min_length=40, max_length=3000)
    financial_analysis: str = Field(min_length=40, max_length=4000)
    facility_structure: str = Field(min_length=40, max_length=3000)
    risks_and_mitigants: str = Field(min_length=40, max_length=4000)
    recommendation: str = Field(min_length=40, max_length=3000)
    source_record_ids: list[uuid.UUID]


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


async def gather_deal_and_exposure(state: State) -> State:
    ctx = current()
    deal_id = uuid.UUID(state["deal_id"])
    today = utcnow().date()
    async with get_sessionmaker()() as session:
        deal = await session.get(Deal, deal_id)
        if deal is None:
            raise LookupError("No such deal")
        company = await session.get(Company, deal.company_id)
        assert company is not None
        facilities = list(
            await session.scalars(select(Facility).where(Facility.company_id == company.id))
        )
        snaps = list(
            await session.scalars(
                select(FinancialSnapshot)
                .where(
                    FinancialSnapshot.company_id == company.id,
                    FinancialSnapshot.period_type == PeriodType.MONTHLY,
                )
                .order_by(FinancialSnapshot.period_end.desc())
                .limit(3)
            )
        )[::-1]
        signals = list(
            await session.scalars(
                select(EarlyWarningSignal).where(
                    EarlyWarningSignal.company_id == company.id,
                    EarlyWarningSignal.status != EwsStatus.RESOLVED,
                )
            )
        )
        documents = list(
            await session.scalars(select(Document).where(Document.company_id == company.id))
        )
        owners = list(
            await session.scalars(
                select(BeneficialOwner).where(BeneficialOwner.company_id == company.id)
            )
        )
    threshold = get_settings().ubo_threshold_pct
    facts = {
        "deal": {
            "id": str(deal.id),
            "title": deal.title,
            "product": deal.product.value,
            "requested_amount": str(deal.requested_amount),
            "stage": deal.stage.value,
        },
        "company": {
            "id": str(company.id),
            "name": company.trading_name or company.legal_name,
            "legal_name": company.legal_name,
            "country": company.country,
            "industry": company.industry,
            "tier": company.tier.value,
            "annual_turnover": str(company.annual_turnover),
            "currency": company.currency,
            "risk_rating": company.risk_rating,
            "kyb_status": company.kyb_status.value,
        },
        "facilities": [
            {
                "id": str(f.id),
                "product": f.product.value,
                "limit": str(f.sanctioned_limit),
                "utilized": str(f.utilized_amount),
                "utilization_pct": _s(fm.utilization_pct(f.utilized_amount, f.sanctioned_limit)),
                "covenants": f.covenants,
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
                "total_debt": str(s.total_debt),
                "total_equity": str(s.total_equity),
                "current_assets": str(s.current_assets),
                "current_liabilities": str(s.current_liabilities),
                "avg_bank_balance": str(s.avg_bank_balance),
                "bounced_cheques": s.bounced_cheques,
            }
            for s in snaps
        ],
        "open_signals": [
            {
                "id": str(e.id),
                "trigger": e.trigger.value,
                "severity": e.severity.value,
                "status": e.status.value,
            }
            for e in signals
        ],
        "documents": [
            {"doc_type": c.doc_type.value, "state": c.state, "id": _s_id(c.document_id)}
            for c in build_checklist(documents, today)
        ],
        "owners": [
            {
                "name": o.full_name,
                "ownership_pct": str(o.ownership_pct),
                "is_ubo": o.ownership_pct >= threshold,
                "pep": o.pep_status.value,
                "sanctions": o.sanctions_status.value,
            }
            for o in owners
        ],
    }
    ctx.tool("gather_deal_and_exposure", {"deal_id": state["deal_id"]}, facts)
    return {"facts": facts}


def _s_id(v: uuid.UUID | None) -> str | None:
    return None if v is None else str(v)


async def calculate_ratios(state: State) -> State:
    """Deterministic: every number in the memo comes from here (SPEC 4.1, rule 3)."""
    ctx = current()
    facts = state["facts"]
    deal = facts["deal"]
    product = Product(deal["product"])
    amount = Decimal(deal["requested_amount"])
    snaps = facts["snapshots"]
    if not snaps:
        raise ValueError("No monthly financials on file: can't analyse this deal")
    latest = snaps[-1]
    d = {k: Decimal(latest[k]) for k in latest if k not in ("id", "period_end", "bounced_cheques")}
    annual_ebitda = fm.annualise_monthly([Decimal(s["ebitda"]) for s in snaps])
    annual_revenue = fm.annualise_monthly([Decimal(s["revenue"]) for s in snaps])
    assert annual_ebitda is not None and annual_revenue is not None
    avg_ebitda = annual_ebitda / 12

    funded = product not in NON_FUNDED
    rate, tenor = TERMS.get(product, (Decimal(0), None))
    new_ds = fm.monthly_debt_service(amount, rate, tenor) if funded else Decimal("0.00")
    pf_debt = d["total_debt"] + (amount if funded else Decimal(0))
    today_ratios = {
        "dscr": fm.dscr(avg_ebitda, d["interest_expense"], d["principal_repayment"]),
        "debt_to_ebitda": fm.debt_to_ebitda(d["total_debt"], annual_ebitda),
    }
    pro_forma = {
        "dscr": fm.pro_forma_dscr(
            avg_ebitda, d["interest_expense"], d["principal_repayment"], new_ds
        ),
        "debt_to_ebitda": fm.debt_to_ebitda(pf_debt, annual_ebitda),
    }
    current_ratio = fm.current_ratio(d["current_assets"], d["current_liabilities"])
    leverage = fm.debt_to_equity(pf_debt, d["total_equity"])
    total_limit = sum((Decimal(f["limit"]) for f in facts["facilities"]), Decimal(0))
    total_used = sum((Decimal(f["utilized"]) for f in facts["facilities"]), Decimal(0))
    grade = fm.indicative_risk_grade(pro_forma["dscr"], pro_forma["debt_to_ebitda"], current_ratio)
    ratios = {
        "annualised_revenue": str(annual_revenue.quantize(Decimal("0.01"))),
        "annualised_ebitda": str(annual_ebitda.quantize(Decimal("0.01"))),
        "dscr_current": _s(today_ratios["dscr"]),
        "dscr_pro_forma": _s(pro_forma["dscr"]),
        "debt_to_ebitda_current": _s(today_ratios["debt_to_ebitda"]),
        "debt_to_ebitda_pro_forma": _s(pro_forma["debt_to_ebitda"]),
        "debt_to_equity_pro_forma": _s(leverage),
        "current_ratio": _s(current_ratio),
        "existing_utilization_pct": _s(fm.utilization_pct(total_used, total_limit)),
        "new_monthly_debt_service": str(new_ds),
        "risk_grade": str(grade),
    }
    assumptions = {
        "rate_pct": str(rate),
        "repayment": (
            "non-funded: no debt service"
            if not funded
            else "interest-only revolving line"
            if tenor is None
            else f"{tenor} months, straight-line"
        ),
        "ebitda_basis": f"average of the last {len(snaps)} monthly snapshots",
        "grade_method": "scorecard on pro-forma DSCR, pro-forma debt/EBITDA and current ratio",
    }
    out = {"ratios": ratios, "assumptions": assumptions, "risk_grade": grade}
    ctx.tool("calculate_ratios", {"deal_id": deal["id"], "amount": deal["requested_amount"]}, out)
    return {"ratios": out}


async def fetch_benchmarks(state: State) -> State:
    ctx = current()
    industry = state["facts"]["company"]["industry"]
    b = benchmarks.for_industry(industry)
    out = {
        "industry": b.industry,
        "dscr_median": str(b.dscr_median),
        "debt_to_ebitda_median": str(b.debt_to_ebitda_median),
        "current_ratio_median": str(b.current_ratio_median),
        "source": benchmarks.SOURCE,
    }
    ctx.tool("fetch_benchmarks", {"industry": industry}, out)
    return {"benchmark": out}


def _allowed(facts: dict[str, Any]) -> set[uuid.UUID]:
    ids = {uuid.UUID(facts["deal"]["id"]), uuid.UUID(facts["company"]["id"])}
    for key in ("facilities", "snapshots", "open_signals", "documents"):
        ids.update(uuid.UUID(x["id"]) for x in facts[key] if x.get("id"))
    return ids


async def draft_cam_sections(state: State) -> State:
    ctx = current()
    context = {**state["facts"], "calculated": state["ratios"], "benchmark": state["benchmark"]}
    draft = await ctx.generate(
        task=TASK,
        system=(
            "You draft credit appraisal memos for SME lending at a bank. Write each section in "
            "plain, factual prose for a credit committee. Use ONLY the figures in `calculated`, "
            "`benchmark` and the records given; never compute or estimate a number yourself. Name "
            "weaknesses plainly and suggest mitigants. The risk grade is the scorecard's; explain "
            "it, don't change it. Cite the ids of every record you relied on."
        ),
        prompt=f"Deal, account and calculated figures (JSON): {context}",
        schema=CamDraft,
        context=context,
        allowed_sources=_allowed(state["facts"]),
    )
    body = draft.model_dump(mode="json")
    sections = [{"key": k, "title": t, "body": body[k]} for k, t in SECTIONS]
    return {
        "result": {
            "deal_id": state["deal_id"],
            "sections": sections,
            "risk_grade": state["ratios"]["risk_grade"],
            "ratios": state["ratios"]["ratios"],
            "assumptions": state["ratios"]["assumptions"],
            "benchmark": state["benchmark"],
            "source_record_ids": body["source_record_ids"],
        }
    }


def propose_submission(state: dict[str, Any]) -> Proposal:
    r = state["result"]
    ratios = r["ratios"]
    return {
        "target_id": state["deal_id"],
        "payload": {
            "company_id": state["facts"]["company"]["id"],
            "deal_id": state["deal_id"],
            "sections": r["sections"],
            "risk_grade": r["risk_grade"],
            "ratios": ratios,
            "assumptions": r["assumptions"],
            "rationale": (
                f"Indicative grade {r['risk_grade']}/10 from the scorecard: pro-forma DSCR "
                f"{ratios['dscr_pro_forma'] or 'n/a'}, pro-forma debt/EBITDA "
                f"{ratios['debt_to_ebitda_pro_forma'] or 'n/a'}, current ratio "
                f"{ratios['current_ratio'] or 'n/a'}. Approving submits the memo and moves the "
                "deal to Approval with you as the credit officer."
            ),
        },
    }


@register_graph(AGENT)
def build() -> StateGraph[Any]:
    g: StateGraph[Any] = StateGraph(State)
    g.add_node("gather_deal_and_exposure", gather_deal_and_exposure)
    g.add_node("calculate_ratios", calculate_ratios)
    g.add_node("fetch_benchmarks", fetch_benchmarks)
    g.add_node("draft_cam_sections", draft_cam_sections)
    first = add_approval_step(
        g, name="cam_submission", action=ActionType.SUBMIT_CAM, propose=propose_submission
    )
    g.add_edge(START, "gather_deal_and_exposure")
    g.add_edge("gather_deal_and_exposure", "calculate_ratios")
    g.add_edge("calculate_ratios", "fetch_benchmarks")
    g.add_edge("fetch_benchmarks", "draft_cam_sections")
    g.add_edge("draft_cam_sections", first)
    return g


# ---------------- mock LLM output ----------------


def _n(v: str | None, suffix: str = "") -> str:
    return "not available" if v is None else f"{v}{suffix}"


def _m(v: str) -> str:
    return f"{Decimal(v):,.2f}"


@mock_handler(TASK)
def _mock_sections(ctx: dict[str, Any]) -> CamDraft:
    c, d, r, b = ctx["company"], ctx["deal"], ctx["calculated"]["ratios"], ctx["benchmark"]
    a = ctx["calculated"]["assumptions"]
    cur = c["currency"]
    product = PRODUCT_LABEL[Product(d["product"])]
    grade = ctx["calculated"]["risk_grade"]
    signals = ctx["open_signals"]
    gaps = [
        x["doc_type"].replace("_", " ").lower()
        for x in ctx["documents"]
        if x["state"] != "VERIFIED"
    ]
    ubos = [o["name"] for o in ctx["owners"] if o["is_ubo"]]
    latest = ctx["snapshots"][-1]
    risks = []
    if signals:
        risks.append(
            f"{len(signals)} open early-warning signal(s) ("
            + ", ".join(s["trigger"].replace("_", " ").lower() for s in signals)
            + "); the credit officer should review them before deciding"
        )
    if gaps:
        risks.append("documents not yet verified: " + ", ".join(gaps))
    if latest["bounced_cheques"]:
        risks.append(f"{latest['bounced_cheques']} bounced cheque(s) in the latest month")
    if not risks:
        risks.append("no open alerts or document gaps on file")
    cites = [uuid.UUID(d["id"]), uuid.UUID(c["id"])] + [
        uuid.UUID(s["id"]) for s in ctx["snapshots"]
    ]
    cites += [uuid.UUID(f["id"]) for f in ctx["facilities"]] + [uuid.UUID(s["id"]) for s in signals]
    amount = _m(d["requested_amount"])
    new_ds = _m(r["new_monthly_debt_service"])
    return CamDraft(
        executive_summary=(
            f"{c['legal_name']} requests a {product} facility of {cur} {amount}. "
            f"On the bank's figures the pro-forma DSCR is {_n(r['dscr_pro_forma'])} against an "
            f"industry median of {b['dscr_median']}, giving an indicative risk grade of {grade}/10."
        ),
        business_overview=(
            f"A {c['tier'].lower()} enterprise in {c['industry'].lower()} ({c['country']}), "
            f"annualised revenue {cur} {_m(r['annualised_revenue'])} and EBITDA {cur} "
            f"{_m(r['annualised_ebitda'])} over the last three months. KYB status: "
            f"{c['kyb_status'].replace('_', ' ').lower()}. Beneficial owners at or above the "
            f"threshold: {', '.join(ubos) or 'none recorded'}."
        ),
        financial_analysis=(
            f"DSCR is {_n(r['dscr_current'])} today and {_n(r['dscr_pro_forma'])} with the new "
            f"facility (industry median {b['dscr_median']}). Debt/EBITDA moves from "
            f"{_n(r['debt_to_ebitda_current'], 'x')} to {_n(r['debt_to_ebitda_pro_forma'], 'x')} "
            f"(median {b['debt_to_ebitda_median']}x). Current ratio {_n(r['current_ratio'])} "
            f"(median {b['current_ratio_median']}). Existing lines are "
            f"{_n(r['existing_utilization_pct'], '%')} drawn."
        ),
        facility_structure=(
            f"{product[:1].upper()}{product[1:]} of {cur} {amount} at an assumed "
            f"{a['rate_pct']}% ({a['repayment']}), adding {cur} {new_ds} "
            "of monthly debt service. Pricing, tenor and security to be confirmed by credit."
        ),
        risks_and_mitigants=(
            "Risks: " + "; ".join(risks) + ". Mitigants to consider: covenant on minimum DSCR, "
            "quarterly management accounts, and assignment of receivables where appropriate."
        ),
        recommendation=(
            f"Indicative grade {grade}/10 (1 strongest) from the scorecard on pro-forma DSCR, "
            "debt/EBITDA and current ratio. This is a draft for the credit officer; the credit "
            "decision is theirs."
        ),
        source_record_ids=cites,
    )
