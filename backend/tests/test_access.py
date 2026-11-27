"""Relationship managers see only their own accounts, on every route that exposes account data."""

import asyncio
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm, runtime
from app.agents.actions import ACTIONS, derived_id
from app.agents.graphs import demo_followup
from app.api.routes import agents as agent_routes
from app.db.seed import sid
from app.db.session import get_engine, get_sessionmaker
from app.main import create_app
from app.models import (
    AgentRun,
    ApprovalItem,
    AuditEvent,
    Company,
    Deal,
    Document,
    EarlyWarningSignal,
    Interaction,
    Task,
    User,
)
from app.models.base import utcnow
from app.models.enums import (
    ActionType,
    AgentRunStatus,
    ApprovalStatus,
    DocumentType,
    EwsStatus,
    EwsTrigger,
    KybStatus,
    Role,
    Severity,
    VerificationStatus,
)
from app.services.ews_rules import EXPIRING_DOCS
from app.services.tasks import may_update
from tests.conftest import login

FALCON = sid("company", "falcon-steel")  # Layla's
OASIS = sid("company", "oasis-clinics")  # Layla's
GULF_SPICE = sid("company", "gulf-spice")  # Layla's
PEARL = sid("company", "pearl-bay")  # Layla's, licence due for renewal
SADAF = sid("company", "sadaf-build")  # Layla's; two tests hand it to Yusuf and back
TIDE = sid("company", "tide-print")  # Yusuf's
LULU_DEAL = sid("deal", "lulu-bakers")  # Yusuf's
FALCON_DEAL = sid("deal", "falcon-steel")  # Layla's
SADAF_DEAL = sid("deal", "sadaf-build")  # Layla's, open
LAYLA, YUSUF, OMAR = sid("user", "rm"), sid("user", "rm2"), sid("user", "credit")
OTHER_RM = "rm2@demo.local"


async def _names(client: AsyncClient, email: str) -> list[str]:
    await login(client, email)
    return [r["trading_name"] for r in (await client.get("/api/accounts")).json()]


async def _looks_missing(
    client: AsyncClient, method: str, url: str, record: uuid.UUID | str, **kw: Any
) -> None:
    """A record the user may not see answers exactly like one that doesn't exist."""
    seen = await client.request(method, url.format(record), **kw)
    missing = await client.request(method, url.format(uuid.uuid4()), **kw)
    assert seen.status_code == 404, (method, url, seen.status_code, seen.text)
    assert (seen.status_code, seen.text) == (missing.status_code, missing.text), (method, url)


def _former(role: Role) -> User:
    """Someone who has left: inactive, and the RM of no account."""
    return User(
        id=uuid.uuid4(),
        email=f"former.{uuid.uuid4().hex[:8]}@demo.local",
        full_name=f"Former {role.value}",
        role=role,
        password_hash="-",
        is_active=False,
    )


def _ids(tasks: list[Task]) -> set[str]:
    return {str(t.id) for t in tasks}


def _in_force_expiry(docs: list[Document]) -> date | None:
    """The soonest of the latest verified expiry of each expiring document type."""
    latest: dict[DocumentType, date] = {}
    for d in docs:
        verified = d.verification_status == VerificationStatus.VERIFIED
        if verified and d.doc_type in EXPIRING_DOCS and d.expiry_date is not None:
            latest[d.doc_type] = max(d.expiry_date, latest.get(d.doc_type, d.expiry_date))
    return min(latest.values(), default=None)


async def test_each_rm_gets_their_own_accounts_and_others_get_all(client: AsyncClient) -> None:
    layla, yusuf = await _names(client, "rm@demo.local"), await _names(client, OTHER_RM)
    assert (len(layla), len(yusuf)) == (8, 7) and not set(layla) & set(yusuf)
    for email in ("credit@demo.local", "compliance@demo.local", "admin@demo.local"):
        assert set(await _names(client, email)) == set(layla) | set(yusuf)


