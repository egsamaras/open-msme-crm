import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, or_, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import get_settings
from app.models import (
    AgentRun,
    BeneficialOwner,
    Company,
    Contact,
    Document,
    EarlyWarningSignal,
    Facility,
    FacilityUtilization,
    FinancialSnapshot,
    Interaction,
    User,
)
from app.models.enums import (
    EwsStatus,
    KybStatus,
    PeriodType,
    Role,
    TaskStatus,
    VerificationStatus,
)
from app.schemas.common import AccountListItem
from app.schemas.crm import (
    AccountDetail,
    ContactOut,
    CovenantResult,
    DocumentOut,
    EwsOut,
    FacilityOut,
    InteractionIn,
    InteractionOut,
    OwnerOut,
    SnapshotOut,
    TaskOut,
    UtilizationPoint,
)
from app.services import audit
from app.services import financial_math as fm
from app.services.access import account_or_404, visible_accounts
from app.services.ews_rules import EXPIRING_DOCS
from app.services.tasks import query_tasks

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountListItem])
async def list_accounts(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=100),
) -> list[AccountListItem]:
    """Accounts the user may see, in the order most useful to their role."""
    limits = (
        select(
            Facility.company_id,
            func.coalesce(func.sum(Facility.sanctioned_limit), 0).label("total_limit"),
            func.coalesce(func.sum(Facility.utilized_amount), 0).label("total_utilized"),
        )
        .group_by(Facility.company_id)
        .subquery()
    )
    ews = (
        select(EarlyWarningSignal.company_id, func.count().label("open_ews"))
        .where(EarlyWarningSignal.status != EwsStatus.RESOLVED)
        .group_by(EarlyWarningSignal.company_id)
        .subquery()
    )
    # Next expiry: for each type (trade licence, CR certificate), the latest expiry on a verified
    # document, then the sooner of the two. Pending and rejected uploads and other types don't
    # count.
    in_force = (
        select(Document.company_id, func.max(Document.expiry_date).label("expiry_date"))
        .where(
            Document.doc_type.in_(EXPIRING_DOCS),
            Document.verification_status == VerificationStatus.VERIFIED,
        )
        .group_by(Document.company_id, Document.doc_type)
        .subquery()
    )
    expiry = (
        select(in_force.c.company_id, func.min(in_force.c.expiry_date).label("next_expiry"))
        .group_by(in_force.c.company_id)
        .subquery()
    )
    order: list[Any] = [Company.legal_name]
    if user.role == Role.CREDIT_OFFICER:
        alerts = func.coalesce(ews.c.open_ews, 0)
        order = [alerts.desc(), Company.risk_rating.desc(), *order]
    elif user.role == Role.COMPLIANCE:
        kyb = case(
            {KybStatus.FLAGGED: 0, KybStatus.PENDING_RENEWAL: 1}, value=Company.kyb_status, else_=2
        )
        order = [kyb, expiry.c.next_expiry.asc().nulls_last(), *order]
    stmt = (
        select(
            Company,
            User.full_name,
            limits.c.total_limit,
            limits.c.total_utilized,
            ews.c.open_ews,
            expiry.c.next_expiry,
        )
        .outerjoin(User, User.id == Company.rm_id)
        .outerjoin(limits, limits.c.company_id == Company.id)
        .outerjoin(ews, ews.c.company_id == Company.id)
        .outerjoin(expiry, expiry.c.company_id == Company.id)
        .where(visible_accounts(user))
        .order_by(*order)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Company.legal_name.ilike(like),
                Company.trading_name.ilike(like),
                Company.cr_number.ilike(like),
            )
        )
    rows = await session.execute(stmt)
    return [
        AccountListItem.model_validate(
            {
                **{
                    c: getattr(company, c)
                    for c in AccountListItem.model_fields
                    if hasattr(company, c)
                },
                "rm_name": rm_name,
                "total_limit": total_limit or Decimal(0),
                "total_utilized": total_utilized or Decimal(0),
                "open_ews": open_ews or 0,
                "next_doc_expiry": next_expiry,
            }
        )
        for company, rm_name, total_limit, total_utilized, open_ews, next_expiry in rows.all()
    ]


