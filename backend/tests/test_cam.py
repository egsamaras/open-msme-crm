"""Phase 4, graph 4: credit memo drafting, pro-forma ratios, four-eyes submission."""

import uuid
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import sid
from app.models import AuditEvent, Deal, FinancialSnapshot, Task
from app.models.enums import DealStage, PeriodType
from app.services import audit
from app.services import financial_math as fm
from tests.conftest import login

GULF_SPICE_DEAL = sid("deal", "gulf-spice")  # term loan, in underwriting
OASIS_DEAL = sid("deal", "oasis-clinics")  # working capital, in underwriting
GOLDEN_DEAL = sid("deal", "lulu-bakers")  # working capital, in underwriting
CREDIT_OFFICER = sid("user", "credit")


async def _start(client: AsyncClient, deal: uuid.UUID, who: str = "rm@demo.local") -> Any:
    await login(client, who)
    return await client.post(f"/api/agents/cam/{deal}")


async def _run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    return dict((await client.get(f"/api/agent-runs/{run_id}")).json())


async def _approval(client: AsyncClient, run_id: str) -> dict[str, Any]:
    items = (await client.get("/api/approvals")).json()
    return next(i for i in items if i["run"]["id"] == run_id)


async def test_only_rms_start_memos_and_only_for_deals_in_underwriting(
    client: AsyncClient, session: AsyncSession
) -> None:
    assert (await _start(client, GULF_SPICE_DEAL, "compliance@demo.local")).status_code == 403
    lead = await session.scalar(select(Deal.id).where(Deal.stage == DealStage.LEAD))
    r = await _start(client, lead)  # type: ignore[arg-type]
    assert r.status_code == 409 and "underwriting" in r.json()["detail"]
    assert (await _start(client, uuid.uuid4())).status_code == 404


async def test_memo_is_drafted_from_computed_ratios_and_waits_for_credit(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await _start(client, GULF_SPICE_DEAL)
    assert r.status_code == 202, r.text
    run = await _run(client, r.json()["id"])
    assert run["status"] == "AWAITING_APPROVAL" and run["deal_id"] == str(GULF_SPICE_DEAL)
    nodes = [e["node"] for e in run["trace"] if e["type"] == "node"]
    assert nodes == [
        "gather_deal_and_exposure",
        "calculate_ratios",
        "fetch_benchmarks",
        "draft_cam_sections",
        "propose_cam_submission",
    ]
    tools = [e["name"] for e in run["trace"] if e["type"] == "tool"]
    assert tools == ["gather_deal_and_exposure", "calculate_ratios", "fetch_benchmarks"]

    # Recompute the pro-forma DSCR independently: 3-month average EBITDA, latest debt service,
    # plus a 60-month straight-line term loan at the assumed 7.50%.
    deal = await session.get(Deal, GULF_SPICE_DEAL)
    assert deal is not None
    snaps = list(
        await session.scalars(
            select(FinancialSnapshot)
            .where(
                FinancialSnapshot.company_id == deal.company_id,
                FinancialSnapshot.period_type == PeriodType.MONTHLY,
            )
            .order_by(FinancialSnapshot.period_end.desc())
            .limit(3)
        )
    )
    avg_ebitda = sum((s.ebitda for s in snaps), Decimal(0)) / 3
    new_ds = fm.monthly_debt_service(deal.requested_amount, Decimal("7.50"), 60)
    expected = fm.pro_forma_dscr(
        avg_ebitda, snaps[0].interest_expense, snaps[0].principal_repayment, new_ds
    )
    result = run["result"]
    assert result["ratios"]["dscr_pro_forma"] == str(expected)
    assert result["ratios"]["new_monthly_debt_service"] == str(new_ds)
    assert result["assumptions"]["repayment"] == "60 months, straight-line"
    assert [s["key"] for s in result["sections"]] == [
        "executive_summary",
        "business_overview",
        "financial_analysis",
        "facility_structure",
        "risks_and_mitigants",
        "recommendation",
    ]
    # The prose narrates the computed numbers; it doesn't invent its own.
    analysis = next(s["body"] for s in result["sections"] if s["key"] == "financial_analysis")
    assert str(expected) in analysis
    assert result["benchmark"]["industry"] == "Wholesale and retail trade"
    assert {r["kind"] for r in run["cited_records"]} >= {"Deal", "Account", "Financial snapshot"}

    item = await _approval(client, run["id"])
    assert item["action_type"] == "SUBMIT_CAM" and item["four_eyes"] is True
    assert item["can_review"] is False and "credit officer" in item["review_blocker"]
    assert item["proposed_payload"]["risk_grade"] == result["risk_grade"]

    again = await _start(client, GULF_SPICE_DEAL)
    assert again.status_code == 409 and "already in progress" in again.json()["detail"]


async def test_credit_officer_edits_and_submits_the_memo(
    client: AsyncClient, session: AsyncSession
) -> None:
    await login(client, "credit@demo.local")
    items = (await client.get("/api/approvals")).json()
    item = next(
        i
        for i in items
        if i["action_type"] == "SUBMIT_CAM"
        and i["proposed_payload"]["deal_id"] == str(GULF_SPICE_DEAL)
    )
    assert item["can_review"] is True
    payload = item["proposed_payload"]

    tampered = {**payload, "ratios": {**payload["ratios"], "dscr_pro_forma": "9.99"}}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE", "payload": tampered}
    )
    assert r.status_code == 422 and "ratios" in r.json()["detail"]

    sections = [dict(s) for s in payload["sections"]]
    sections[-1]["body"] = "Recommend approval subject to a minimum DSCR covenant of 1.25x."
    edited = {**payload, "sections": sections}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve",
        json={"decision": "APPROVE", "payload": edited, "note": "Added covenant"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EDITED_AND_APPROVED"
    assert r.json()["run"]["status"] == "COMPLETED"

    session.expire_all()
    deal = await session.get(Deal, GULF_SPICE_DEAL)
    assert deal is not None
    assert deal.stage == DealStage.APPROVAL and deal.credit_officer_id == CREDIT_OFFICER
    assert deal.draft_cam is not None
    assert deal.draft_cam["sections"][-1]["body"].startswith("Recommend approval subject")
    task = await session.scalar(select(Task).where(Task.deal_id == GULF_SPICE_DEAL))
    assert task is not None and task.assignee_id == CREDIT_OFFICER
    assert task.title.startswith("Credit decision:")
    moved = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(GULF_SPICE_DEAL), AuditEvent.action == "deal.update"
        )
    )
    assert moved is not None and moved.payload["via"] == "credit memo approval"
    assert (await audit.verify_chain(session)).ok


