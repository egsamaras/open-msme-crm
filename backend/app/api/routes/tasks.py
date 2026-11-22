import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.models import Company, Deal, Task, User
from app.models.enums import Role, TaskSource, TaskStatus
from app.schemas.crm import TaskIn, TaskOut, TaskPatch
from app.services import audit
from app.services.tasks import query_tasks

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    session: SessionDep,
    user: CurrentUser,
    mine: bool = True,
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
) -> list[TaskOut]:
    return await query_tasks(session, assignee_id=user.id if mine else None, status=status_filter)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskIn, session: SessionDep, user: CurrentUser) -> TaskOut:
    if await session.get(Company, body.company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")
    if body.deal_id:
        deal = await session.get(Deal, body.deal_id)
        if deal is None or deal.company_id != body.company_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Deal is not on this account"
            )
    assignee_id = body.assignee_id or user.id
    assignee = await session.get(User, assignee_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No such assignee")
    task = Task(
        company_id=body.company_id,
        deal_id=body.deal_id,
        assignee_id=assignee_id,
        title=body.title,
        due_date=body.due_date,
        status=TaskStatus.OPEN,
        source=TaskSource.MANUAL,
    )
    session.add(task)
    await session.flush()
    await audit.record(
        session,
        action="task.create",
        entity_type="task",
        entity_id=task.id,
        payload={"company_id": str(body.company_id), "assignee_id": str(assignee_id)},
        actor_user_id=user.id,
    )
    await session.commit()
    return (await query_tasks(session, task_id=task.id))[0]


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID, body: TaskPatch, session: SessionDep, user: CurrentUser
) -> TaskOut:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such task")
    if task.assignee_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assignee can update this task")
    if task.status != body.status:
        old = task.status
        task.status = body.status
        await audit.record(
            session,
            action="task.status",
            entity_type="task",
            entity_id=task.id,
            payload={"from": old.value, "to": body.status.value},
            actor_user_id=user.id,
        )
        await session.commit()
    return (await query_tasks(session, task_id=task.id))[0]
