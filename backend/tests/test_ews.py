"""Phase 4, graph 3: early-warning rules, the portfolio scan, per-company reviews, Risk radar."""

import uuid
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graphs import ews as ews_graph
from app.core.config import Settings
from app.db.seed import sid
from app.db.session import get_sessionmaker
from app.models import (
    AgentRun,
    ApprovalItem,
    EarlyWarningSignal,
    OutboxMessage,
    Task,
)
from app.models.enums import (
    DocumentType,
    EwsStatus,
    EwsTrigger,
    Product,
    Severity,
)
from app.services import audit
from app.services import ews_rules as rules
from tests.conftest import login

DUNES = sid("company", "dunes-logistics")  # balance drop
FALCON = sid("company", "falcon-steel")  # utilisation above 90%
OASIS = sid("company", "oasis-clinics")  # bounced cheques
PEARL = sid("company", "pearl-bay")  # licence expiring
TODAY = date(2026, 11, 23)
S = Settings()


# ---------- rules (pure) ----------


def _snap(balance: str, bounced: int = 0, ebitda: str = "100") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        period_end=TODAY,
        avg_bank_balance=D(balance),
        bounced_cheques=bounced,
        ebitda=D(ebitda),
        interest_expense=D("10"),
        principal_repayment=D("40"),
        total_debt=D("1000"),
        total_equity=D("500"),
        current_assets=D("200"),
        current_liabilities=D("100"),
    )


def _inputs(**kw: Any) -> rules.CompanyInputs:
    company = SimpleNamespace(id=uuid.uuid4(), currency="BHD")
    return rules.CompanyInputs(
        company=cast(Any, company),
        snapshots=kw.get("snapshots", []),
        facilities=kw.get("facilities", []),
        utilization=kw.get("utilization", {}),
        documents=kw.get("documents", []),
    )


@pytest.mark.parametrize(
    ("balances", "expected"),
    [
        (["100", "90", "76"], None),  # -24%: under the 25% line
        (["100", "90", "74"], Severity.HIGH),  # -26%
        (["100", "80", "60"], Severity.CRITICAL),  # -40%
        (["100", "60"], None),  # needs three months to span two
    ],
)
def test_cashflow_drop_spans_the_last_two_months(
    balances: list[str], expected: Severity | None
) -> None:
    found = rules.cashflow_drop(_inputs(snapshots=[_snap(b) for b in balances]), S)
    assert (found.severity if found else None) == expected
    if found:
        assert found.metrics["threshold_pct"] == "-25"
        assert len(found.source_record_ids) == 2


def test_utilization_needs_every_weekly_point_above_the_line_for_30_days() -> None:
    fac = SimpleNamespace(id=uuid.uuid4(), product=Product.WORKING_CAPITAL, sanctioned_limit=D(100))
    weeks = [TODAY - timedelta(weeks=w) for w in range(8, -1, -1)]

    def util(values: list[int]) -> dict[Any, Any]:
        return {
            fac.id: [
                SimpleNamespace(as_of=d, utilized_amount=D(v))
                for d, v in zip(weeks, values, strict=True)
            ]
        }

    # Five weeks above 90% = 28 days: not yet.
    short = _inputs(facilities=[fac], utilization=util([50, 50, 50, 50, 91, 92, 93, 94, 95]))
    assert rules.utilization_spikes(short, S) == []
    # Six weeks = 35 days: fires, medium.
    hit = _inputs(facilities=[fac], utilization=util([50, 50, 50, 91, 92, 93, 94, 95, 96]))
    [found] = rules.utilization_spikes(hit, S)
    assert found.metrics["days_above"] == 35 and found.severity == Severity.MEDIUM
    # A dip in between resets the run.
    dip = _inputs(facilities=[fac], utilization=util([91, 92, 93, 94, 80, 92, 93, 94, 95]))
    assert rules.utilization_spikes(dip, S) == []
    # Term loans aren't working-capital lines.
    term = SimpleNamespace(id=fac.id, product=Product.TERM_LOAN, sanctioned_limit=D(100))
    hit.facilities = [cast(Any, term)]
    assert rules.utilization_spikes(hit, S) == []