async def test_lists_open_in_the_order_each_role_needs(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Credit officers: most open alerts, then highest risk. Compliance: flagged, then pending
    renewal, then the soonest expiry of a document in force, undated last. Then by name."""
    today = utcnow().date()
    companies = {c.id: c for c in await session.scalars(select(Company))}
    docs = list(await session.scalars(select(Document)))
    expiry = {cid: _in_force_expiry([d for d in docs if d.company_id == cid]) for cid in companies}
    low, lower = sorted(companies.values(), key=lambda c: (c.risk_rating, c.legal_name))[:2]
    # Flag and put up for renewal the accounts that expire last, so their rank has to win.
    plain = sorted(
        (c for c in companies.values() if c.kyb_status == KybStatus.VERIFIED),
        key=lambda c: expiry[c.id] or date.max,
    )
    undated, flagged, pending = plain[0], plain[-2], plain[-1]
    undated_docs = [d for d in docs if d.company_id == undated.id and d.doc_type in EXPIRING_DOCS]
    undated_dates = {d.id: d.expiry_date for d in undated_docs}
    renewal = today + timedelta(days=400)
    planted: list[Any] = [
        EarlyWarningSignal(
            id=uuid.uuid4(),
            company_id=c.id,
            trigger=EwsTrigger.BOUNCED_CHEQUES,
            severity=Severity.LOW,
            status=s,
            metrics={"count": 1, "period": "2026-10-31"},
            detected_at=utcnow(),
        )
        for c, s in [(low, EwsStatus.OPEN), (low, EwsStatus.OPEN), (lower, EwsStatus.INVESTIGATING)]
    ]
    # Pearl Bay's licence is renewed and verified, so its old date no longer counts and its
    # certificate sets the date. Nor do a pending and a rejected certificate that would run
    # longer than the one in force, or a document of another type due sooner. Pending and
    # rejected uploads don't give the undated account a date either.
    for company_id, doc_type, days, state in [
        (PEARL, DocumentType.TRADE_LICENSE, 400, VerificationStatus.VERIFIED),
        (PEARL, DocumentType.CR_CERTIFICATE, 800, VerificationStatus.PENDING),
        (PEARL, DocumentType.CR_CERTIFICATE, 900, VerificationStatus.REJECTED),
        (PEARL, DocumentType.BANK_STATEMENT, 2, VerificationStatus.VERIFIED),
        (undated.id, DocumentType.TRADE_LICENSE, 800, VerificationStatus.PENDING),
        (undated.id, DocumentType.CR_CERTIFICATE, 900, VerificationStatus.REJECTED),
    ]:
        planted.append(
            Document(
                id=uuid.uuid4(),
                company_id=company_id,
                doc_type=doc_type,
                file_name=f"planted-{doc_type.value.lower()}.txt",
                expiry_date=today + timedelta(days=days),
                verification_status=state,
                extracted_fields={},
            )
        )
    session.add_all(planted)
    flagged.kyb_status, pending.kyb_status = KybStatus.FLAGGED, KybStatus.PENDING_RENEWAL
    for d in undated_docs:
        d.expiry_date = None
    await session.commit()
    try:
        await login(client, "credit@demo.local")
        rows = (await client.get("/api/accounts")).json()
        keys = [(-r["open_ews"], -r["risk_rating"], r["legal_name"]) for r in rows]
        assert keys == sorted(keys)
        alerts = {r["id"]: r["open_ews"] for r in rows}
        assert (alerts[str(low.id)], alerts[str(lower.id)]) == (2, 1)

        await login(client, "compliance@demo.local")
        rows = (await client.get("/api/accounts")).json()
        rank = {"FLAGGED": 0, "PENDING_RENEWAL": 1, "VERIFIED": 2}

        def place(r: dict[str, Any]) -> tuple[int, bool, str, str]:
            due = r["next_doc_expiry"]
            return rank[r["kyb_status"]], due is None, due or "", r["legal_name"]

        order = [place(r) for r in rows]
        assert order == sorted(order)
        docs = list(await session.scalars(select(Document)))
        shown = {r["id"]: r["next_doc_expiry"] for r in rows}
        for cid in companies:
            expected = _in_force_expiry([d for d in docs if d.company_id == cid])
            assert shown[str(cid)] == (expected.isoformat() if expected else None), cid
        pearl_cr = await session.get(Document, sid("doc", "pearl-bay", "cr"))
        assert pearl_cr is not None and pearl_cr.expiry_date is not None
        assert shown[str(PEARL)] == min(renewal, pearl_cr.expiry_date).isoformat()
        assert shown[str(undated.id)] is None
    finally:
        for row in planted:
            await session.delete(row)
        flagged.kyb_status = pending.kyb_status = KybStatus.VERIFIED
        for d in undated_docs:
            d.expiry_date = undated_dates[d.id]
        await session.commit()


@pytest.mark.parametrize(
    "part",
    ["", "/documents", "/ews", "/facilities", "/financials", "/interactions", "/tasks"],
)
async def test_account_pages_of_another_rm_look_missing(client: AsyncClient, part: str) -> None:
    await login(client, OTHER_RM)
    await _looks_missing(client, "GET", "/api/accounts/{}" + part, FALCON)
    assert (await client.get(f"/api/accounts/{TIDE}{part}")).status_code == 200


def _writes(
    company: uuid.UUID, deal: uuid.UUID, doc: uuid.UUID
) -> list[tuple[str, dict[str, Any]]]:
    note = {"interaction_type": "CALL", "occurred_at": utcnow().isoformat(), "summary": "Hi there"}
    new_deal = {"title": "Sneaky", "product": "TERM_LOAN", "requested_amount": "1000"}
    return [
        (f"/api/accounts/{company}/interactions", {"json": note}),
        ("/api/deals", {"json": {"company_id": str(company), **new_deal}}),
        ("/api/tasks", {"json": {"company_id": str(company), "title": "Sneaky task"}}),
        (f"/api/agents/briefing/{company}", {}),
        (f"/api/agents/cam/{deal}", {}),
        (f"/api/dev/agents/demo-followup/{company}", {}),
        (f"/api/documents/{doc}/check", {}),
        (
            "/api/documents/upload",
            {
                "data": {"company_id": str(company), "doc_type": "TRADE_LICENSE"},
                "files": {"file": ("a.txt", b"Expiry: 2030-01-01", "text/plain")},
            },
        ),
    ]


async def _rows_on(session: AsyncSession, companies: list[uuid.UUID]) -> list[int | None]:
    return [
        await session.scalar(
            select(func.count()).select_from(model).where(model.company_id.in_(companies))
        )
        for model in (Deal, Task, Interaction, Document, AgentRun)
    ]


async def test_another_rms_account_cannot_be_written_or_handed_to_an_agent(
    client: AsyncClient, session: AsyncSession
) -> None:
    await login(client, OTHER_RM)
    accounts = [FALCON, OASIS, GULF_SPICE]
    before = await _rows_on(session, accounts)
    theirs = _writes(FALCON, sid("deal", "oasis-clinics"), sid("doc", "gulf-spice", "ubo"))
    missing = _writes(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    for (url, kw), (other_url, other_kw) in zip(theirs, missing, strict=True):
        r, other = await client.post(url, **kw), await client.post(other_url, **other_kw)
        assert r.status_code == 404, (url, r.status_code, r.text)
        assert (r.status_code, r.text) == (other.status_code, other.text), url
    # A write followed by a 404 would pass the checks above, so check nothing was written.
    assert await _rows_on(session, accounts) == before


async def test_deals_and_tasks_stay_with_their_rm(
    client: AsyncClient, session: AsyncSession
) -> None:
    await login(client, OTHER_RM)
    mine = {str(TIDE)} | {r["id"] for r in (await client.get("/api/accounts")).json()}
    deals = (await client.get("/api/deals")).json()
    assert deals and {d["company_id"] for d in deals} <= mine
    assert (await client.get(f"/api/deals/{LULU_DEAL}")).status_code == 200
    await _looks_missing(client, "GET", "/api/deals/{}", FALCON_DEAL)
    await _looks_missing(client, "PATCH", "/api/deals/{}", FALCON_DEAL, json={"probability_pct": 1})
    tasks = (await client.get("/api/tasks", params={"mine": False})).json()
    assert tasks and {t["company_id"] for t in tasks} <= mine
    theirs = await session.scalar(select(Task.id).where(Task.company_id == FALCON))
    assert theirs is not None
    await _looks_missing(client, "PATCH", "/api/tasks/{}", theirs, json={"status": "DONE"})
    # Nor can a task on my account be given to an RM who can't open the account.
    body = {"company_id": str(TIDE), "title": "For Layla", "assignee_id": str(LAYLA)}
    assert (await client.post("/api/tasks", json=body)).status_code == 422


async def test_runs_and_approvals_stay_with_their_rm(
    client: AsyncClient, session: AsyncSession
) -> None:
    await login(client, "rm@demo.local")
    run_id = (await client.post(f"/api/dev/agents/demo-followup/{FALCON}")).json()["id"]
    item = await session.scalar(
        select(ApprovalItem).where(ApprovalItem.agent_run_id == uuid.UUID(run_id))
    )
    assert item is not None
    # A reviewer can't give the task to someone who can't open the account, or who has left,
    # and nothing is recorded.
    gone = _former(Role.CREDIT_OFFICER)
    session.add(gone)
    await session.commit()
    url = f"/api/approvals/{item.id}"
    try:
        for assignee in (YUSUF, gone.id):
            moved = {**item.proposed_payload, "assignee_id": str(assignee)}
            r = await client.post(f"{url}/resolve", json={"decision": "APPROVE", "payload": moved})
            assert (r.status_code, r.json()["detail"]) == (422, "No such assignee"), assignee
    finally:
        await session.execute(delete(Task).where(Task.assignee_id == gone.id))
        await session.execute(delete(User).where(User.id == gone.id))
        await session.commit()
    await session.refresh(item)
    assert (item.status, item.edited_payload) == (ApprovalStatus.PENDING, None)
    resolved = select(func.count()).where(
        AuditEvent.action == "approval.resolved", AuditEvent.entity_id == str(item.id)
    )
    assert await session.scalar(resolved) == 0

    await login(client, OTHER_RM)
    await _looks_missing(client, "GET", "/api/approvals/{}", item.id)
    approve = {"json": {"decision": "APPROVE"}}
    await _looks_missing(client, "POST", "/api/approvals/{}/resolve", item.id, **approve)
    await _looks_missing(client, "GET", "/api/agent-runs/{}", run_id)
    await _looks_missing(client, "GET", "/api/agent-runs/{}/stream", run_id)
    mine = {r["id"] for r in (await client.get("/api/accounts")).json()}
    approvals = (await client.get("/api/approvals", params={"state": "all"})).json()
    assert {a["company_id"] for a in approvals} <= mine
    assert (await client.get("/api/approvals/count")).json()["pending_total"] == 0
    # A scan run has no account: he sees only the ones he started.
    runs = (await client.get("/api/agent-runs")).json()
    assert all(
        r["company_id"] in mine if r["company_id"] else r["triggered_by_name"] == "Yusuf Darwish"
        for r in runs
    )

    await login(client, "rm@demo.local")
    r = await client.post(f"{url}/resolve", json={"decision": "REJECT", "note": "test clean-up"})
    assert r.status_code == 200


async def test_scans_and_alerts_cover_only_what_the_rm_sees(
    client: AsyncClient, session: AsyncSession
) -> None:
    sig = EarlyWarningSignal(
        id=uuid.uuid4(),
        company_id=FALCON,
        trigger=EwsTrigger.BOUNCED_CHEQUES,
        severity=Severity.LOW,
        metrics={"count": 1, "period": "2026-10-31"},
        detected_at=utcnow(),
    )
    session.add(sig)
    await session.commit()
    try:
        await login(client, OTHER_RM)
        assert (await client.get("/api/ews")).json() == []
        # Refused without waiting for, or taking, the lock on Layla's signal.
        update_it = {"json": {"status": "INVESTIGATING"}}
        async with get_sessionmaker()() as holder:
            locking = select(EarlyWarningSignal.id).where(EarlyWarningSignal.id == sig.id)
            await holder.execute(locking.with_for_update())
            refused = asyncio.create_task(client.patch(f"/api/ews/{sig.id}", **update_it))
            done, _ = await asyncio.wait({refused}, timeout=5)
            await holder.rollback()
        assert (await refused).status_code == 404 and refused in done
        await _looks_missing(client, "PATCH", "/api/ews/{}", sig.id, **update_it)
        # Every planted anomaly is on Layla's accounts, so Yusuf's scan finds nothing.
        scan = (await client.post("/api/agents/ews-scan")).json()
        run = (await client.get(f"/api/agent-runs/{scan['id']}")).json()
        tool = next(e for e in run["trace"] if e.get("name") == "scan_portfolio")
        assert run["status"] == "COMPLETED" and tool["input"]["companies"] == 7
        assert run["result"]["signals_found"] == 0
        # A scan has no account: it belongs to the RM who ran it.
        await login(client, "rm@demo.local")
        assert (await client.get(f"/api/agent-runs/{scan['id']}")).status_code == 404
        await login(client, "credit@demo.local")
        assert (await client.get(f"/api/agent-runs/{scan['id']}")).status_code == 200
    finally:
        await session.delete(sig)
        await session.commit()


async def _waiting_follow_up(client: AsyncClient, session: AsyncSession) -> ApprovalItem:
    """Layla runs the demo agent on Sadaf; its proposed task waits for approval."""
    await login(client, "rm@demo.local")
    run_id = (await client.post(f"/api/dev/agents/demo-followup/{SADAF}")).json()["id"]
    item = await session.scalar(
        select(ApprovalItem).where(ApprovalItem.agent_run_id == uuid.UUID(run_id))
    )
    assert item is not None
    return item


async def test_access_and_open_work_follow_the_account_when_it_changes_hands(
    client: AsyncClient, session: AsyncSession
) -> None:
    # Layla's work on Sadaf: a task for her and one for Omar, an agent task for her, two
    # follow-ups still waiting, and a portfolio scan she ran.
    made = []
    await login(client, "rm@demo.local")
    for title, assignee in [("Collect the signed offer", LAYLA), ("Value the collateral", OMAR)]:
        body = {"company_id": str(SADAF), "title": title, "assignee_id": str(assignee)}
        r = await client.post("/api/tasks", json=body)
        assert r.status_code == 201, r.text
        made.append(uuid.UUID(r.json()["id"]))
    hers, omars = made
    items = [await _waiting_follow_up(client, session) for _ in range(3)]
    r = await client.post(f"/api/approvals/{items[0].id}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 200, r.text
    agent_task = derived_id(items[0], "task")
    made += [derived_id(i, "task") for i in items]
    scan = AgentRun(
        id=uuid.uuid4(),
        thread_id=f"ews_scan:{uuid.uuid4()}",
        agent_name="ews_scan",
        triggered_by_id=LAYLA,
        status=AgentRunStatus.COMPLETED,
        trace=[{"type": "tool", "name": "scan_portfolio", "output": {str(SADAF): ["DOC_EXPIRY"]}}],
    )
    session.add(scan)
    probability = await session.scalar(select(Deal.probability_pct).where(Deal.id == SADAF_DEAL))
    await session.execute(update(Company).where(Company.id == SADAF).values(rm_id=YUSUF))
    await session.commit()
    try:
        await login(client, "rm@demo.local")
        done = {"json": {"status": "DONE"}}
        for method, url, record, kw in [
            ("GET", "/api/accounts/{}", SADAF, {}),
            ("GET", "/api/deals/{}", SADAF_DEAL, {}),
            ("PATCH", "/api/deals/{}", SADAF_DEAL, {"json": {"probability_pct": 1}}),
            ("PATCH", "/api/tasks/{}", hers, done),
            ("PATCH", "/api/tasks/{}", agent_task, done),
            ("GET", "/api/agent-runs/{}", items[0].agent_run_id, {}),
            ("GET", "/api/agent-runs/{}/stream", items[1].agent_run_id, {}),
            ("GET", "/api/approvals/{}", items[1].id, {}),
            ("POST", "/api/approvals/{}/resolve", items[1].id, {"json": {"decision": "APPROVE"}}),
        ]:
            await _looks_missing(client, method, url, record, **kw)
        # A scan run has no account, so it stays with whoever started it, as a record of what
        # they could see then.
        assert (await client.get(f"/api/agent-runs/{scan.id}")).status_code == 200
        # Her task lists no longer show the account's tasks.
        for params in ({}, {"mine": False}):
            listed = {t["id"] for t in (await client.get("/api/tasks", params=params)).json()}
            assert not {str(hers), str(agent_task), str(omars)} & listed, params

        # Yusuf inherits the open deal, and Layla's tasks: she is an RM who no longer has it.
        await login(client, OTHER_RM)
        assert (await client.get(f"/api/accounts/{SADAF}")).status_code == 200
        r = await client.patch(f"/api/deals/{SADAF_DEAL}", json={"probability_pct": 85})
        assert r.status_code == 200, r.text
        mine = {t["id"] for t in (await client.get("/api/tasks")).json()}
        assert {str(hers), str(agent_task)} <= mine and str(omars) not in mine
        for task in (hers, agent_task):
            assert (await client.patch(f"/api/tasks/{task}", **done)).status_code == 200
        # Omar's stays his: only an RM's tasks pass to the account's RM.
        assert (await client.patch(f"/api/tasks/{omars}", **done)).status_code == 403

        # The waiting follow-ups: a task for someone who can't open the account is refused
        # before anything is recorded; given to Yusuf, or approved as proposed, it is his.
        url = f"/api/approvals/{items[1].id}/resolve"
        for_layla = {**items[1].proposed_payload, "assignee_id": str(LAYLA)}
        r = await client.post(url, json={"decision": "APPROVE", "payload": for_layla})
        assert (r.status_code, r.json()["detail"]) == (422, "No such assignee")
        await session.refresh(items[1])
        assert (items[1].status, items[1].edited_payload) == (ApprovalStatus.PENDING, None)
        resolved = select(func.count()).where(
            AuditEvent.action == "approval.resolved", AuditEvent.entity_id == str(items[1].id)
        )
        assert await session.scalar(resolved) == 0
        for_yusuf = {**items[1].proposed_payload, "assignee_id": str(YUSUF)}
        r = await client.post(url, json={"decision": "APPROVE", "payload": for_yusuf})
        assert r.json()["status"] == "EDITED_AND_APPROVED"
        r = await client.post(f"/api/approvals/{items[2].id}/resolve", json={"decision": "APPROVE"})
        assert r.json()["status"] == "APPROVED"
        new = [derived_id(i, "task") for i in items[1:]]
        holders = await session.execute(select(Task.id, Task.assignee_id).where(Task.id.in_(new)))
        assert dict(holders.all()) == dict.fromkeys(new, YUSUF)
    finally:
        await session.execute(update(Company).where(Company.id == SADAF).values(rm_id=LAYLA))
        await session.execute(
            update(Deal).where(Deal.id == SADAF_DEAL).values(probability_pct=probability)
        )
        await session.execute(delete(Task).where(Task.id.in_(made)))
        await session.execute(delete(AgentRun).where(AgentRun.id == scan.id))
        await session.commit()


async def test_the_accounts_rm_inherits_tasks_with_no_assignee_or_a_former_rm(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A task passes to the account's RM when it has no assignee, or its assignee was an RM who
    no longer has the account. A credit officer's, compliance officer's or admin's stays theirs
    even after they leave: only they or an admin may update it."""
    former = {role: _former(role) for role in Role}
    session.add_all(former.values())
    await session.flush()
    passing = [
        Task(id=uuid.uuid4(), company_id=TIDE, assignee_id=assignee, title=title)
        for assignee, title in [
            (None, "Call Tide Print"),
            (former[Role.RM].id, "Collect the signed offer"),  # Tide is no longer theirs
        ]
    ]
    staying = [
        Task(id=uuid.uuid4(), company_id=TIDE, assignee_id=former[role].id, title=title)
        for role, title in [
            (Role.CREDIT_OFFICER, "Check the guarantee"),
            (Role.COMPLIANCE, "Recheck the licence"),
            (Role.ADMIN, "Fix the contact record"),
        ]
    ]
    tasks = passing + staying
    session.add_all(tasks)
    await session.commit()
    done = {"json": {"status": "DONE"}}
    try:
        await login(client, OTHER_RM)
        mine = {t["id"] for t in (await client.get("/api/tasks")).json()}
        assert _ids(passing) <= mine and not _ids(staying) & mine
        for group, code in [(passing, 200), (staying, 403)]:
            for t in group:
                r = await client.patch(f"/api/tasks/{t.id}", **done)
                assert r.status_code == code, (t.title, r.text)
        # Nor can a new task go to someone who has left.
        officer = str(former[Role.CREDIT_OFFICER].id)
        body = {"company_id": str(TIDE), "title": "Recheck", "assignee_id": officer}
        assert (await client.post("/api/tasks", json=body)).status_code == 422

        # Anyone else needs to be the assignee, and inherits nothing.
        await login(client, "credit@demo.local")
        for t in (passing[0], staying[0]):
            r = await client.patch(f"/api/tasks/{t.id}", json={"status": "OPEN"})
            assert r.status_code == 403, t.title
        theirs = {t["id"] for t in (await client.get("/api/tasks")).json()}
        everything = (await client.get("/api/tasks", params={"mine": False})).json()
        assert _ids(tasks) <= {t["id"] for t in everything} - theirs

        # An admin may update any task.
        await login(client, "admin@demo.local")
        for t in tasks:
            r = await client.patch(f"/api/tasks/{t.id}", json={"status": "OPEN"})
            assert r.status_code == 200, (t.title, r.text)
    finally:
        gone = [u.id for u in former.values()]
        made = Task.id.in_([t.id for t in tasks])
        await session.execute(delete(Task).where(or_(made, Task.assignee_id.in_(gone))))
        await session.execute(delete(User).where(User.id.in_(gone)))
        await session.commit()


async def test_the_task_check_refuses_an_assignee_who_lost_the_account(
    session: AsyncSession,
) -> None:
    """`may_update` checks visibility itself, not only through the route's 404 before it."""
    layla = User(id=LAYLA, role=Role.RM, is_active=True)
    task = Task(id=uuid.uuid4(), company_id=SADAF, assignee_id=LAYLA, title="Collect the offer")
    for rm, allowed in [(LAYLA, True), (YUSUF, False)]:
        account = Company(id=SADAF, rm_id=rm)  # never added to the session
        assert await may_update(session, task, account, layla) is allowed, rm


@pytest.mark.parametrize("lost", ["the account moves", "the user is deactivated"])
async def test_an_open_stream_ends_when_access_is_lost(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lost: str
) -> None:
    run = AgentRun(
        id=uuid.uuid4(),
        thread_id=f"briefing:{uuid.uuid4()}",
        agent_name="briefing",
        triggered_by_id=YUSUF,
        company_id=TIDE,
        status=AgentRunStatus.RUNNING,
        trace=[{"type": "node", "node": "before"}],
    )
    session.add(run)
    await session.commit()
    held: list[int] = []

    async def between_polls(_: float) -> None:
        # The stream holds no database connection while it waits.
        held.append(get_engine().pool.checkedout())
        # Meanwhile Yusuf loses access, and the run writes more and ends.
        async with get_sessionmaker()() as s:
            if lost == "the account moves":
                await s.execute(update(Company).where(Company.id == TIDE).values(rm_id=LAYLA))
            else:
                await s.execute(update(User).where(User.id == YUSUF).values(is_active=False))
            after = [*run.trace, {"type": "node", "node": "after"}]
            await s.execute(
                update(AgentRun)
                .where(AgentRun.id == run.id)
                .values(trace=after, status=AgentRunStatus.COMPLETED)
            )
            await s.commit()

    await login(client, OTHER_RM)
    monkeypatch.setattr(agent_routes, "asyncio", SimpleNamespace(sleep=between_polls))
    try:
        r = await client.get(f"/api/agent-runs/{run.id}/stream")
        assert r.status_code == 200
        assert '"before"' in r.text and '"after"' not in r.text and "COMPLETED" not in r.text
        # One error event, then the stream stops.
        assert r.text.count("event: error") == 1 and "No such agent run" in r.text
        assert held == [0]
    finally:
        await session.execute(update(Company).where(Company.id == TIDE).values(rm_id=YUSUF))
        await session.execute(update(User).where(User.id == YUSUF).values(is_active=True))
        await session.execute(delete(AgentRun).where(AgentRun.id == run.id))
        await session.commit()


async def test_a_decision_is_answered_even_if_the_account_moves_meanwhile(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = await _waiting_follow_up(client, session)
    resume = runtime.resume

    async def hand_over_then_resume(run_id: uuid.UUID, **kw: Any) -> AgentRunStatus:
        async with get_sessionmaker()() as s:
            await s.execute(update(Company).where(Company.id == SADAF).values(rm_id=YUSUF))
            await s.commit()
        return await resume(run_id, **kw)

    monkeypatch.setattr(runtime, "resume", hand_over_then_resume)
    try:
        reject = {"decision": "REJECT", "note": "Already arranged"}
        r = await client.post(f"/api/approvals/{item.id}/resolve", json=reject)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "REJECTED"
    finally:
        await session.execute(update(Company).where(Company.id == SADAF).values(rm_id=LAYLA))
        await session.commit()


async def test_a_run_lists_only_the_citations_its_check_accepted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def also_cites_falcon(facts: dict[str, Any]) -> demo_followup.FollowUpDraft:
        draft = demo_followup._mock_draft(facts)
        return draft.model_copy(update={"source_record_ids": [*draft.source_record_ids, FALCON]})

    monkeypatch.setitem(llm._MOCK_HANDLERS, demo_followup.TASK, also_cites_falcon)
    await login(client, OTHER_RM)
    started = (await client.post(f"/api/dev/agents/demo-followup/{TIDE}")).json()
    run = (await client.get(f"/api/agent-runs/{started['id']}")).json()
    llm_event = next(e for e in run["trace"] if e["type"] == "llm")
    assert run["status"] == "FAILED" and llm_event["rejected_citations"] == [str(FALCON)]
    # Layla's account is not named: only the records the check accepted are described.
    assert str(FALCON) not in {c["id"] for c in run["cited_records"]}
    assert {c["kind"] for c in run["cited_records"]} == {"Account", "Facility"}


@pytest.mark.parametrize(
    ("named", "initiator", "rm", "expected"),
    [
        (None, None, "active", YUSUF),
        (LAYLA, None, "active", YUSUF),
        (OMAR, None, "active", OMAR),
        (None, OMAR, "active", YUSUF),
        (None, OMAR, "inactive", OMAR),
        (LAYLA, OMAR, "missing", OMAR),
        (None, None, "inactive", None),
    ],
    ids=[
        "cron scan, nobody named: the account's RM",
        "named RM can't see it: the account's RM",
        "named credit officer can: them",
        "the account's RM comes before the starter",
        "RM inactive: the starter",
        "no RM: the starter",
        "nobody can: no assignee",
    ],
)
async def test_an_agent_task_goes_to_the_first_who_can_hold_the_account(
    session: AsyncSession,
    named: uuid.UUID | None,
    initiator: uuid.UUID | None,
    rm: str,
    expected: uuid.UUID | None,
) -> None:
    """The first who can hold the account: the named assignee, the account's RM, whoever started
    the run. If none can, nobody."""
    tide, yusuf = await session.get(Company, TIDE), await session.get(User, YUSUF)
    assert tide is not None and yusuf is not None
    yusuf.is_active = rm != "inactive"
    if rm == "missing":
        tide.rm_id = None
    schema, apply = ACTIONS[ActionType.CREATE_TASK]
    approval = ApprovalItem(
        id=uuid.uuid4(), action_type=ActionType.CREATE_TASK, initiator_id=initiator
    )
    payload = {"company_id": str(TIDE), "title": "Call Tide Print", "assignee_id": named}
    try:
        result = await apply(session, approval, schema.model_validate(payload))
        task = await session.get(Task, derived_id(approval, "task"))
        assert task is not None and task.assignee_id == expected
        assert result["assignee_id"] == (str(expected) if expected else None)
    finally:
        await session.rollback()  # nothing was committed: Yusuf, Tide and the task are as before


async def test_every_account_route_is_reviewed_for_access() -> None:
    """Every method on a path with a record id in it is listed here once someone has checked
    that it is scoped, so a new one fails until reviewed. It reads the OpenAPI schema, so ids in
    a query or body, and routes hidden from the schema, aren't seen."""
    reviewed = {
        "GET /api/accounts/{company_id}",
        "GET /api/accounts/{company_id}/documents",
        "GET /api/accounts/{company_id}/ews",
        "GET /api/accounts/{company_id}/facilities",
        "GET /api/accounts/{company_id}/financials",
        "GET /api/accounts/{company_id}/interactions",
        "POST /api/accounts/{company_id}/interactions",
        "GET /api/accounts/{company_id}/tasks",
        "GET /api/agent-runs/{run_id}",
        "GET /api/agent-runs/{run_id}/stream",
        "POST /api/agents/briefing/{company_id}",
        "POST /api/agents/cam/{deal_id}",
        "GET /api/approvals/{approval_id}",
        "POST /api/approvals/{approval_id}/resolve",
        "GET /api/deals/{deal_id}",
        "PATCH /api/deals/{deal_id}",
        "POST /api/dev/agents/demo-followup/{company_id}",
        "POST /api/documents/{document_id}/check",
        "PATCH /api/ews/{signal_id}",
        "PATCH /api/tasks/{task_id}",
    }
    paths = create_app().openapi()["paths"]
    operations = {f"{m.upper()} {p}" for p, item in paths.items() if "{" in p for m in item}
    assert operations == reviewed
