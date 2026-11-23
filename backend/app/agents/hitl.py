"""Human-in-the-loop approval steps (SPEC 4.1, rule 1).

`add_approval_step` wires three nodes into a graph:

    propose_<name>  upsert the ApprovalItem on its idempotency key; no other side effects
    await_<name>    ONLY interrupt(). LangGraph re-runs an interrupted node from the top when it
                    resumes, so nothing with side effects may live here
    apply_<name>    runs the action's applier, only if the reviewer approved

Resuming happens only through POST /api/approvals/{id}/resolve, which validates the reviewer and
calls the graph with Command(resume={"decision": ..., "payload": ...}).
"""

import uuid
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.actions import ACTIONS
from app.agents.context import current
from app.db.session import get_sessionmaker
from app.models import ApprovalItem
from app.models.enums import ActionType, ApprovalStatus
from app.services import audit

APPROVED = (ApprovalStatus.APPROVED.value, ApprovalStatus.EDITED_AND_APPROVED.value)


class Proposal(TypedDict):
    target_id: str
    payload: dict[str, Any]


class ApprovalState(TypedDict, total=False):
    approvals: dict[str, dict[str, Any]]


def idempotency_key(thread_id: str, action: ActionType, target_id: str) -> str:
    return f"{thread_id}:{action.value}:{target_id}"


async def upsert_approval(
    *,
    run_id: uuid.UUID,
    thread_id: str,
    key: str,
    action: ActionType,
    payload: dict[str, Any],
    initiator_id: uuid.UUID | None,
    agent_name: str,
) -> uuid.UUID:
    """Insert the ApprovalItem once per idempotency key; return its id either way."""
    async with get_sessionmaker()() as session:
        inserted = await session.scalar(
            insert(ApprovalItem)
            .values(
                id=uuid.uuid4(),
                agent_run_id=run_id,
                thread_id=thread_id,
                idempotency_key=key,
                action_type=action,
                proposed_payload=payload,
                status=ApprovalStatus.PENDING,
                initiator_id=initiator_id,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(ApprovalItem.id)
        )
        item_id = inserted or await session.scalar(
            select(ApprovalItem.id).where(ApprovalItem.idempotency_key == key)
        )
        assert isinstance(item_id, uuid.UUID)
        if inserted:
            await audit.record(
                session,
                action="approval.proposed",
                entity_type="approval_item",
                entity_id=item_id,
                payload={"action_type": action.value, "thread_id": thread_id},
                actor_agent=agent_name,
                actor_user_id=initiator_id,
            )
        await session.commit()
    return item_id


def add_approval_step(
    builder: Any,  # a StateGraph whose state has an `approvals` key
    *,
    name: str,
    action: ActionType,
    propose: Callable[[dict[str, Any]], Proposal],
    then: str = END,
    on_reject: str = END,
) -> str:
    """Add the three nodes. Returns the name of the first node, to wire an edge into."""
    schema, applier = ACTIONS[action]

    async def propose_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = current()
        proposal = propose(state)
        payload = schema.model_validate(proposal["payload"]).model_dump(mode="json")
        key = idempotency_key(ctx.thread_id, action, proposal["target_id"])
        item_id = await upsert_approval(
            run_id=ctx.run_id,
            thread_id=ctx.thread_id,
            key=key,
            action=action,
            payload=payload,
            initiator_id=ctx.user_id,
            agent_name=ctx.agent_name,
        )
        approvals = dict(state.get("approvals") or {})
        approvals[name] = {"approval_id": str(item_id), "action": action.value}
        return {"approvals": approvals}

    def await_node(state: dict[str, Any]) -> dict[str, Any]:
        entry = state["approvals"][name]
        decision = interrupt({"approval_id": entry["approval_id"], "action": action.value})
        approvals = dict(state["approvals"])
        approvals[name] = {
            **entry,
            "decision": decision["decision"],
            "payload": decision["payload"],
        }
        return {"approvals": approvals}

    async def apply_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = current()
        entry = state["approvals"][name]
        async with get_sessionmaker()() as session:
            item = await session.get(ApprovalItem, uuid.UUID(entry["approval_id"]))
            assert item is not None
            result = await applier(session, item, schema.model_validate(entry["payload"]))
            await audit.record(
                session,
                action="approval.applied",
                entity_type="approval_item",
                entity_id=item.id,
                payload={"action_type": action.value, "result": result},
                actor_agent=ctx.agent_name,
            )
            await session.commit()
        ctx.tool(f"apply.{action.value.lower()}", {"approval_id": entry["approval_id"]}, result)
        approvals = dict(state["approvals"])
        approvals[name] = {**entry, "result": result}
        return {"approvals": approvals}

    def route(state: dict[str, Any]) -> str:
        return f"apply_{name}" if state["approvals"][name]["decision"] in APPROVED else on_reject

    builder.add_node(f"propose_{name}", propose_node)
    builder.add_node(f"await_{name}", await_node)
    builder.add_node(f"apply_{name}", apply_node)
    builder.add_edge(f"propose_{name}", f"await_{name}")
    builder.add_conditional_edges(f"await_{name}", route, [f"apply_{name}", on_reject])
    builder.add_edge(f"apply_{name}", then)
    return f"propose_{name}"