def test_doc_expiry_bounced_cheques_and_covenants() -> None:
    doc = SimpleNamespace(
        id=uuid.uuid4(), doc_type=DocumentType.TRADE_LICENSE, expiry_date=TODAY + timedelta(days=5)
    )
    [exp] = rules.doc_expiries(_inputs(documents=[doc]), S, TODAY)
    assert exp.severity == Severity.HIGH and exp.metrics["days_left"] == 5
    doc.expiry_date = TODAY + timedelta(days=31)
    assert rules.doc_expiries(_inputs(documents=[doc]), S, TODAY) == []

    assert rules.bounced_cheques(_inputs(snapshots=[_snap("1", bounced=0)]), S) is None
    found = rules.bounced_cheques(_inputs(snapshots=[_snap("1", bounced=1)]), S)
    assert found is not None and found.severity == Severity.MEDIUM

    # DSCR = 50 / (10 + 40) = 1.0, below a 1.25 covenant.
    fac = SimpleNamespace(
        id=uuid.uuid4(),
        product=Product.TERM_LOAN,
        covenants=[{"metric": "DSCR", "operator": ">=", "threshold": "1.25"}],
    )
    [breach] = rules.covenant_breaches(
        _inputs(snapshots=[_snap("1", ebitda="50")], facilities=[fac]), S
    )
    assert breach.metrics["actual"] == "1.0000" and breach.trigger == EwsTrigger.COVENANT_BREACH
    assert (
        rules.covenant_breaches(_inputs(snapshots=[_snap("1", ebitda="80")], facilities=[fac]), S)
        == []
    )


# ---------- the scan, end to end ----------


async def _run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    return dict((await client.get(f"/api/agent-runs/{run_id}")).json())


async def _approval_for(client: AsyncClient, company: uuid.UUID) -> dict[str, Any]:
    items = (await client.get("/api/approvals")).json()
    return next(
        i
        for i in items
        if i["company_id"] == str(company) and i["run"]["agent_name"] == "ews_review"
    )


@pytest.fixture(scope="module")
async def scan() -> dict[str, Any]:
    """Run the scan once for this module, as the RM."""
    from httpx import ASGITransport

    from app.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        await login(c, "rm@demo.local")
        r = await c.post("/api/agents/ews-scan")
        assert r.status_code == 202, r.text
        return await _run(c, r.json()["id"])


async def test_scan_flags_exactly_the_planted_anomalies(scan: dict[str, Any]) -> None:
    assert scan["status"] == "COMPLETED"
    nodes = [e["node"] for e in scan["trace"] if e["type"] == "node"]
    assert nodes == ["scan_portfolio", "create_ews_records", "fan_out"]
    result = scan["result"]
    flagged = {r["company_id"] for r in result["reviews"]}
    assert flagged == {str(DUNES), str(FALCON), str(OASIS), str(PEARL)}
    assert result["new_signals"] == result["signals_found"] == 4


