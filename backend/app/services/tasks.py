import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Company, Task, User
from app.models.enums import TaskStatus
from app.schemas.crm import TaskOut


async def query_tasks(
    session: AsyncSession,
    *,
    company_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    task_id: uuid.UUID | None = None,
) -> list[TaskOut]:
    assignee = aliased(User)
    stmt = (
        select(Task, Company.trading_name, Company.legal_name, assignee.full_name)
        .join(Company, Company.id == Task.company_id)
        .outerjoin(assignee, assignee.id == Task.assignee_id)
        .order_by(Task.status, Task.due_date.asc().nulls_last(), Task.title)
    )
    if company_id:
        stmt = stmt.where(Task.company_id == company_id)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
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
