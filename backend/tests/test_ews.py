"""Phase 4, graph 3: early-warning rules, the portfolio scan, per-company reviews, Risk radar."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graphs import ews as ews_graph
from app.core.config import Settings, get_settings
from app.db.seed import sid
from app.db.session import get_sessionmaker
from app.models import (
    AgentRun,
    ApprovalItem,
    Document,
    EarlyWarningSignal,
    OutboxMessage,
    Task,
)
from app.models.base import utcnow
from app.models.enums import (
    DocumentType,
    EwsStatus,
    EwsTrigger,
    Product,
    Severity,
    VerificationStatus,
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


LICENCE, CERTIFICATE = DocumentType.TRADE_LICENSE, DocumentType.CR_CERTIFICATE


def _doc(
    doc_type: DocumentType,
    days: int | None,
    state: VerificationStatus = VerificationStatus.VERIFIED,
    added: int = 0,
) -> Any:
    """A document expiring `days` after TODAY (None: undated), added `added` hours after others."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        doc_type=doc_type,
        expiry_date=None if days is None else TODAY + timedelta(days=days),
        verification_status=state,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=added),
    )


def _expiry_alerts(*docs: Any) -> list[tuple[uuid.UUID, int]]:
    """The cited document and days left of each expiry the rule finds."""
    found = rules.doc_expiries(_inputs(documents=list(docs)), S, TODAY)
    return [(f.source_record_ids[0], f.metrics["days_left"]) for f in found]


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
    doc = _doc(LICENCE, 5)
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


# Only the document in force can expire, as on the Accounts list: for each type, the verified
# document that expires last.


def test_a_verified_renewal_stops_the_expiry_alert() -> None:
    old = _doc(LICENCE, 18)
    assert _expiry_alerts(old) == [(old.id, 18)]
    assert _expiry_alerts(old, _doc(LICENCE, 400, added=1)) == []


def test_a_renewal_that_expires_soon_alerts_on_itself() -> None:
    old, renewal = _doc(LICENCE, 5), _doc(LICENCE, 25, added=1)
    assert _expiry_alerts(old, renewal) == [(renewal.id, 25)]


@pytest.mark.parametrize(
    ("days", "severity"),
    [
        (31, None),
        (30, Severity.MEDIUM),
        (8, Severity.MEDIUM),
        (7, Severity.HIGH),
        (-3, Severity.HIGH),  # a lapsed licence still in force keeps alerting
    ],
)
def test_expiry_alerts_within_30_days_and_is_high_within_7(
    days: int, severity: Severity | None
) -> None:
    found = rules.doc_expiries(_inputs(documents=[_doc(LICENCE, days)]), S, TODAY)
    expected = [] if severity is None else [(severity, days)]
    assert [(f.severity, f.metrics["days_left"]) for f in found] == expected


def test_a_pending_renewal_leaves_the_old_licence_alerting() -> None:
    old = _doc(LICENCE, 18)
    pending = _doc(LICENCE, 400, VerificationStatus.PENDING, added=1)
    assert _expiry_alerts(old, pending) == [(old.id, 18)]


def test_a_rejected_upload_is_ignored() -> None:
    old, renewed = _doc(LICENCE, 18), _doc(LICENCE, 400)
    # A rejected renewal doesn't stop the alert, and a rejected upload due sooner doesn't raise one.
    rejected = VerificationStatus.REJECTED
    assert _expiry_alerts(old, _doc(LICENCE, 400, rejected, added=1)) == [(old.id, 18)]
    assert _expiry_alerts(renewed, _doc(LICENCE, 3, rejected, added=1)) == []


