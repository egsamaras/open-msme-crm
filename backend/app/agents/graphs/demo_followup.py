"""Demo agent: propose one follow-up task for an account.

A small, real graph that exercises the whole Phase 3 machinery before the four main agents
(Phase 4): deterministic context fetch -> cited LLM draft -> human approval -> apply.
Started only from a development endpoint.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import current
from app.agents.hitl import Proposal, add_approval_step
from app.agents.llm import mock_handler
from app.agents.runtime import register_graph
from app.db.session import get_sessionmaker
from app.models import Company, Facility, FinancialSnapshot
from app.models.enums import PRODUCT_LABEL, ActionType, PeriodType, Product
from app.services import financial_math as fm

AGENT = "demo_followup"
TASK = "demo_followup.draft"


class State(TypedDict, total=False):
    company_id: str
    context: dict[str, Any]
    draft: dict[str, Any]
    approvals: dict[str, dict[str, Any]]


class FollowUpDraft(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    due_in_days: int = Field(ge=1, le=30)
    rationale: str = Field(max_length=1000)
    source_record_ids: list[uuid.UUID]


async def fetch_context(state: State) -> State:
    ctx = current()
    company_id = uuid.UUID(state["company_id"])
    async with get_sessionmaker()() as session:
        company = await session.get(Company, company_id)
        if company is None:
            raise LookupError("No such company")
        facilities = list(
            await session.scalars(select(Facility).where(Facility.company_id == company_id))
        )
        latest = await session.scalar(
            select(FinancialSnapshot)
            .where(
                FinancialSnapshot.company_id == company_id,
                FinancialSnapshot.period_type == PeriodType.MONTHLY,
            )
            .order_by(FinancialSnapshot.period_end.desc())
            .limit(1)
        )
    facts: dict[str, Any] = {
        "company": {"id": str(company.id), "name": company.trading_name or company.legal_name},
        "facilities": [
            {
                "id": str(f.id),
                "product": f.product.value,
                "utilization_pct": str(fm.utilization_pct(f.utilized_amount, f.sanctioned_limit)),
            }
            for f in facilities
        ],
    }
    if latest is not None:
        ratios = fm.snapshot_ratios(latest)
        facts["latest_snapshot"] = {
            "id": str(latest.id),
            "period_end": latest.period_end.isoformat(),
            "dscr": str(ratios.dscr),
            "bounced_cheques": latest.bounced_cheques,
        }
    ctx.tool("fetch_account_context", {"company_id": str(company_id)}, facts)
    return {"context": facts}


async def draft_followup(state: State) -> State:
    ctx = current()
    facts = state["context"]
    allowed = {uuid.UUID(facts["company"]["id"])} | {
        uuid.UUID(f["id"]) for f in facts["facilities"]
    }
    if "latest_snapshot" in facts:
        allowed.add(uuid.UUID(facts["latest_snapshot"]["id"]))
    draft = await ctx.generate(
        task=TASK,
        system=(
            "You are an assistant to a bank relationship manager. Propose ONE concrete follow-up "
            "task. Use only the facts given; never compute new numbers. Cite the ids of the "
            "records you relied on in source_record_ids."
        ),
        prompt=f"Account facts (JSON): {facts}",
        schema=FollowUpDraft,
        context=facts,
        allowed_sources=allowed,
    )
    return {"draft": draft.model_dump(mode="json")}


def propose_task(state: dict[str, Any]) -> Proposal:
    draft = state["draft"]
    due = datetime.now(UTC).date() + timedelta(days=int(draft["due_in_days"]))
    return {
        "target_id": state["company_id"],
        "payload": {
            "company_id": state["company_id"],
            "title": draft["title"],
            "due_date": due.isoformat(),
            "rationale": draft["rationale"],
        },
    }


@mock_handler(TASK)
def _mock_draft(facts: dict[str, Any]) -> FollowUpDraft:
    """Deterministic stand-in for the LLM: pick the busiest facility and cite it."""
    busiest = max(
        facts["facilities"],
        key=lambda f: float(f["utilization_pct"]) if f["utilization_pct"] != "None" else -1.0,
    )
    name = facts["company"]["name"]
    product = PRODUCT_LABEL[Product(busiest["product"])]
    return FollowUpDraft(
        title=f"Call {name} about {product} usage ({busiest['utilization_pct']}% drawn)",
        due_in_days=3,
        rationale=(
            f"The {product} facility is the most heavily used line at "
            f"{busiest['utilization_pct']}% of its limit. A short call confirms whether this is "
            "seasonal or a sign of cash-flow pressure."
        ),
        source_record_ids=[uuid.UUID(facts["company"]["id"]), uuid.UUID(busiest["id"])],
    )


@register_graph(AGENT)
def build() -> StateGraph[Any]:
    g: StateGraph[Any] = StateGraph(State)
    g.add_node("fetch_context", fetch_context)
    g.add_node("draft_followup", draft_followup)
    first = add_approval_step(
        g, name="task", action=ActionType.CREATE_TASK, propose=propose_task, then=END
    )
    g.add_edge(START, "fetch_context")
    g.add_edge("fetch_context", "draft_followup")
    g.add_edge("draft_followup", first)
    return g