@router.get("/{company_id}", response_model=AccountDetail)
async def get_account(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> AccountDetail:
    company = await account_or_404(session, company_id, user)
    threshold = get_settings().ubo_threshold_pct
    rm = await session.get(User, company.rm_id) if company.rm_id else None
    owners = await session.scalars(
        select(BeneficialOwner)
        .where(BeneficialOwner.company_id == company_id)
        .order_by(BeneficialOwner.ownership_pct.desc())
    )
    contacts = await session.scalars(
        select(Contact)
        .where(Contact.company_id == company_id)
        .order_by(Contact.is_primary.desc(), Contact.full_name)
    )
    return AccountDetail.model_validate(
        {
            **{c: getattr(company, c) for c in AccountDetail.model_fields if hasattr(company, c)},
            "rm_name": rm.full_name if rm else None,
            "ubo_threshold_pct": threshold,
            "owners": [
                OwnerOut.model_validate(
                    {
                        **{c: getattr(o, c) for c in OwnerOut.model_fields if hasattr(o, c)},
                        "is_ubo": o.ownership_pct >= threshold,
                    }
                )
                for o in owners
            ],
            "contacts": [ContactOut.model_validate(c) for c in contacts],
        }
    )


async def _monthly_snapshots(session: SessionDep, company_id: uuid.UUID) -> list[FinancialSnapshot]:
    rows = await session.scalars(
        select(FinancialSnapshot)
        .where(
            FinancialSnapshot.company_id == company_id,
            FinancialSnapshot.period_type == PeriodType.MONTHLY,
        )
        .order_by(FinancialSnapshot.period_end)
    )
    return list(rows)


@router.get("/{company_id}/financials", response_model=list[SnapshotOut])
async def get_financials(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[SnapshotOut]:
    await account_or_404(session, company_id, user)
    snapshots = await _monthly_snapshots(session, company_id)
    out: list[SnapshotOut] = []
    prev: FinancialSnapshot | None = None
    for s in snapshots:
        r = fm.snapshot_ratios(s)
        out.append(
            SnapshotOut.model_validate(
                {
                    **{c: getattr(s, c) for c in SnapshotOut.model_fields if hasattr(s, c)},
                    "dscr": r.dscr,
                    "debt_to_equity": r.debt_to_equity,
                    "debt_to_ebitda": r.debt_to_ebitda,
                    "current_ratio": r.current_ratio,
                    "balance_change_pct": (
                        fm.pct_change(prev.avg_bank_balance, s.avg_bank_balance) if prev else None
                    ),
                }
            )
        )
        prev = s
    return out


@router.get("/{company_id}/facilities", response_model=list[FacilityOut])
async def get_facilities(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[FacilityOut]:
    await account_or_404(session, company_id, user)
    threshold = get_settings().ews_utilization_pct
    facilities = list(
        await session.scalars(
            select(Facility).where(Facility.company_id == company_id).order_by(Facility.product)
        )
    )
    history: dict[uuid.UUID, list[FacilityUtilization]] = defaultdict(list)
    for point in await session.scalars(
        select(FacilityUtilization)
        .where(FacilityUtilization.facility_id.in_([f.id for f in facilities]))
        .order_by(FacilityUtilization.as_of)
    ):
        history[point.facility_id].append(point)

    snapshots = await _monthly_snapshots(session, company_id)
    latest = snapshots[-1] if snapshots else None
    ratios = fm.snapshot_ratios(latest) if latest else None

    out = []
    for f in facilities:
        points = [
            UtilizationPoint(
                as_of=p.as_of,
                utilized_amount=p.utilized_amount,
                utilization_pct=fm.utilization_pct(p.utilized_amount, f.sanctioned_limit),
            )
            for p in history[f.id]
        ]
        covenants = []
        for c in f.covenants:
            actual = ratios.metric(c["metric"]) if ratios else None
            covenants.append(
                CovenantResult(
                    metric=c["metric"],
                    operator=c["operator"],
                    threshold=Decimal(c["threshold"]),
                    actual=actual,
                    passes=fm.covenant_passes(actual, c["operator"], Decimal(c["threshold"])),
                    tested_on=latest.period_end if latest else None,
                )
            )
        out.append(
            FacilityOut(
                id=f.id,
                product=f.product,
                is_islamic=f.is_islamic,
                sanctioned_limit=f.sanctioned_limit,
                utilized_amount=f.utilized_amount,
                utilization_pct=fm.utilization_pct(f.utilized_amount, f.sanctioned_limit),
                days_above_alert_threshold=fm.days_continuously_above(
                    [(p.as_of, p.utilization_pct) for p in points if p.utilization_pct is not None],
                    threshold,
                ),
                alert_threshold_pct=threshold,
                rate_pct=f.rate_pct,
                start_date=f.start_date,
                maturity_date=f.maturity_date,
                covenants=covenants,
                history=points,
            )
        )
    return out


@router.get("/{company_id}/documents", response_model=list[DocumentOut])
async def get_documents(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[DocumentOut]:
    await account_or_404(session, company_id, user)
    rows = list(
        await session.scalars(
            select(Document)
            .where(Document.company_id == company_id)
            .order_by(Document.doc_type, Document.created_at.desc())
        )
    )
    # Latest KYB check per document (runs carry the document id in their graph input).
    checks: dict[str, AgentRun] = {}
    for run in await session.scalars(
        select(AgentRun)
        .where(AgentRun.company_id == company_id, AgentRun.agent_name == "kyb_intake")
        .order_by(AgentRun.created_at)
    ):
        doc_id = (run.result or {}).get("document_id") or _started_doc(run)
        if doc_id:
            checks[doc_id] = run
    out = []
    for d in rows:
        check = checks.get(str(d.id))
        out.append(
            DocumentOut.model_validate(d).model_copy(
                update={
                    "has_text": bool(d.content_text),
                    "check_run_id": check.id if check else None,
                    "check_run_status": check.status if check else None,
                }
            )
        )
    return out


def _started_doc(run: AgentRun) -> str | None:
    """A paused run has no result yet; its document id is in the first trace event."""
    for e in run.trace:
        if e.get("type") == "tool" and e.get("name") == "parse_document":
            return str(e["input"]["document_id"])
    return None


@router.get("/{company_id}/interactions", response_model=list[InteractionOut])
async def get_interactions(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[InteractionOut]:
    await account_or_404(session, company_id, user)
    rows = await session.execute(
        select(Interaction, User.full_name)
        .outerjoin(User, User.id == Interaction.user_id)
        .where(Interaction.company_id == company_id)
        .order_by(Interaction.occurred_at.desc())
    )
    return [_interaction_out(i, name) for i, name in rows.all()]


def _interaction_out(i: Interaction, user_name: str | None) -> InteractionOut:
    return InteractionOut.model_validate(
        {
            **{c: getattr(i, c) for c in InteractionOut.model_fields if hasattr(i, c)},
            "user_name": user_name,
        }
    )


@router.post(
    "/{company_id}/interactions",
    response_model=InteractionOut,
    status_code=status.HTTP_201_CREATED,
)
async def log_interaction(
    company_id: uuid.UUID, body: InteractionIn, session: SessionDep, user: CurrentUser
) -> InteractionOut:
    await account_or_404(session, company_id, user)
    if body.occurred_at.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "occurred_at needs a timezone")
    if body.occurred_at > datetime.now(UTC):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "occurred_at is in the future")
    interaction = Interaction(company_id=company_id, user_id=user.id, **body.model_dump())
    session.add(interaction)
    await session.flush()
    await audit.record(
        session,
        action="interaction.create",
        entity_type="interaction",
        entity_id=interaction.id,
        payload={"company_id": str(company_id), "type": body.interaction_type.value},
        actor_user_id=user.id,
    )
    await session.commit()
    return _interaction_out(interaction, user.full_name)


@router.get("/{company_id}/ews", response_model=list[EwsOut])
async def get_ews(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[EarlyWarningSignal]:
    await account_or_404(session, company_id, user)
    rows = await session.scalars(
        select(EarlyWarningSignal)
        .where(EarlyWarningSignal.company_id == company_id)
        .order_by(EarlyWarningSignal.detected_at.desc())
    )
    return list(rows)


@router.get("/{company_id}/tasks", response_model=list[TaskOut])
async def get_account_tasks(
    company_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
) -> list[TaskOut]:
    company = await account_or_404(session, company_id, user)
    return await query_tasks(session, user, company_id=company.id, status=status_filter)