def test_each_type_has_one_document_in_force() -> None:
    # Added after the licence, the certificate comes second unless the findings are sorted.
    licence, certificate = _doc(LICENCE, 5), _doc(CERTIFICATE, 20, added=2)
    # Other types and undated copies don't count.
    others = [_doc(DocumentType.BANK_STATEMENT, 2), _doc(LICENCE, None, added=1)]
    found = rules.doc_expiries(_inputs(documents=[licence, certificate, *others]), S, TODAY)
    assert [(f.metrics["document_type"], f.severity) for f in found] == [
        ("CR_CERTIFICATE", Severity.MEDIUM),
        ("TRADE_LICENSE", Severity.HIGH),
    ]
    # Of two copies with the same date, the first one added stays in force whatever order they
    # load in, so uploading a copy doesn't raise a second alert. The copy's id sorts first, so
    # going by id alone would pick it.
    copy = _doc(LICENCE, 5, added=1)
    copy.id = uuid.UUID(int=0)
    assert _expiry_alerts(licence, copy) == _expiry_alerts(copy, licence) == [(licence.id, 5)]


@pytest.mark.parametrize(
    ("doc_type", "days", "expiry", "line"),
    [
        ("TRADE_LICENSE", 18, "2026-12-15", "the trade licence expires on 2026-12-15 (in 18 days)"),
        ("TRADE_LICENSE", 1, "2026-11-28", "the trade licence expires on 2026-11-28 (in 1 day)"),
        ("CR_CERTIFICATE", 0, "2026-11-27", "the CR certificate expires today (2026-11-27)"),
        ("TRADE_LICENSE", -3, "2026-11-24", "the trade licence expired on 2026-11-24 (3 days ago)"),
    ],
)
def test_the_mock_root_cause_words_an_expiry_plainly(
    doc_type: str, days: int, expiry: str, line: str
) -> None:
    metrics = {"document_type": doc_type, "expiry_date": expiry, "days_left": days}
    assert ews_graph._sig_line({"trigger": "DOC_EXPIRY", "metrics": metrics}, "BHD") == line


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


# Expiry alerts follow the document in force. An alert left open on a document that no longer is
# (after a verified renewal, or raised on an upload back when every upload counted) is marked with
# the one that is, so the Risk radar doesn't show its stale day count.

PEARL_LICENCE = sid("doc", "pearl-bay", "licence")
AZURE = sid("company", "azure-pack")  # Yusuf's, nothing planted


def _licence(
    company: uuid.UUID,
    days: int,
    state: VerificationStatus,
    doc_type: DocumentType = DocumentType.TRADE_LICENSE,
) -> Document:
    """A trade licence (or `doc_type`) for `company` that expires `days` from today."""
    return Document(
        id=uuid.uuid4(),
        company_id=company,
        doc_type=doc_type,
        file_name=f"{doc_type.value.lower()}-renewal.pdf",
        expiry_date=utcnow().date() + timedelta(days=days),
        verification_status=state,
        extracted_fields={},
    )


def _alert_on_upload(
    company: uuid.UUID,
    doc_type: DocumentType = DocumentType.TRADE_LICENSE,
    status: EwsStatus = EwsStatus.OPEN,
) -> tuple[Document, EarlyWarningSignal]:
    """A pending upload due in 10 days, and the alert a scan raised on it when uploads counted."""
    upload = _licence(company, 10, VerificationStatus.PENDING, doc_type)
    alert = EarlyWarningSignal(
        id=uuid.uuid4(),
        company_id=company,
        trigger=EwsTrigger.DOC_EXPIRY,
        severity=Severity.MEDIUM,
        status=status,
        metrics={
            "document_type": doc_type.value,
            "expiry_date": str(upload.expiry_date),
            "days_left": 10,
            "threshold_days": 30,
            "source_record_ids": [str(upload.id)],
        },
        detected_at=utcnow(),
    )
    return upload, alert


def _mark(doc: Document) -> dict[str, str]:
    """The mark a scan gives an alert whose document `doc` has replaced."""
    return {"document_id": str(doc.id), "expiry_date": str(doc.expiry_date)}


async def _scan(client: AsyncClient) -> dict[str, Any]:
    """Scan as whoever is signed in. Returns the findings per company, the counts in
    `create_ews_records`' trace, and the reviews it started."""
    r = await client.post("/api/agents/ews-scan")
    run = await _run(client, r.json()["id"])
    assert run["status"] == "COMPLETED"
    tools = {e["name"]: e["output"] for e in run["trace"] if e["type"] == "tool"}
    return {
        "findings": tools["scan_portfolio"],
        **tools["create_ews_records"],
        "reviews": run["result"]["reviews"],
    }


