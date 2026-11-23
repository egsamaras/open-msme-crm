"""Runs agent graphs: creates the AgentRun, streams node updates into its trace, records
interrupts, and resumes threads after a reviewer's decision (SPEC 4.1, rules 1 and 7)."""

import time
import uuid
from collections.abc import Callable
from typing import Any

from langgraph.graph import StateGraph
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.checkpointer import get_checkpointer
from app.agents.context import AgentContext, Tracer, reset_context, set_context
from app.agents.hitl import APPROVED
from app.agents.llm import get_llm
from app.db.session import get_sessionmaker
from app.models import AgentRun
from app.models.base import utcnow
from app.models.enums import AgentRunStatus

GraphFactory = Callable[[], StateGraph[Any]]
_REGISTRY: dict[str, GraphFactory] = {}
_COMPILED: dict[tuple[str, int], Any] = {}

TERMINAL = {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.REJECTED}


def register_graph(name: str) -> Callable[[GraphFactory], GraphFactory]:
    def register(factory: GraphFactory) -> GraphFactory:
        _REGISTRY[name] = factory
        return factory

    return register


def compiled_graph(name: str) -> Any:
    saver = get_checkpointer()
    key = (name, id(saver))
    if key not in _COMPILED:
        _COMPILED[key] = _REGISTRY[name]().compile(checkpointer=saver)
    return _COMPILED[key]


async def create_run(
    session: AsyncSession,
    *,
    agent_name: str,
    user_id: uuid.UUID | None,
    company_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
    parent_run_id: uuid.UUID | None = None,
) -> AgentRun:
    if agent_name not in _REGISTRY:
        raise LookupError(f"Unknown agent {agent_name!r}")
    run = AgentRun(
        id=uuid.uuid4(),
        thread_id=f"{agent_name}:{uuid.uuid4()}",
        agent_name=agent_name,
        triggered_by_id=user_id,
        company_id=company_id,
        deal_id=deal_id,
        parent_run_id=parent_run_id,
        status=AgentRunStatus.RUNNING,
        trace=[],
    )
    session.add(run)
    await session.flush()
    return run


async def _flush(
    run_id: uuid.UUID,
    tracer: Tracer,
    status: AgentRunStatus | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    events = tracer.drain()
    async with get_sessionmaker()() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if events:
            run.trace = [*run.trace, *events]  # reassign so SQLAlchemy sees the change
        if result is not None:
            run.result = result
        if status is not None:
            run.status = status
            if status in TERMINAL:
                run.finished_at = utcnow()
        await session.commit()


async def execute(run_id: uuid.UUID, graph_input: dict[str, Any] | Command[Any]) -> AgentRunStatus:
    """Run (or resume) a graph until it finishes or pauses at an interrupt."""
    async with get_sessionmaker()() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        ctx = AgentContext(
            run_id=run.id,
            thread_id=run.thread_id,
            agent_name=run.agent_name,
            user_id=run.triggered_by_id,
            llm=get_llm(),
            tracer=Tracer(),
        )
    graph = compiled_graph(ctx.agent_name)
    config = {"configurable": {"thread_id": ctx.thread_id}}
    token = set_context(ctx)
    status = AgentRunStatus.RUNNING
    result: dict[str, Any] | None = None
    try:
        last = time.perf_counter()
        async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
            for node, update in chunk.items():
                now = time.perf_counter()
                if node == "__interrupt__":
                    for intr in update:
                        ctx.tracer.add("interrupt", **dict(intr.value))
                else:
                    ctx.tracer.add("node", node=node, ms=int((now - last) * 1000))
                last = now
            await _flush(run_id, ctx.tracer)
        snapshot = await graph.aget_state(config)
        # A graph may publish what it produced (a briefing, a draft memo) under `result`.
        result = snapshot.values.get("result")
        if snapshot.next:
            status = AgentRunStatus.AWAITING_APPROVAL
        else:
            decisions = [
                a.get("decision") for a in (snapshot.values.get("approvals") or {}).values()
            ]
            rejected = bool(decisions) and not any(d in APPROVED for d in decisions)
            status = AgentRunStatus.REJECTED if rejected else AgentRunStatus.COMPLETED
    except Exception as e:
        ctx.tracer.add("error", error=type(e).__name__, message=str(e)[:500])
        status = AgentRunStatus.FAILED
    finally:
        reset_context(token)
    await _flush(run_id, ctx.tracer, status, result)
    return status


async def resume(
    run_id: uuid.UUID, *, decision: str, payload: dict[str, Any], reviewer_id: uuid.UUID
) -> AgentRunStatus:
    """Resume a paused run with a reviewer's decision. Only the approvals API calls this."""
    tracer = Tracer()
    tracer.add("resume", decision=decision, reviewer_id=str(reviewer_id))
    await _flush(run_id, tracer, AgentRunStatus.RUNNING)
    return await execute(run_id, Command(resume={"decision": decision, "payload": payload}))
