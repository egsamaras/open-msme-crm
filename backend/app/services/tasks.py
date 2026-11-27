import uuid

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Company, Task, User
from app.models.enums import Role, TaskStatus
from app.schemas.crm import TaskOut
from app.services.access import can_see, passes_to_rm, passes_to_rm_sql, visible_accounts


async def query_tasks(
    session: AsyncSession,
    user: User,
    *,
    company_id: uuid.UUID | None = None,
    mine: bool = False,
    status: TaskStatus | None = None,
    task_id: uuid.UUID | None = None,
) -> list[TaskOut]:
    assignee = aliased(User)
    stmt = (
        select(Task, Company.trading_name, Company.legal_name, assignee.full_name)
        .join(Company, Company.id == Task.company_id)
        .outerjoin(assignee, assignee.id == Task.assignee_id)
        .where(visible_accounts(user))
        .order_by(Task.status, Task.due_date.asc().nulls_last(), Task.title)
    )
    if company_id:
        stmt = stmt.where(Task.company_id == company_id)
    if mine:
        condition: ColumnElement[bool] = Task.assignee_id == user.id
        if user.role == Role.RM:
            # Also the tasks that pass to the account's RM. Only an RM can be an account's RM
            # (`rm_id`), so other roles keep the plain filter, which the assignee index serves.
            condition = or_(condition, and_(Company.rm_id == user.id, passes_to_rm_sql(assignee)))
        stmt = stmt.where(condition)
    if status:
        stmt = stmt.where(Task.status == status)
    if task_id:
        stmt = stmt.where(Task.id == task_id)
    rows = await session.execute(stmt)
    return [
        TaskOut.model_validate(
            {
                **{c: getattr(t, c) for c in TaskOut.model_fields if hasattr(t, c)},
                "company_name": trading or legal,
                "assignee_name": assignee_name,
            }
        )
        for t, trading, legal, assignee_name in rows.all()
    ]


async def may_update(session: AsyncSession, task: Task, company: Company, user: User) -> bool:
    """The assignee while they may see the account, an admin, or the account's RM when the task
    passes to them (`passes_to_rm`): it has no assignee, or its assignee was an RM who no longer
    has the account. It checks visibility itself, so it holds without the route's 404 first."""
    if user.role == Role.ADMIN:
        return True
    if task.assignee_id == user.id:
        return can_see(user, company)
    if user.role != Role.RM or company.rm_id != user.id:
        return False
    assignee = await session.get(User, task.assignee_id) if task.assignee_id else None
    return passes_to_rm(assignee, company)