async def test_each_company_gets_its_own_paused_review(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    await login(client, "rm@demo.local")
    children = (await client.get(f"/api/agent-runs?parent_run_id={scan['id']}")).json()
    assert len(children) == 4
    assert {c["status"] for c in children} == {"AWAITING_APPROVAL"}
    assert {c["parent_run_id"] for c in children} == {scan["id"]}

    child = await _run(client, next(c["id"] for c in children if c["company_id"] == str(DUNES)))
    nodes = [e["node"] for e in child["trace"] if e["type"] == "node"]
    assert nodes == ["load_signals", "analyse_root_cause", "draft_outreach", "propose_escalation"]
    assert [e["type"] for e in child["trace"]].count("llm") == 2
    assert {r["kind"] for r in child["cited_records"]} >= {"Account", "Financial snapshot"}

    sig = await session.scalar(
        select(EarlyWarningSignal).where(EarlyWarningSignal.company_id == DUNES)
    )
    assert sig is not None and sig.trigger == EwsTrigger.CASHFLOW_DROP
    assert sig.severity == Severity.HIGH and sig.status == EwsStatus.OPEN
    assert sig.root_cause_summary and "average bank balance fell" in sig.root_cause_summary


async def test_severity_decides_the_action(client: AsyncClient, scan: dict[str, Any]) -> None:
    await login(client, "rm@demo.local")
    actions = {
        c: (await _approval_for(client, c))["action_type"] for c in (DUNES, FALCON, OASIS, PEARL)
    }
    assert actions == {
        DUNES: "ESCALATE_EWS",  # HIGH: balance down 38%
        OASIS: "ESCALATE_EWS",  # HIGH: three bounced cheques
        FALCON: "SEND_EMAIL",  # MEDIUM: utilisation
        PEARL: "SEND_EMAIL",  # MEDIUM: licence expiring in 18 days
    }
    email = await _approval_for(client, FALCON)
    assert email["proposed_payload"]["to_address"].endswith("@falcon-steel.example")
    assert "early warning" not in email["proposed_payload"]["body"].lower()


async def test_scanning_again_creates_nothing_new(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    before = await session.scalar(select(func.count()).select_from(EarlyWarningSignal))
    await login(client, "credit@demo.local")
    r = await client.post("/api/agents/ews-scan")
    again = await _run(client, r.json()["id"])
    assert again["status"] == "COMPLETED"
    assert again["result"]["signals_found"] == 4 and again["result"]["new_signals"] == 0
    assert again["result"]["reviews"] == []
    assert await session.scalar(select(func.count()).select_from(EarlyWarningSignal)) == before


def _companies_scanned(run: dict[str, Any]) -> int:
    tool = next(e for e in run["trace"] if e.get("name") == "scan_portfolio")
    return int(tool["input"]["companies"])


async def test_cron_and_admin_scans_cover_the_bank_and_an_rms_scan_only_theirs(
    client: AsyncClient, scan: dict[str, Any]
) -> None:
    assert _companies_scanned(scan) == 8  # the module's scan, run as Layla
    async with get_sessionmaker()() as s:
        cron = await ews_graph.start_scan(s, None)
        await s.commit()
    await ews_graph.drive_scan(cron.id)
    await login(client, "admin@demo.local")
    admin = (await client.post("/api/agents/ews-scan")).json()["id"]
    for run_id in (str(cron.id), admin):
        run = await _run(client, run_id)
        assert run["status"] == "COMPLETED" and _companies_scanned(run) == 15
        assert run["result"]["signals_found"] == 4 and run["result"]["new_signals"] == 0
    # A scan belongs to whoever started it, so no RM can open the cron scan.
    await login(client, "rm@demo.local")
    assert (await client.get(f"/api/agent-runs/{cron.id}")).status_code == 404


async def test_escalation_needs_a_credit_officer_then_opens_an_investigation(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    await login(client, "rm@demo.local")
    item = await _approval_for(client, DUNES)
    assert item["four_eyes"] is True and item["can_review"] is False
    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 403

    await login(client, "credit@demo.local")
    locked = {**item["proposed_payload"], "signal_ids": [str(uuid.uuid4())]}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE", "payload": locked}
    )
    assert r.status_code == 422 and "signal ids" in r.json()["detail"]

    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 200, r.text
    assert r.json()["run"]["status"] == "COMPLETED"
    session.expire_all()
    sig = await session.scalar(
        select(EarlyWarningSignal).where(EarlyWarningSignal.company_id == DUNES)
    )
    assert sig is not None and sig.status == EwsStatus.INVESTIGATING
    titles = set(await session.scalars(select(Task.title).where(Task.company_id == DUNES)))
    assert "Credit review of early-warning signals: Dunes Freight" in titles
    assert item["proposed_payload"]["rm_task_title"] in titles

    run = await _run(client, item["run"]["id"])
    assert run["result"]["decisions"] == {"escalation": "APPROVED"}
    assert [e["node"] for e in run["trace"] if e["type"] == "node"][-2:] == [
        "apply_escalation",
        "summarise",
    ]


async def test_edited_outreach_goes_to_the_outbox_as_simulated(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    await login(client, "rm@demo.local")
    item = await _approval_for(client, FALCON)
    edited = {**item["proposed_payload"], "subject": "Quick catch-up this week?"}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE", "payload": edited}
    )
    assert r.json()["status"] == "EDITED_AND_APPROVED"
    msg = await session.scalar(
        select(OutboxMessage).where(OutboxMessage.approval_item_id == uuid.UUID(item["id"]))
    )
    assert msg is not None and msg.subject == "Quick catch-up this week?"
    assert msg.status.value == "SIMULATED"


async def test_rejected_outreach_sends_nothing(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    await login(client, "rm@demo.local")
    item = await _approval_for(client, PEARL)
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve",
        json={"decision": "REJECT", "note": "Renewal is already filed"},
    )
    assert r.json()["run"]["status"] == "REJECTED"
    n = await session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.approval_item_id == uuid.UUID(item["id"]))
    )
    assert n == 0
    assert (await audit.verify_chain(session)).ok


