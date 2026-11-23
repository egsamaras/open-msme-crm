import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sse_starlette.sse import EventSourceResponse

from app.agents import runtime
from app.agents.actions import payload_schema
from app.api.deps import CurrentUser, SessionDep, require_roles
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models import AgentRun, ApprovalItem, AuditEvent, Company, User
from app.models.base import utcnow
from app.models.enums import AgentRunStatus, ApprovalStatus, Role
from app.schemas.agents import (
    AgentRunDetail,
    AgentRunSummary,
    ApprovalCount,
    ApprovalOut,
    AuditEventOut,
    ResolveIn,
)
from app.services import audit
from app.services.approvals import is_four_eyes, required_roles, review_blocker
from app.services.records import describe_records

router = APIRouter(tags=["agents"])

Initiator = aliased(User)
Reviewer = aliased(User)
Trigger = aliased(User)


# ---------- helpers ----------


def _run_summary(
    run: AgentRun, company_name: str | None, trigger_name: str | None
) -> AgentRunSummary:
    return AgentRunSummary(
        id=run.id,
        thread_id=run.thread_id,
        agent_name=run.agent_name,
        status=run.status,
        company_id=run.company_id,
        company_name=company_name,
        deal_id=run.deal_id,
        triggered_by_name=trigger_name,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


def _approvals_query() -> Any:
    return (
        select(
            ApprovalItem,
            AgentRun,
            Company.trading_name,
            Initiator.full_name,
            Reviewer.full_name,
            Trigger.full_name,
        )
        .join(AgentRun, AgentRun.id == ApprovalItem.agent_run_id)
        .outerjoin(Company, Company.id == AgentRun.company_id)
        .outerjoin(Initiator, Initiator.id == ApprovalItem.initiator_id)
        .outerjoin(Reviewer, Reviewer.id == ApprovalItem.reviewer_id)
        .outerjoin(Trigger, Trigger.id == AgentRun.triggered_by_id)
    )


def _approval_out(row: Any, user: User) -> ApprovalOut:
    item, run, company_name, initiator, reviewer, trigger = row
    blocker = review_blocker(item, user)
    return ApprovalOut(
        id=item.id,
        action_type=item.action_type,
        status=item.status,
        proposed_payload=item.proposed_payload,
        edited_payload=item.edited_payload,
        company_id=run.company_id,
        company_name=company_name,
        initiator_id=item.initiator_id,
        initiator_name=initiator,
        reviewer_name=reviewer,
        review_note=item.review_note,
        created_at=item.created_at,
        resolved_at=item.resolved_at,
        required_roles=sorted(required_roles(item)),
        four_eyes=is_four_eyes(item),
        can_review=blocker is None,
        review_blocker=blocker,
        run=_run_summary(run, company_name, trigger),
    )


async def _load_approval(session: SessionDep, approval_id: uuid.UUID, user: User) -> ApprovalOut:
    row = (await session.execute(_approvals_query().where(ApprovalItem.id == approval_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such approval item")
    return _approval_out(row, user)


# ---------- approvals ----------


@router.get("/api/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    session: SessionDep,
    user: CurrentUser,
    state: str = Query(default="pending", pattern="^(pending|resolved|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ApprovalOut]:
    stmt = _approvals_query().order_by(ApprovalItem.created_at.desc()).limit(limit)
    if state == "pending":
        stmt = stmt.where(ApprovalItem.status == ApprovalStatus.PENDING)
    elif state == "resolved":
        stmt = stmt.where(ApprovalItem.status != ApprovalStatus.PENDING)
    rows = (await session.execute(stmt)).all()
    return [_approval_out(r, user) for r in rows]


@router.get("/api/approvals/count", response_model=ApprovalCount)
async def count_approvals(session: SessionDep, user: CurrentUser) -> ApprovalCount:
    pending = list(
        await session.scalars(
            select(ApprovalItem).where(ApprovalItem.status == ApprovalStatus.PENDING)
        )
    )
    return ApprovalCount(
        pending_for_me=sum(1 for i in pending if review_blocker(i, user) is None),
        pending_total=len(pending),
    )


@router.get("/api/approvals/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> ApprovalOut:
    return await _load_approval(session, approval_id, user)


@router.post("/api/approvals/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: uuid.UUID, body: ResolveIn, session: SessionDep, user: CurrentUser
) -> ApprovalOut:
    # Lock the row so two reviewers can't both resolve it.
    item = await session.scalar(
        select(ApprovalItem).where(ApprovalItem.id == approval_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such approval item")
    if item.status != ApprovalStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has already been resolved")
    blocker = review_blocker(item, user)
    if blocker:
        raise HTTPException(status.HTTP_403_FORBIDDEN, blocker)

    final = item.proposed_payload
    if body.decision == "REJECT":
        if not (body.note and body.note.strip()):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say why you're rejecting")
        new_status = ApprovalStatus.REJECTED
    else:
        new_status = ApprovalStatus.APPROVED
        if body.payload is not None:
            try:
                edited = payload_schema(item.action_type).model_validate(body.payload)
            except ValidationError as e:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Edited payload is not valid: {e.errors()[0]['msg']}",
                ) from e
            edited_json = edited.model_dump(mode="json")
            # Fields the reviewer can't change stay as proposed.
            if edited_json.get("company_id") != item.proposed_payload.get("company_id"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "You can't change the account"
                )
            if edited_json != item.proposed_payload:
                item.edited_payload = edited_json
                final = edited_json
                new_status = ApprovalStatus.EDITED_AND_APPROVED

    item.status = new_status
    item.reviewer_id = user.id
    item.review_note = body.note
    item.resolved_at = utcnow()
    await audit.record(
        session,
        action="approval.resolved",
        entity_type="approval_item",
        entity_id=item.id,
        payload={
            "decision": new_status.value,
            "action_type": item.action_type.value,
            "edited": item.edited_payload is not None,
            "note": body.note,
        },
        actor_user_id=user.id,
    )
    run_id = item.agent_run_id
    await session.commit()

    await runtime.resume(run_id, decision=new_status.value, payload=final, reviewer_id=user.id)
    session.expire_all()
    return await _load_approval(session, approval_id, user)


# ---------- agent runs ----------


@router.get("/api/agent-runs", response_model=list[AgentRunSummary])
async def list_runs(
    session: SessionDep,
    _: CurrentUser,
    company_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AgentRunSummary]:
    stmt = (
        select(AgentRun, Company.trading_name, Trigger.full_name)
        .outerjoin(Company, Company.id == AgentRun.company_id)
        .outerjoin(Trigger, Trigger.id == AgentRun.triggered_by_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    if company_id:
        stmt = stmt.where(AgentRun.company_id == company_id)
    return [_run_summary(r, c, t) for r, c, t in (await session.execute(stmt)).all()]


@router.get("/api/agent-runs/{run_id}", response_model=AgentRunDetail)
async def get_run(run_id: uuid.UUID, session: SessionDep, _: CurrentUser) -> AgentRunDetail:
    row = (
        await session.execute(
            select(AgentRun, Company.trading_name, Trigger.full_name)
            .outerjoin(Company, Company.id == AgentRun.company_id)
            .outerjoin(Trigger, Trigger.id == AgentRun.triggered_by_id)
            .where(AgentRun.id == run_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such agent run")
    run, company_name, trigger = row
    cited = {uuid.UUID(c) for e in run.trace if e.get("type") == "llm" for c in e.get("cited", [])}
    approval_ids = list(
        await session.scalars(select(ApprovalItem.id).where(ApprovalItem.agent_run_id == run.id))
    )
    return AgentRunDetail(
        **_run_summary(run, company_name, trigger).model_dump(),
        trace=run.trace,
        cited_records=await describe_records(session, cited),
        approval_ids=approval_ids,
    )


@router.get("/api/agent-runs/{run_id}/stream")
async def stream_run(run_id: uuid.UUID, request: Request, _: CurrentUser) -> EventSourceResponse:
    """Server-Sent Events: trace events as they're written, then the final status."""
    pause = {AgentRunStatus.AWAITING_APPROVAL, *runtime.TERMINAL}

    async def events() -> AsyncIterator[dict[str, str]]:
        sent = 0
        for _ in range(600):  # stop after ~5 minutes regardless
            async with get_sessionmaker()() as s:
                run = await s.get(AgentRun, run_id)
            if run is None:
                yield {"event": "error", "data": json.dumps({"detail": "No such agent run"})}
                return
            for event in run.trace[sent:]:
                yield {"event": "trace", "data": json.dumps(event)}
            sent = len(run.trace)
            if run.status in pause:
                yield {"event": "status", "data": json.dumps({"status": run.status.value})}
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    return EventSourceResponse(events())


# ---------- development: demo agent ----------


@router.post(
    "/api/dev/agents/demo-followup/{company_id}",
    response_model=AgentRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_demo_followup(
    company_id: uuid.UUID,
    background: BackgroundTasks,
    session: SessionDep,
    user: Annotated[User, Depends(require_roles(Role.RM))],
) -> AgentRunSummary:
    """Development only: run the demo agent, which proposes one follow-up task for approval."""
    if not get_settings().is_dev:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")
    run = await runtime.create_run(
        session, agent_name="demo_followup", user_id=user.id, company_id=company_id
    )
    await audit.record(
        session,
        action="agent.started",
        entity_type="agent_run",
        entity_id=run.id,
        payload={"agent": run.agent_name, "company_id": str(company_id)},
        actor_user_id=user.id,
    )
    await session.commit()
    background.add_task(runtime.execute, run.id, {"company_id": str(company_id)})
    return _run_summary(run, company.trading_name, user.full_name)


# ---------- audit trail ----------


@router.get("/api/audit/events", response_model=list[AuditEventOut])
async def list_audit_events(
    session: SessionDep,
    _: Annotated[User, Depends(require_roles(Role.COMPLIANCE))],
    before_seq: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditEventOut]:
    stmt = (
        select(AuditEvent, User.full_name)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .order_by(AuditEvent.seq.desc())
        .limit(limit)
    )
    if before_seq is not None:
        stmt = stmt.where(AuditEvent.seq < before_seq)
    return [
        AuditEventOut(
            seq=e.seq,
            occurred_at=e.occurred_at,
            actor_name=name,
            actor_agent=e.actor_agent,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            payload=e.payload,
            hash=e.hash,
        )
        for e, name in (await session.execute(stmt)).all()
    ]


@router.get("/api/audit/count")
async def count_audit_events(
    session: SessionDep, _: Annotated[User, Depends(require_roles(Role.COMPLIANCE))]
) -> dict[str, int]:
    return {"total": int(await session.scalar(select(func.count()).select_from(AuditEvent)) or 0)}
