"""Phase 3: agent runtime, approvals, four-eyes, citations, idempotency, streaming."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.graphs import demo_followup
from app.agents.hitl import upsert_approval
from app.db.seed import sid
from app.models import AgentRun, ApprovalItem, Task, User
from app.models.enums import ActionType, ApprovalStatus, Role, TaskSource
from app.services import audit
from app.services.approvals import review_blocker
from tests.conftest import login

FALCON = sid("company", "falcon-steel")
OASIS = sid("company", "oasis-clinics")


async def _start_demo(client: AsyncClient, company: uuid.UUID = FALCON) -> dict[str, Any]:
    await login(client, "rm@demo.local")
    r = await client.post(f"/api/dev/agents/demo-followup/{company}")
    assert r.status_code == 202, r.text
    run = (await client.get(f"/api/agent-runs/{r.json()['id']}")).json()
    return dict(run)


async def _pending_for(client: AsyncClient, run_id: str) -> dict[str, Any]:
    items = (await client.get("/api/approvals")).json()
    return next(i for i in items if i["run"]["id"] == run_id)


async def test_demo_run_pauses_for_approval_with_full_trace(client: AsyncClient) -> None:
    run = await _start_demo(client)
    assert run["status"] == "AWAITING_APPROVAL"
    kinds = [e["type"] for e in run["trace"]]
    assert kinds.count("tool") == 1 and kinds.count("llm") == 1
    assert kinds[-1] == "interrupt"
    nodes = [e["node"] for e in run["trace"] if e["type"] == "node"]
    assert nodes == ["fetch_context", "draft_followup", "propose_task"]
    llm_event = next(e for e in run["trace"] if e["type"] == "llm")
    assert llm_event["provider"] == "mock" and llm_event["rejected_citations"] == []
    # Cited records resolve to labelled links for the inspection drawer.
    kinds_cited = {r["kind"] for r in run["cited_records"]}
    assert kinds_cited == {"Account", "Facility"}

    item = await _pending_for(client, run["id"])
    assert item["action_type"] == "CREATE_TASK"
    assert item["initiator_name"] == "Layla Rahman"
    assert item["can_review"] is True  # routine action: the RM who started it may approve
    assert item["four_eyes"] is False
    assert "Falcon Steel" in item["proposed_payload"]["title"]


async def test_approve_creates_agent_task_and_completes_run(
    client: AsyncClient, session: AsyncSession
) -> None:
    run = await _start_demo(client)
    item = await _pending_for(client, run["id"])
    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    assert r.json()["run"]["status"] == "COMPLETED"

    detail = (await client.get(f"/api/agent-runs/{run['id']}")).json()
    tail = detail["trace"][-4:]
    # On resume the paused node re-runs and completes, then the applier runs.
    assert [e["type"] for e in tail] == ["resume", "node", "tool", "node"]
    assert [tail[1]["node"], tail[3]["node"]] == ["await_task", "apply_task"]
    task = await session.scalar(select(Task).where(Task.title == item["proposed_payload"]["title"]))
    assert task is not None and task.source == TaskSource.AGENT
    assert (await audit.verify_chain(session)).ok


async def test_edit_and_approve_uses_the_edited_payload(
    client: AsyncClient, session: AsyncSession
) -> None:
    run = await _start_demo(client, OASIS)
    item = await _pending_for(client, run["id"])
    edited = {**item["proposed_payload"], "title": "Visit Oasis Clinics finance team"}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve",
        json={"decision": "APPROVE", "payload": edited, "note": "Better in person"},
    )
    assert r.json()["status"] == "EDITED_AND_APPROVED"
    assert r.json()["edited_payload"]["title"] == "Visit Oasis Clinics finance team"
    assert await session.scalar(select(Task).where(Task.title == edited["title"])) is not None


async def test_reject_needs_a_reason_and_creates_nothing(
    client: AsyncClient, session: AsyncSession
) -> None:
    run = await _start_demo(client)
    item = await _pending_for(client, run["id"])
    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "REJECT"})
    assert r.status_code == 422
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve",
        json={"decision": "REJECT", "note": "Already spoke to them today"},
    )
    assert r.json()["status"] == "REJECTED"
    assert r.json()["run"]["status"] == "REJECTED"
    count = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.title == item["proposed_payload"]["title"])
    )
    # Earlier tests may have approved an identical title for Falcon; none came from this item.
    run_row = await session.get(AgentRun, uuid.UUID(run["id"]))
    assert run_row is not None
    assert not any(
        e.get("type") == "tool" and e.get("name", "").startswith("apply.") for e in run_row.trace
    )
    assert count is not None


async def test_resolving_twice_is_a_conflict(client: AsyncClient) -> None:
    run = await _start_demo(client)
    item = await _pending_for(client, run["id"])
    body = {"decision": "APPROVE"}
    assert (await client.post(f"/api/approvals/{item['id']}/resolve", json=body)).status_code == 200
    assert (await client.post(f"/api/approvals/{item['id']}/resolve", json=body)).status_code == 409


async def test_wrong_role_and_bad_edits_are_refused(client: AsyncClient) -> None:
    run = await _start_demo(client)
    item = await _pending_for(client, run["id"])

    await login(client, "compliance@demo.local")
    listed = await _pending_for(client, run["id"])
    assert listed["can_review"] is False
    assert "relationship manager" in listed["review_blocker"]
    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 403

    await login(client, "rm@demo.local")
    moved = {**item["proposed_payload"], "company_id": str(OASIS)}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE", "payload": moved}
    )
    assert r.status_code == 422
    blank = {**item["proposed_payload"], "title": ""}
    r = await client.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE", "payload": blank}
    )
    assert r.status_code == 422
    counts = (await client.get("/api/approvals/count")).json()
    assert counts["pending_for_me"] >= 1


def _user(role: Role) -> User:
    return User(id=uuid.uuid4(), role=role, email=f"{role}@x", full_name=role.value)


@pytest.mark.parametrize("action", [ActionType.SUBMIT_CAM, ActionType.FLAG_KYB])
def test_four_eyes_blocks_the_initiator_and_wrong_roles(action: ActionType) -> None:
    reviewer_role = Role.CREDIT_OFFICER if action == ActionType.SUBMIT_CAM else Role.COMPLIANCE
    initiator = _user(reviewer_role)
    item = ApprovalItem(
        action_type=action, status=ApprovalStatus.PENDING, initiator_id=initiator.id
    )

    assert "Four-eyes" in (review_blocker(item, initiator) or "")
    assert review_blocker(item, _user(reviewer_role)) is None  # a different officer
    assert "Needs a" in (review_blocker(item, _user(Role.RM)) or "")
    admin = _user(Role.ADMIN)
    assert review_blocker(item, admin) is None
    item.initiator_id = admin.id
    assert "Four-eyes" in (review_blocker(item, admin) or "")  # admins aren't exempt


async def test_unknown_citation_fails_the_run_before_anything_is_proposed(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cites_a_stranger(facts: dict[str, Any]) -> demo_followup.FollowUpDraft:
        good = demo_followup._mock_draft(facts)
        return good.model_copy(
            update={"source_record_ids": [*good.source_record_ids, uuid.uuid4()]}
        )

    monkeypatch.setitem(llm._MOCK_HANDLERS, demo_followup.TASK, cites_a_stranger)
    run = await _start_demo(client)
    assert run["status"] == "FAILED"
    error = run["trace"][-1]
    assert error["type"] == "error" and error["error"] == "CitationError"
    llm_event = next(e for e in run["trace"] if e["type"] == "llm")
    assert len(llm_event["rejected_citations"]) == 1
    n = await session.scalar(
        select(func.count())
        .select_from(ApprovalItem)
        .where(ApprovalItem.agent_run_id == uuid.UUID(run["id"]))
    )
    assert n == 0


async def test_approval_upsert_is_idempotent(session: AsyncSession) -> None:
    run = await session.scalar(select(AgentRun).limit(1))
    assert run is not None
    kwargs: dict[str, Any] = {
        "run_id": run.id,
        "thread_id": run.thread_id,
        "key": f"{run.thread_id}:CREATE_TASK:retry-test",
        "action": ActionType.CREATE_TASK,
        "payload": {"company_id": str(FALCON), "title": "Retry test"},
        "initiator_id": None,
        "agent_name": "test",
    }
    first = await upsert_approval(**kwargs)
    second = await upsert_approval(**kwargs)
    assert first == second
    n = await session.scalar(
        select(func.count())
        .select_from(ApprovalItem)
        .where(ApprovalItem.idempotency_key == kwargs["key"])
    )
    assert n == 1


async def test_stream_replays_trace_then_status(client: AsyncClient) -> None:
    run = await _start_demo(client)
    r = await client.get(f"/api/agent-runs/{run['id']}/stream")
    assert r.status_code == 200
    assert r.text.count("event: trace") == len(run["trace"])
    assert "AWAITING_APPROVAL" in r.text


async def test_audit_events_are_compliance_only(client: AsyncClient) -> None:
    await _start_demo(client)
    assert (await client.get("/api/audit/events")).status_code == 403
    await login(client, "compliance@demo.local")
    events = (await client.get("/api/audit/events?limit=50")).json()
    assert any(e["action"] == "approval.proposed" for e in events)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs, reverse=True)


async def test_demo_endpoint_is_rm_only(client: AsyncClient) -> None:
    await login(client, "compliance@demo.local")
    assert (await client.post(f"/api/dev/agents/demo-followup/{FALCON}")).status_code == 403


async def test_paused_run_survives_a_restart(client: AsyncClient) -> None:
    """Close and reopen the checkpointer (as a server restart would) between pause and resume."""
    import os

    from app.agents.checkpointer import close_checkpointer, open_checkpointer

    run = await _start_demo(client, OASIS)
    item = await _pending_for(client, run["id"])
    await close_checkpointer()
    await open_checkpointer(os.environ["CHECKPOINT_DATABASE_URL"])
    r = await client.post(f"/api/approvals/{item['id']}/resolve", json={"decision": "APPROVE"})
    assert r.status_code == 200
    assert r.json()["run"]["status"] == "COMPLETED"