async def test_proposals_are_idempotent_per_thread(
    session: AsyncSession, scan: dict[str, Any]
) -> None:
    child_ids = [uuid.UUID(r["child_run_id"]) for r in scan["result"]["reviews"]]
    per_run = (
        await session.execute(
            select(ApprovalItem.agent_run_id, func.count())
            .where(ApprovalItem.agent_run_id.in_(child_ids))
            .group_by(ApprovalItem.agent_run_id)
        )
    ).all()
    assert len(per_run) == 4 and all(n == 1 for _, n in per_run)
    keys = list(
        await session.scalars(
            select(ApprovalItem.idempotency_key).where(ApprovalItem.agent_run_id.in_(child_ids))
        )
    )
    assert all(k.startswith("ews_review:") for k in keys)
    runs = list(await session.scalars(select(AgentRun).where(AgentRun.id.in_(child_ids))))
    # Every child's trace is persisted, including the pause for approval.
    assert all(any(e["type"] == "interrupt" for e in r.trace) for r in runs)


# ---------- Risk radar API ----------


async def test_risk_radar_lists_by_severity_and_resolves_with_a_note(
    client: AsyncClient, scan: dict[str, Any]
) -> None:
    await login(client, "credit@demo.local")
    rows = (await client.get("/api/ews")).json()
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    ranks = [order.index(r["severity"]) for r in rows]
    assert ranks == sorted(ranks) and len(rows) >= 4
    oasis = next(r for r in rows if r["company_id"] == str(OASIS))
    assert oasis["metrics"]["count"] == 3 and oasis["company_name"] == "Oasis Clinics"

    r = await client.patch(f"/api/ews/{oasis['id']}", json={"status": "RESOLVED"})
    assert r.status_code == 422
    r = await client.patch(
        f"/api/ews/{oasis['id']}",
        json={"status": "RESOLVED", "note": "Cheques re-presented and cleared"},
    )
    assert r.status_code == 200
    assert r.json()["resolved_by_name"] == "Omar Faris" and r.json()["status"] == "RESOLVED"
    r = await client.patch(
        f"/api/ews/{oasis['id']}", json={"status": "INVESTIGATING", "note": "again"}
    )
    assert r.status_code == 409
    resolved = (await client.get("/api/ews?state=resolved")).json()
    assert [x["id"] for x in resolved] == [oasis["id"]]

    await login(client, "compliance@demo.local")
    pearl = next(r for r in rows if r["company_id"] == str(PEARL))
    r = await client.patch(f"/api/ews/{pearl['id']}", json={"status": "INVESTIGATING"})
    assert r.status_code == 403
    assert (await client.post("/api/agents/ews-scan")).status_code == 403
