"""Risk radar: early-warning signals across the portfolio, the scan that finds them, resolution."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import case, select

from app.agents.graphs import ews as ews_graph
from app.api.deps import CurrentUser, SessionDep, require_roles
from app.models import Company, EarlyWarningSignal, User
from app.models.base import utcnow
from app.models.enums import EwsStatus, Role, Severity
from app.schemas.agents import AgentRunSummary
from app.schemas.crm import EwsListItem, EwsUpdate
from app.services import audit

router = APIRouter(tags=["risk"])

_SEVERITY_RANK = case(
    {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3},
    value=EarlyWarningSignal.severity,
)


def _item(sig: EarlyWarningSignal, company_name: str, resolver: str | None) -> EwsListItem:
    return EwsListItem.model_validate(
        {
            **{c: getattr(sig, c) for c in EwsListItem.model_fields if hasattr(sig, c)},
            "company_name": company_name,
            "resolved_by_name": resolver,
        }
    )


def _query() -> Any:
    return (
        select(EarlyWarningSignal, Company.trading_name, User.full_name)
        .join(Company, Company.id == EarlyWarningSignal.company_id)
        .outerjoin(User, User.id == EarlyWarningSignal.resolved_by_id)
    )


@router.get("/api/ews", response_model=list[EwsListItem])
async def list_signals(
    session: SessionDep,
    _: CurrentUser,
    state: str = Query(default="open", pattern="^(open|resolved|all)$"),
) -> list[EwsListItem]:
    """Signals ranked by severity, then newest first. `open` includes ones being investigated."""
    stmt = _query().order_by(_SEVERITY_RANK, EarlyWarningSignal.detected_at.desc())
    if state == "open":
        stmt = stmt.where(EarlyWarningSignal.status != EwsStatus.RESOLVED)
    elif state == "resolved":
        stmt = stmt.where(EarlyWarningSignal.status == EwsStatus.RESOLVED)
    return [_item(s, name, r) for s, name, r in (await session.execute(stmt)).all()]


@router.patch("/api/ews/{signal_id}", response_model=EwsListItem)
async def update_signal(
    signal_id: uuid.UUID,
    body: EwsUpdate,
    session: SessionDep,
    user: Annotated[User, Depends(require_roles(Role.RM, Role.CREDIT_OFFICER))],
) -> EwsListItem:
    sig = await session.scalar(
        select(EarlyWarningSignal).where(EarlyWarningSignal.id == signal_id).with_for_update()
    )
    if sig is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such signal")
    if sig.status == EwsStatus.RESOLVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This signal is already resolved")
    new = EwsStatus(body.status)
    if new == EwsStatus.RESOLVED and not (body.note and body.note.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say how it was resolved")
    before = sig.status
    sig.status = new
    if body.note:
        sig.resolution_note = body.note
    if new == EwsStatus.RESOLVED:
        sig.resolved_by_id = user.id
        sig.resolved_at = utcnow()
    await audit.record(
        session,
        action="ews.update",
        entity_type="early_warning_signal",
        entity_id=sig.id,
        payload={"from": before.value, "to": new.value, "note": body.note},
        actor_user_id=user.id,
    )
    await session.commit()
    row = (await session.execute(_query().where(EarlyWarningSignal.id == signal_id))).one()
    return _item(*row)


@router.post(
    "/api/agents/ews-scan", response_model=AgentRunSummary, status_code=status.HTTP_202_ACCEPTED
)
async def start_ews_scan(
    background: BackgroundTasks,
    session: SessionDep,
    user: Annotated[User, Depends(require_roles(Role.RM, Role.CREDIT_OFFICER))],
) -> AgentRunSummary:
    """Scan the whole portfolio. Each company with new signals gets its own review and approval."""
    run = await ews_graph.start_scan(session, user.id)
    await session.commit()
    background.add_task(ews_graph.drive_scan, run.id)
    return AgentRunSummary(
        id=run.id,
        thread_id=run.thread_id,
        agent_name=run.agent_name,
        status=run.status,
        company_id=None,
        company_name=None,
        deal_id=None,
        triggered_by_name=user.full_name,
        created_at=run.created_at,
        finished_at=None,
    )
