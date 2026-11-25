"""Which accounts a user may see (SPEC 4.1, rule 10). The single source of truth.

Relationship managers see only accounts assigned to them. Credit officers, compliance and admins
see the whole bank, because second-person review has to cover all of it. Out-of-scope records are
reported as missing (404), so their existence doesn't leak.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, Company, User
from app.models.enums import Role


def visible_accounts(user: User, company_id: Any = Company.id) -> ColumnElement[bool]:
    """SQL condition on a company id column: rows of accounts `user` may see."""
    if user.role != Role.RM:
        return true()
    condition: ColumnElement[bool] = company_id.in_(
        select(Company.id).where(Company.rm_id == user.id)
    )
    return condition


def visible_runs(user: User) -> ColumnElement[bool]:
    """Runs on visible accounts. A run with no account (a scan) belongs to whoever started it."""
    if user.role != Role.RM:
        return true()
    return or_(
        visible_accounts(user, AgentRun.company_id),
        and_(AgentRun.company_id.is_(None), AgentRun.triggered_by_id == user.id),
    )


def can_see(user: User, company: Company) -> bool:
    return user.role != Role.RM or company.rm_id == user.id


async def account_or_404(
    session: AsyncSession, company_id: uuid.UUID, user: User, detail: str = "No such account"
) -> Company:
    company = await session.get(Company, company_id)
    if company is None or not can_see(user, company):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
    return company
