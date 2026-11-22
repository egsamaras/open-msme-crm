from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Company, EarlyWarningSignal, Facility, User
from app.models.enums import EwsStatus, Role
from app.schemas.common import AccountListItem

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountListItem])
async def list_accounts(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=100),
    mine: bool = False,
) -> list[AccountListItem]:
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
    stmt = (
        select(
            Company, User.full_name, limits.c.total_limit, limits.c.total_utilized, ews.c.open_ews
        )
        .outerjoin(User, User.id == Company.rm_id)
        .outerjoin(limits, limits.c.company_id == Company.id)
        .outerjoin(ews, ews.c.company_id == Company.id)
        .order_by(Company.legal_name)
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
    if mine and user.role == Role.RM:
        stmt = stmt.where(Company.rm_id == user.id)

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
            }
        )
        for company, rm_name, total_limit, total_utilized, open_ews in rows.all()
    ]
