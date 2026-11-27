import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, require_roles
from app.models import AgentRun, Company, Deal, Document, User
from app.models.enums import DealStage, Role
from app.schemas.crm import DealDetail, DealIn, DealOut, DealPatch, DraftCamOut
from app.services import audit
from app.services.access import account_or_404, visible_accounts
from app.services.pipeline import allowed_stages, build_checklist, checklist_complete

router = APIRouter(prefix="/api/deals", tags=["deals"])

STAGE_PROBABILITY = {
    DealStage.LEAD: 10,
    DealStage.QUALIFICATION: 25,
    DealStage.DOC_COLLECTION: 40,
    DealStage.CREDIT_UNDERWRITING: 60,
    DealStage.APPROVAL: 80,
    DealStage.DISBURSED: 100,
    DealStage.LOST: 0,
}


def _deal_out(deal: Deal, company: Company, owner_name: str | None) -> DealOut:
    return DealOut(
        id=deal.id,
        company_id=company.id,
        company_name=company.trading_name or company.legal_name,
        currency=company.currency,
        title=deal.title,
        product=deal.product,
        stage=deal.stage,
        requested_amount=deal.requested_amount,
        probability_pct=deal.probability_pct,
        expected_close=deal.expected_close,
        owner_name=owner_name,
        has_draft_cam=deal.draft_cam is not None,
    )


@router.get("", response_model=list[DealOut])
async def list_deals(
    session: SessionDep,
    user: CurrentUser,
    stage: DealStage | None = None,
    company_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
) -> list[DealOut]:
    stmt = (
        select(Deal, Company, User.full_name)
        .join(Company, Company.id == Deal.company_id)
        .outerjoin(User, User.id == Deal.owner_id)
        .where(visible_accounts(user))
        .order_by(Deal.expected_close.asc().nulls_last(), Deal.title)
    )
    if stage:
        stmt = stmt.where(Deal.stage == stage)
    if company_id:
        stmt = stmt.where(Deal.company_id == company_id)
    if q:
        stmt = stmt.where(Deal.title.ilike(f"%{q}%"))
    rows = await session.execute(stmt)
    return [_deal_out(d, c, n) for d, c, n in rows.all()]


async def _detail(session: SessionDep, deal_id: uuid.UUID, user: User) -> DealDetail:
    row = (
        await session.execute(
            select(Deal, Company, User.full_name)
            .join(Company, Company.id == Deal.company_id)
            .outerjoin(User, User.id == Deal.owner_id)
            .where(Deal.id == deal_id, visible_accounts(user))
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deal")
    deal, company, owner_name = row
    docs = await session.scalars(select(Document).where(Document.company_id == company.id))
    checklist = build_checklist(docs, datetime.now(UTC).date())
    cam_run = await session.scalar(
        select(AgentRun)
        .where(AgentRun.deal_id == deal.id, AgentRun.agent_name == "cam_draft")
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    officer = await session.get(User, deal.credit_officer_id) if deal.credit_officer_id else None
    return DealDetail(
        **_deal_out(deal, company, owner_name).model_dump(),
        checklist=checklist,
        checklist_complete=checklist_complete(checklist),
        allowed_stages=allowed_stages(deal.stage, user.role),
        draft_cam=DraftCamOut.model_validate(deal.draft_cam) if deal.draft_cam else None,
        credit_officer_name=officer.full_name if officer else None,
        cam_run_id=cam_run.id if cam_run else None,
        cam_run_status=cam_run.status if cam_run else None,
    )


@router.get("/{deal_id}", response_model=DealDetail)
async def get_deal(deal_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> DealDetail:
    return await _detail(session, deal_id, user)


@router.post("", response_model=DealDetail, status_code=status.HTTP_201_CREATED)
async def create_deal(
    body: DealIn,
    session: SessionDep,
    user: Annotated[User, Depends(require_roles(Role.RM))],
) -> DealDetail:
    await account_or_404(session, body.company_id, user)
    deal = Deal(
        **body.model_dump(),
        stage=DealStage.LEAD,
        probability_pct=STAGE_PROBABILITY[DealStage.LEAD],
        owner_id=user.id,
    )
    session.add(deal)
    await session.flush()
    await audit.record(
        session,
        action="deal.create",
        entity_type="deal",
        entity_id=deal.id,
        payload={"company_id": str(body.company_id), "amount": body.requested_amount},
        actor_user_id=user.id,
    )
    await session.commit()
    return await _detail(session, deal.id, user)


@router.patch("/{deal_id}", response_model=DealDetail)
async def update_deal(
    deal_id: uuid.UUID,
    body: DealPatch,
    session: SessionDep,
    user: Annotated[User, Depends(require_roles(Role.RM, Role.CREDIT_OFFICER))],
) -> DealDetail:
    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deal")
    # An RM may edit every deal on their own accounts, including one a predecessor opened.
    await account_or_404(session, deal.company_id, user, "No such deal")

    changes = body.model_dump(exclude_unset=True)
    if "stage" in changes and changes["stage"] != deal.stage:
        new_stage = changes["stage"]
        if new_stage not in allowed_stages(deal.stage, user.role):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Can't move a deal from {deal.stage.value} to {new_stage.value} by hand"
                + (
                    " — submit a credit memo for approval instead"
                    if new_stage == DealStage.APPROVAL
                    else ""
                ),
            )
        changes.setdefault("probability_pct", STAGE_PROBABILITY[new_stage])
    elif user.role == Role.CREDIT_OFFICER:
        # Credit officers only move approved deals; they don't edit RM pipeline fields.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Credit officers can only change the stage")

    before = {k: getattr(deal, k) for k in changes}
    for key, value in changes.items():
        setattr(deal, key, value)
    if changes:
        await audit.record(
            session,
            action="deal.update",
            entity_type="deal",
            entity_id=deal.id,
            payload={
                "from": {k: (v.value if hasattr(v, "value") else v) for k, v in before.items()},
                "to": {k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()},
            },
            actor_user_id=user.id,
        )
        await session.commit()
    return await _detail(session, deal.id, user)