async def _stored_alerts(session: AsyncSession, company: uuid.UUID) -> list[dict[str, Any]]:
    """The company's expiry alerts as stored, oldest first."""
    rows = await session.execute(
        select(
            EarlyWarningSignal.id,
            EarlyWarningSignal.status,
            EarlyWarningSignal.severity,
            EarlyWarningSignal.metrics,
        )
        .where(
            EarlyWarningSignal.company_id == company,
            EarlyWarningSignal.trigger == EwsTrigger.DOC_EXPIRY,
        )
        .order_by(EarlyWarningSignal.detected_at)
    )
    return [dict(row) for row in rows.mappings()]


async def _put_back(session: AsyncSession, alert: dict[str, Any]) -> None:
    """Restore an alert as `_stored_alerts` read it."""
    await session.execute(
        update(EarlyWarningSignal)
        .where(EarlyWarningSignal.id == alert["id"])
        .values(status=alert["status"], severity=alert["severity"], metrics=alert["metrics"])
    )


async def test_the_scan_follows_the_licence_in_force_without_a_second_alert(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    """Pearl Bay's licence expires in 18 days. A pending renewal and a rejected upload leave its
    alert as it is. Once the renewal is verified, the scan stops finding the expiry and marks the
    open alert with the renewal; if the renewal is rejected after all, the mark goes."""
    [alert] = await _stored_alerts(session, PEARL)
    assert alert["metrics"]["source_record_ids"] == [str(PEARL_LICENCE)]
    assert alert["status"] == EwsStatus.OPEN
    # A renewal waiting for verification, and a rejected upload that would expire sooner.
    renewal = _licence(PEARL, 400, VerificationStatus.PENDING)
    rejected = _licence(PEARL, 3, VerificationStatus.REJECTED)
    session.add_all([renewal, rejected])
    await session.commit()
    try:
        await login(client, "credit@demo.local")
        # The old licence is still the one in force: its open alert is refreshed, not repeated.
        scanned = await _scan(client)
        assert scanned["findings"][str(PEARL)] == ["DOC_EXPIRY"] and scanned["new_signals"] == 0
        assert await _stored_alerts(session, PEARL) == [alert]

        renewal.verification_status = VerificationStatus.VERIFIED
        await session.commit()
        scanned = await _scan(client)
        assert str(PEARL) not in scanned["findings"] and scanned["new_signals"] == 0
        # The alert already open waits for someone to resolve it with a note, like any other. It
        # says which licence is in force now; its day count, severity and status stay as they were.
        marked = {**alert, "metrics": {**alert["metrics"], "in_force": _mark(renewal)}}
        assert await _stored_alerts(session, PEARL) == [marked]
        assert scanned["marked_not_in_force"] == 1

        # The old licence is back in force, so its alert is refreshed again, without the mark.
        renewal.verification_status = VerificationStatus.REJECTED
        await session.commit()
        scanned = await _scan(client)
        assert scanned["findings"][str(PEARL)] == ["DOC_EXPIRY"] and scanned["new_signals"] == 0
        assert await _stored_alerts(session, PEARL) == [alert]
        assert scanned["marked_not_in_force"] == 0
    finally:
        for row in (renewal, rejected):
            await session.delete(row)
        await _put_back(session, alert)
        await session.commit()


async def test_a_renewal_due_within_the_window_raises_its_own_alert(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    """A verified renewal that expires in 25 days takes over and raises an alert of its own. The
    old licence's alert stays open, marked with the renewal."""
    [alert] = await _stored_alerts(session, PEARL)
    renewal = _licence(PEARL, 25, VerificationStatus.VERIFIED)
    session.add(renewal)
    await session.commit()
    scanned: dict[str, Any] = {"reviews": []}
    try:
        await login(client, "credit@demo.local")
        scanned = await _scan(client)
        assert scanned["new_signals"] == 1 and scanned["marked_not_in_force"] == 1
        old, new = await _stored_alerts(session, PEARL)
        assert old == {**alert, "metrics": {**alert["metrics"], "in_force": _mark(renewal)}}
        assert new["metrics"]["source_record_ids"] == [str(renewal.id)]
        assert "in_force" not in new["metrics"]
        assert (new["status"], new["severity"], new["metrics"]["days_left"]) == (
            EwsStatus.OPEN,
            Severity.MEDIUM,
            25,
        )
    finally:
        # The new alert and its review; the review's approval goes with its run.
        for review in scanned["reviews"]:
            ids = [uuid.UUID(i) for i in review["signal_ids"]]
            await session.execute(delete(EarlyWarningSignal).where(EarlyWarningSignal.id.in_(ids)))
            child = uuid.UUID(review["child_run_id"])
            await session.execute(delete(AgentRun).where(AgentRun.id == child))
        await session.delete(renewal)
        await _put_back(session, alert)
        await session.commit()


async def test_an_alert_raised_on_an_upload_is_marked_with_the_licence_in_force(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    """Scans once raised alerts on pending uploads too. The scan marks such an alert with the
    verified licence in force and leaves the rest of it, and the alert on that licence, alone."""
    upload, planted = _alert_on_upload(PEARL)
    session.add_all([upload, planted])
    await session.commit()
    licence = await session.get(Document, PEARL_LICENCE)
    assert licence is not None
    try:
        await login(client, "credit@demo.local")
        scanned = await _scan(client)
        assert scanned["new_signals"] == 0 and scanned["marked_not_in_force"] == 1
        stored = {a["id"]: a for a in await _stored_alerts(session, PEARL)}
        assert stored.pop(planted.id) == {
            "id": planted.id,
            "status": EwsStatus.OPEN,
            "severity": Severity.MEDIUM,
            "metrics": {**planted.metrics, "in_force": _mark(licence)},
        }
        assert [a["metrics"].get("in_force") for a in stored.values()] == [None]
    finally:
        for row in (planted, upload):
            await session.delete(row)
        await session.commit()


async def test_the_mark_goes_once_the_document_is_back_in_force_even_if_not_due(
    client: AsyncClient,
    session: AsyncSession,
    scan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the window cut below the 18 days Pearl Bay's licence has left, no finding refreshes
    its alert once a rejected renewal hands back to it; the scan still removes the mark."""
    [alert] = await _stored_alerts(session, PEARL)
    renewal = _licence(PEARL, 400, VerificationStatus.VERIFIED)
    session.add(renewal)
    await session.commit()
    try:
        await login(client, "credit@demo.local")
        assert (await _scan(client))["marked_not_in_force"] == 1
        monkeypatch.setattr(get_settings(), "ews_doc_expiry_days", 14)
        renewal.verification_status = VerificationStatus.REJECTED
        await session.commit()
        scanned = await _scan(client)
        assert str(PEARL) not in scanned["findings"] and scanned["marked_not_in_force"] == 0
        assert await _stored_alerts(session, PEARL) == [alert]
    finally:
        await session.delete(renewal)
        await _put_back(session, alert)
        await session.commit()


async def test_an_rms_scan_marks_only_alerts_on_their_accounts(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    pearl_upload, pearl_alert = _alert_on_upload(PEARL)  # Layla's account
    azure_upload, azure_alert = _alert_on_upload(AZURE)  # Yusuf's
    planted = [pearl_upload, pearl_alert, azure_upload, azure_alert]
    session.add_all(planted)
    await session.commit()
    pearl_licence = await session.get(Document, PEARL_LICENCE)
    azure_licence = await session.get(Document, sid("doc", "azure-pack", "licence"))
    assert pearl_licence is not None and azure_licence is not None

    async def mark_on(alert: EarlyWarningSignal) -> Any:
        metrics = await session.scalar(
            select(EarlyWarningSignal.metrics).where(EarlyWarningSignal.id == alert.id)
        )
        return metrics.get("in_force")

    try:
        await login(client, "rm@demo.local")
        assert (await _scan(client))["marked_not_in_force"] == 1
        assert await mark_on(pearl_alert) == _mark(pearl_licence)
        assert await mark_on(azure_alert) is None
        await login(client, "rm2@demo.local")
        assert (await _scan(client))["marked_not_in_force"] == 1
        assert await mark_on(azure_alert) == _mark(azure_licence)
    finally:
        for row in planted:
            await session.delete(row)
        await session.commit()


async def test_an_investigated_alert_is_marked_and_a_resolved_one_left_alone(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    """An escalated expiry alert is under investigation, often still when the renewal arrives, so
    it is marked like an open one. A resolved alert is history, and the scan leaves it as it is."""
    investigated_upload, investigated = _alert_on_upload(PEARL, status=EwsStatus.INVESTIGATING)
    resolved_upload, resolved = _alert_on_upload(PEARL, status=EwsStatus.RESOLVED)
    planted = [investigated_upload, investigated, resolved_upload, resolved]
    session.add_all(planted)
    await session.commit()
    licence = await session.get(Document, PEARL_LICENCE)
    assert licence is not None
    try:
        await login(client, "credit@demo.local")
        # The count is of alerts that carry the mark, so a second scan reports it again.
        for _ in range(2):
            scanned = await _scan(client)
            assert scanned["new_signals"] == 0 and scanned["marked_not_in_force"] == 1
        stored = {a["id"]: a for a in await _stored_alerts(session, PEARL)}
        assert stored[investigated.id] == {
            "id": investigated.id,
            "status": EwsStatus.INVESTIGATING,
            "severity": Severity.MEDIUM,
            "metrics": {**investigated.metrics, "in_force": _mark(licence)},
        }
        assert stored[resolved.id]["metrics"] == resolved.metrics
    finally:
        for row in planted:
            await session.delete(row)
        await session.commit()


async def test_a_certificate_alert_is_marked_with_the_certificate_or_nulls(
    client: AsyncClient, session: AsyncSession, scan: dict[str, Any]
) -> None:
    """The mark follows the alert's own document type. Once no CR certificate is in force at all,
    it holds nulls, and the alert's day count, severity and status still stay as they were. With
    nothing in force of either type, the account is still scanned and its alerts still marked."""
    certificate_id = sid("doc", "pearl-bay", "cr")
    [licence_alert] = await _stored_alerts(session, PEARL)
    upload, planted = _alert_on_upload(PEARL, DocumentType.CR_CERTIFICATE)
    session.add_all([upload, planted])
    await session.commit()
    certificate = await session.get(Document, certificate_id)
    assert certificate is not None

    async def set_state(doc_id: uuid.UUID, state: VerificationStatus) -> None:
        await session.execute(
            update(Document).where(Document.id == doc_id).values(verification_status=state)
        )
        await session.commit()

    async def certificate_state(state: VerificationStatus) -> None:
        await set_state(certificate_id, state)

    async def stored() -> dict[str, Any]:
        return {a["id"]: a for a in await _stored_alerts(session, PEARL)}[planted.id]

    try:
        await login(client, "credit@demo.local")
        await _scan(client)
        assert (await stored())["metrics"]["in_force"] == _mark(certificate)

        await certificate_state(VerificationStatus.REJECTED)
        scanned = await _scan(client)
        assert scanned["new_signals"] == 0 and scanned["marked_not_in_force"] == 1
        nulls = {"document_id": None, "expiry_date": None}
        assert await stored() == {
            "id": planted.id,
            "status": EwsStatus.OPEN,
            "severity": Severity.MEDIUM,
            "metrics": {**planted.metrics, "in_force": nulls},
        }

        # No licence in force either: nothing alerts, and both alerts hold nulls.
        await set_state(PEARL_LICENCE, VerificationStatus.REJECTED)
        scanned = await _scan(client)
        assert str(PEARL) not in scanned["findings"] and scanned["marked_not_in_force"] == 2
        assert (await stored())["metrics"]["in_force"] == nulls
        [licence_now] = [a for a in await _stored_alerts(session, PEARL) if a["id"] != planted.id]
        assert licence_now == {
            **licence_alert,
            "metrics": {**licence_alert["metrics"], "in_force": nulls},
        }
    finally:
        await certificate_state(VerificationStatus.VERIFIED)
        await set_state(PEARL_LICENCE, VerificationStatus.VERIFIED)
        await _put_back(session, licence_alert)
        for row in (planted, upload):
            await session.delete(row)
        await session.commit()


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
