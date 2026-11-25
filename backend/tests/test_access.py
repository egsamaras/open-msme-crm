"""Relationship managers see only their own accounts, on every route that exposes account data."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import sid
from app.main import create_app
from app.models import ApprovalItem, Company, EarlyWarningSignal, Task
from app.models.base import utcnow
from app.models.enums import EwsTrigger, Severity
from tests.conftest import login

FALCON = sid("company", "falcon-steel")  # Layla's
TIDE = sid("company", "tide-print")  # Yusuf's
LULU_DEAL = sid("deal", "lulu-bakers")  # Yusuf's
FALCON_DEAL = sid("deal", "falcon-steel")  # Layla's
OTHER_RM = "rm2@demo.local"


async def _names(client: AsyncClient, email: str) -> list[str]:
    await login(client, email)
    return [r["trading_name"] for r in (await client.get("/api/accounts")).json()]


async def test_each_rm_gets_their_own_accounts_and_others_get_all(client: AsyncClient) -> None:
    layla, yusuf = await _names(client, "rm@demo.local"), await _names(client, OTHER_RM)
    assert (len(layla), len(yusuf)) == (8, 7) and not set(layla) & set(yusuf)
    for email in ("credit@demo.local", "compliance@demo.local", "admin@demo.local"):
        assert set(await _names(client, email)) == set(layla) | set(yusuf)


async def test_lists_open_in_the_order_each_role_needs(client: AsyncClient) -> None:
    await login(client, "credit@demo.local")
    rows = (await client.get("/api/accounts")).json()
    keys = [(-r["open_ews"], -r["risk_rating"], r["legal_name"]) for r in rows]
    assert keys == sorted(keys)
    await login(client, "compliance@demo.local")
    rows = (await client.get("/api/accounts")).json()
    rank = {"FLAGGED": 0, "PENDING_RENEWAL": 1, "VERIFIED": 2}
    order = [(rank[r["kyb_status"]], r["next_doc_expiry"]) for r in rows]
    assert order == sorted(order)


@pytest.mark.parametrize(
    "part",
    ["", "/documents", "/ews", "/facilities", "/financials", "/interactions", "/tasks"],
)
async def test_account_pages_of_another_rm_look_missing(client: AsyncClient, part: str) -> None:
    await login(client, OTHER_RM)
    assert (await client.get(f"/api/accounts/{FALCON}{part}")).status_code == 404
    assert (await client.get(f"/api/accounts/{TIDE}{part}")).status_code == 200


async def test_another_rms_account_cannot_be_written_or_handed_to_an_agent(
    client: AsyncClient,
) -> None:
    await login(client, OTHER_RM)
    ubo = sid("doc", "gulf-spice", "ubo")
    deal = {"company_id": str(FALCON), "title": "Sneaky", "product": "TERM_LOAN"}
    note = {"interaction_type": "CALL", "occurred_at": utcnow().isoformat(), "summary": "Hi there"}
    calls: list[tuple[str, dict[str, Any]]] = [
        (f"/api/accounts/{FALCON}/interactions", {"json": note}),
        ("/api/deals", {"json": {**deal, "requested_amount": "1000"}}),
        ("/api/tasks", {"json": {"company_id": str(FALCON), "title": "Sneaky task"}}),
        (f"/api/agents/briefing/{FALCON}", {}),
        (f"/api/agents/cam/{sid('deal', 'oasis-clinics')}", {}),
        (f"/api/dev/agents/demo-followup/{FALCON}", {}),
        (f"/api/documents/{ubo}/check", {}),
        (
            "/api/documents/upload",
            {
                "data": {"company_id": str(FALCON), "doc_type": "TRADE_LICENSE"},
                "files": {"file": ("a.txt", b"Expiry: 2030-01-01", "text/plain")},
            },
        ),
    ]
    for url, kw in calls:
        r = await client.post(url, **kw)
        assert r.status_code == 404, (url, r.status_code, r.text)


async def test_deals_and_tasks_stay_with_their_rm(
    client: AsyncClient, session: AsyncSession
) -> None:
    await login(client, OTHER_RM)
    mine = {str(TIDE)} | {r["id"] for r in (await client.get("/api/accounts")).json()}
    deals = (await client.get("/api/deals")).json()
    assert deals and {d["company_id"] for d in deals} <= mine
    assert (await client.get(f"/api/deals/{LULU_DEAL}")).status_code == 200
    assert (await client.get(f"/api/deals/{FALCON_DEAL}")).status_code == 404
    r = await client.patch(f"/api/deals/{FALCON_DEAL}", json={"probability_pct": 1})
    assert r.status_code == 404
    tasks = (await client.get("/api/tasks", params={"mine": False})).json()
    assert tasks and {t["company_id"] for t in tasks} <= mine
    theirs = await session.scalar(select(Task.id).where(Task.company_id == FALCON))
    r = await client.patch(f"/api/tasks/{theirs}", json={"status": "DONE"})
    assert r.status_code == 404
    # Nor can a task on my account be given to an RM who can't open the account.
    body = {"company_id": str(TIDE), "title": "For Layla", "assignee_id": str(sid("user", "rm"))}
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
    # The assignee is part of the target: a reviewer can't redirect the task.
    moved = {**item.proposed_payload, "assignee_id": str(sid("user", "rm2"))}
    url = f"/api/approvals/{item.id}"
    r = await client.post(f"{url}/resolve", json={"decision": "APPROVE", "payload": moved})
    assert r.status_code == 422

    await login(client, OTHER_RM)
    assert (await client.get(url)).status_code == 404
    r = await client.post(f"{url}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 404
    assert (await client.get(f"/api/agent-runs/{run_id}")).status_code == 404
    assert (await client.get(f"/api/agent-runs/{run_id}/stream")).status_code == 404
    mine = {r["id"] for r in (await client.get("/api/accounts")).json()}
    approvals = (await client.get("/api/approvals", params={"state": "all"})).json()
    assert {a["company_id"] for a in approvals} <= mine
    assert (await client.get("/api/approvals/count")).json()["pending_total"] == 0
    assert {r["company_id"] for r in (await client.get("/api/agent-runs")).json()} <= mine

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
        r = await client.patch(f"/api/ews/{sig.id}", json={"status": "INVESTIGATING"})
        assert r.status_code == 404
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


async def test_access_follows_the_account_when_it_changes_hands(
    client: AsyncClient, session: AsyncSession
) -> None:
    company = await session.get(Company, TIDE)
    assert company is not None
    company.rm_id = sid("user", "rm")
    await session.commit()
    try:
        await login(client, OTHER_RM)
        assert (await client.get(f"/api/accounts/{TIDE}")).status_code == 404
        await login(client, "rm@demo.local")
        assert (await client.get(f"/api/accounts/{TIDE}")).status_code == 200
    finally:
        company.rm_id = sid("user", "rm2")
        await session.commit()


async def test_every_account_route_is_reviewed_for_access() -> None:
    """Adding a route with a record id fails here until someone checks it is scoped."""
    reviewed = {
        "/api/accounts/{company_id}",
        "/api/accounts/{company_id}/documents",
        "/api/accounts/{company_id}/ews",
        "/api/accounts/{company_id}/facilities",
        "/api/accounts/{company_id}/financials",
        "/api/accounts/{company_id}/interactions",
        "/api/accounts/{company_id}/tasks",
        "/api/agent-runs/{run_id}",
        "/api/agent-runs/{run_id}/stream",
        "/api/agents/briefing/{company_id}",
        "/api/agents/cam/{deal_id}",
        "/api/approvals/{approval_id}",
        "/api/approvals/{approval_id}/resolve",
        "/api/deals/{deal_id}",
        "/api/dev/agents/demo-followup/{company_id}",
        "/api/documents/{document_id}/check",
        "/api/ews/{signal_id}",
        "/api/tasks/{task_id}",
    }
    paths = {p for p in create_app().openapi()["paths"] if "{" in p}
    assert paths == reviewed
