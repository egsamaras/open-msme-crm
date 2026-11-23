"""What an approved action does, and the payload shape a reviewer may edit.

Each action type has a Pydantic payload schema (edits are validated against it) and an applier
that runs only after approval. Appliers are idempotent: rows they create get a UUID derived from
the approval item, so a retried apply can't create duplicates. Outbound email is never sent:
it lands in the outbox as SIMULATED (SPEC 4.1, rule 6).
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalItem, OutboxMessage, Task
from app.models.enums import ActionType, OutboxStatus, TaskSource, TaskStatus

_NS = uuid.UUID("0b8f3f0e-6b1c-4d3e-9a7f-2a1d5c9e8b47")


def derived_id(approval: ApprovalItem, kind: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{approval.id}:{kind}")


class CreateTaskPayload(BaseModel):
    company_id: uuid.UUID
    title: str = Field(min_length=3, max_length=255)
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None
    rationale: str | None = Field(default=None, max_length=2000)


class SendEmailPayload(BaseModel):
    company_id: uuid.UUID
    # Plain pattern, not EmailStr: synthetic contacts use reserved demo domains.
    to_address: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    subject: str = Field(min_length=3, max_length=255)
    body: str = Field(min_length=10, max_length=10_000)


async def _apply_create_task(
    session: AsyncSession, approval: ApprovalItem, payload: BaseModel
) -> dict[str, Any]:
    p = CreateTaskPayload.model_validate(payload.model_dump())
    task_id = derived_id(approval, "task")
    await session.merge(
        Task(
            id=task_id,
            company_id=p.company_id,
            assignee_id=p.assignee_id or approval.initiator_id,
            title=p.title,
            due_date=p.due_date,
            status=TaskStatus.OPEN,
            source=TaskSource.AGENT,
        )
    )
    return {"task_id": str(task_id)}


async def _apply_send_email(
    session: AsyncSession, approval: ApprovalItem, payload: BaseModel
) -> dict[str, Any]:
    p = SendEmailPayload.model_validate(payload.model_dump())
    msg_id = derived_id(approval, "outbox")
    await session.merge(
        OutboxMessage(
            id=msg_id,
            approval_item_id=approval.id,
            company_id=p.company_id,
            to_address=str(p.to_address),
            subject=p.subject,
            body=p.body,
            status=OutboxStatus.SIMULATED,
        )
    )
    return {"outbox_message_id": str(msg_id), "status": "SIMULATED"}


Applier = Callable[[AsyncSession, ApprovalItem, BaseModel], Awaitable[dict[str, Any]]]

ACTIONS: dict[ActionType, tuple[type[BaseModel], Applier]] = {
    ActionType.CREATE_TASK: (CreateTaskPayload, _apply_create_task),
    ActionType.SEND_EMAIL: (SendEmailPayload, _apply_send_email),
    # ESCALATE_EWS, SUBMIT_CAM, FLAG_KYB, UPDATE_KYB_RECORD arrive with their graphs (Phase 4).
}


def payload_schema(action: ActionType) -> type[BaseModel]:
    if action not in ACTIONS:
        raise NotImplementedError(f"{action.value} has no applier yet")
    return ACTIONS[action][0]