async def test_rejected_memo_leaves_the_deal_in_underwriting(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await _start(client, OASIS_DEAL)
    run_id = r.json()["id"]
    item = await _approval(client, run_id)
    await login(client, "credit@demo.local")
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve",
        json={"decision": "REJECT", "note": "Wait for the bounced cheques to be explained"},
    )
    assert r.json()["run"]["status"] == "REJECTED"
    session.expire_all()
    deal = await session.get(Deal, OASIS_DEAL)
    assert deal is not None and deal.stage == DealStage.CREDIT_UNDERWRITING
    assert deal.draft_cam is None
    # Interest-only working capital line in the assumptions.
    run = await _run(client, run_id)
    assert run["result"]["assumptions"]["repayment"] == "interest-only revolving line"


async def test_four_eyes_and_a_deal_moved_while_waiting(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await _start(client, GOLDEN_DEAL, "admin@demo.local")
    assert r.status_code == 202
    item = await _approval(client, r.json()["id"])
    assert item["can_review"] is False and "Four-eyes" in item["review_blocker"]
    blocked = await client.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"}
    )
    assert blocked.status_code == 403

    # Someone moves the deal back while the memo waits; approving must not drag it forward.
    deal = await session.get(Deal, GOLDEN_DEAL)
    assert deal is not None
    deal.stage = DealStage.DOC_COLLECTION
    await session.commit()
    await login(client, "credit@demo.local")
    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 200
    run = await _run(client, item["run"]["id"])
    applied = next(e for e in run["trace"] if e.get("name") == "apply.submit_cam")
    assert applied["output"] == {"skipped": "deal is now in DOC_COLLECTION"}
    session.expire_all()
    deal = await session.get(Deal, GOLDEN_DEAL)
    assert deal is not None and deal.stage == DealStage.DOC_COLLECTION
    deal.stage = DealStage.CREDIT_UNDERWRITING  # put it back for later test modules
    await session.commit()
