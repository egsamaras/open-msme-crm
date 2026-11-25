"""Start the account co-pilot agents: pre-meeting briefings and credit memo drafting."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from app.agents import runtime
from app.api.deps import CurrentUser, SessionDep, require_roles
from app.models import AgentRun, ApprovalItem, Company, Deal, User
from app.models.enums import ActionType, AgentRunStatus, ApprovalStatus, DealStage, Role
from app.schemas.agents import AgentRunSummary
from app.services import audit
from app.services.access import account_or_404

router = APIRouter(tags=["agents"])


async def _start(
    session: SessionDep,
    background: BackgroundTasks,
    user: User,
    *,
    agent: str,
    graph_input: dict[str, str],
    company: Company,
    deal_id: uuid.UUID | None = None,
) -> AgentRunSummary:
    run = await runtime.create_run(
        session, agent_name=agent, user_id=user.id, company_id=company.id, deal_id=deal_id
    )
    await audit.record(
        session,
        action="agent.started",
        entity_type="agent_run",
        entity_id=run.id,
        payload={"agent": agent, **graph_input},
        actor_user_id=user.id,
    )
    await session.commit()
    background.add_task(runtime.execute, run.id, graph_input)
    return AgentRunSummary(
        id=run.id,
        thread_id=run.thread_id,
        agent_name=run.agent_name,
        status=run.status,
        company_id=company.id,
        company_name=company.trading_name,
        deal_id=deal_id,
        triggered_by_name=user.full_name,
        created_at=run.created_at,
        finished_at=None,
    )


@router.post(
    "/api/agents/cam/{deal_id}",
    response_model=AgentRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_cam(
    deal_id: uuid.UUID,
    background: BackgroundTasks,
    session: SessionDep,
    user: Annotated[User, Depends(require_roles(Role.RM))],
) -> AgentRunSummary:
    """Draft a credit memo for a deal in underwriting. A credit officer reviews it (four-eyes)."""
    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deal")
    company = await account_or_404(session, deal.company_id, user, "No such deal")
    if deal.stage != DealStage.CREDIT_UNDERWRITING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Credit memos are drafted for deals in credit underwriting"
        )
    busy = await session.scalar(
        select(AgentRun.id).where(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == "cam_draft",
            AgentRun.status.in_([AgentRunStatus.RUNNING, AgentRunStatus.AWAITING_APPROVAL]),
        )
    )
    pending = await session.scalar(
        select(ApprovalItem.id).where(
            ApprovalItem.action_type == ActionType.SUBMIT_CAM,
            ApprovalItem.status == ApprovalStatus.PENDING,
            ApprovalItem.proposed_payload["deal_id"].astext == str(deal_id),
        )
    )
    if busy or pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A credit memo for this deal is already in progress"
        )
    return await _start(
        session,
        background,
        user,
        agent="cam_draft",
        graph_input={"deal_id": str(deal_id)},
        company=company,
        deal_id=deal_id,
    )


@router.post(
    "/api/agents/briefing/{company_id}",
    response_model=AgentRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_briefing(
    company_id: uuid.UUID, background: BackgroundTasks, session: SessionDep, user: CurrentUser
) -> AgentRunSummary:
    """Read-only briefing for a client meeting. Follow its progress on the run's /stream."""
    company = await account_or_404(session, company_id, user)
    return await _start(
        session,
        background,
        user,
        agent="briefing",
        graph_input={"company_id": str(company_id)},
        company=company,
    )
