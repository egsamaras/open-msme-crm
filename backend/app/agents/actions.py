"""What an approved action does, and the payload shape a reviewer may edit.

Each action type has a Pydantic payload schema (edits are validated against it) and an applier
that runs only after approval. Appliers are idempotent: rows they create get a UUID derived from
the approval item, so a retried apply can't create duplicates. Outbound email is never sent:
it lands in the outbox as SIMULATED (SPEC 4.1, rule 6).
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ApprovalItem,
    BeneficialOwner,
    Company,
    Deal,
    Document,
    EarlyWarningSignal,
    OutboxMessage,
    Task,
    User,
)
from app.models.enums import (
    ActionType,
    DealStage,
    EwsStatus,
    KybStatus,
    OutboxStatus,
    ScreeningStatus,
    TaskSource,
    TaskStatus,
    VerificationStatus,
)
from app.services.access import can_hold

_NS = uuid.UUID("0b8f3f0e-6b1c-4d3e-9a7f-2a1d5c9e8b47")


def derived_id(approval: ApprovalItem, kind: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{approval.id}:{kind}")


def _in_days(n: int) -> date:
    return datetime.now(UTC).date() + timedelta(days=n)


async def _task(
    session: AsyncSession,
    approval: ApprovalItem,
    kind: str,
    *,
    company_id: uuid.UUID,
    assignee_id: uuid.UUID | None,
    title: str,
    due_in: int,
    deal_id: uuid.UUID | None = None,
) -> uuid.UUID:
    task_id = derived_id(approval, kind)
    await session.merge(
        Task(
            id=task_id,
            company_id=company_id,
            deal_id=deal_id,
            assignee_id=assignee_id,
            title=title[:255],
            due_date=_in_days(due_in),
            status=TaskStatus.OPEN,
            source=TaskSource.AGENT,
        )
    )
    return task_id


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
    company = await session.get(Company, p.company_id)
    assert company is not None
    # The first who can hold the account (active, and may see it): the named assignee, the
    # account's RM, the person who started the run. A cron scan has no starter, and the account
    # may have changed hands while the proposal waited. If none can, the task stays unassigned.
    assignee_id = None
    for candidate in (p.assignee_id, company.rm_id, approval.initiator_id):
        if candidate and can_hold(await session.get(User, candidate), company):
            assignee_id = candidate
            break
    task_id = derived_id(approval, "task")
    await session.merge(
        Task(
            id=task_id,
            company_id=p.company_id,
            assignee_id=assignee_id,
            title=p.title,
            due_date=p.due_date,
            status=TaskStatus.OPEN,
            source=TaskSource.AGENT,
        )
    )
    return {"task_id": str(task_id), "assignee_id": str(assignee_id) if assignee_id else None}


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


class EscalateEwsPayload(BaseModel):
    company_id: uuid.UUID
    signal_ids: list[uuid.UUID] = Field(min_length=1)
    summary: str = Field(min_length=20, max_length=4000, description="Note to the credit officer")
    rm_task_title: str = Field(min_length=3, max_length=255)
    rationale: str | None = Field(default=None, max_length=2000)


async def _apply_escalate_ews(
    session: AsyncSession, approval: ApprovalItem, payload: BaseModel
) -> dict[str, Any]:
    p = EscalateEwsPayload.model_validate(payload.model_dump())
    company = await session.get(Company, p.company_id)
    assert company is not None
    signals = list(
        await session.scalars(
            select(EarlyWarningSignal).where(
                EarlyWarningSignal.id.in_(p.signal_ids),
                EarlyWarningSignal.company_id == p.company_id,
            )
        )
    )
    for sig in signals:
        if sig.status == EwsStatus.OPEN:
            sig.status = EwsStatus.INVESTIGATING
    name = company.trading_name or company.legal_name
    review = await _task(
        session,
        approval,
        "credit-review",
        company_id=p.company_id,
        assignee_id=approval.reviewer_id,
        title=f"Credit review of early-warning signals: {name}",
        due_in=3,
    )
    call = await _task(
        session,
        approval,
        "rm-call",
        company_id=p.company_id,
        assignee_id=company.rm_id,
        title=p.rm_task_title,
        due_in=2,
    )
    return {
        "signals_investigating": [str(s.id) for s in signals],
        "credit_review_task_id": str(review),
        "rm_task_id": str(call),
    }


class CamSection(BaseModel):
    key: str = Field(max_length=64)
    title: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=20, max_length=8000)


class SubmitCamPayload(BaseModel):
    company_id: uuid.UUID
    deal_id: uuid.UUID
    sections: list[CamSection] = Field(min_length=1, max_length=12)
    risk_grade: int = Field(ge=1, le=10, description="Indicative grade, 1 strongest, 10 weakest")
    ratios: dict[str, str | None]
    assumptions: dict[str, str]
    rationale: str | None = Field(default=None, max_length=2000)


async def _apply_submit_cam(
    session: AsyncSession, approval: ApprovalItem, payload: BaseModel
) -> dict[str, Any]:
    from app.services import audit  # local: audit imports models, keep this module light

    p = SubmitCamPayload.model_validate(payload.model_dump())
    deal = await session.get(Deal, p.deal_id, with_for_update=True)
    assert deal is not None
    if deal.stage != DealStage.CREDIT_UNDERWRITING:
        # Someone moved the deal while the memo waited; don't drag it back.
        return {"skipped": f"deal is now in {deal.stage.value}"}
    before = deal.stage
    deal.stage = DealStage.APPROVAL
    deal.probability_pct = max(deal.probability_pct, 80)
    deal.credit_officer_id = approval.reviewer_id
    deal.draft_cam = {
        **p.model_dump(mode="json", exclude={"rationale"}),
        "approval_item_id": str(approval.id),
    }
    task = await _task(
        session,
        approval,
        "credit-decision",
        company_id=p.company_id,
        deal_id=deal.id,
        assignee_id=approval.reviewer_id,
        title=f"Credit decision: {deal.title}",
        due_in=5,
    )
    await audit.record(
        session,
        action="deal.update",
        entity_type="deal",
        entity_id=deal.id,
        payload={
            "from": {"stage": before.value},
            "to": {"stage": deal.stage.value, "credit_officer_id": str(approval.reviewer_id)},
            "via": "credit memo approval",
        },
        actor_user_id=approval.reviewer_id,
    )
    return {"deal_stage": deal.stage.value, "credit_decision_task_id": str(task)}


class Discrepancy(BaseModel):
    kind: str = Field(max_length=64)
    detail: str = Field(max_length=500)


class FlagKybPayload(BaseModel):
    company_id: uuid.UUID
    document_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=2000)
    discrepancies: list[Discrepancy] = Field(min_length=1)
    rationale: str | None = Field(default=None, max_length=2000)


async def _apply_flag_kyb(
    session: AsyncSession, approval: ApprovalItem, payload: BaseModel
) -> dict[str, Any]:
    p = FlagKybPayload.model_validate(payload.model_dump())
    company = await session.get(Company, p.company_id)
    doc = await session.get(Document, p.document_id)
    assert company is not None and doc is not None and doc.company_id == company.id
    company.kyb_status = KybStatus.FLAGGED
    doc.verification_status = VerificationStatus.REJECTED
    task = await _task(
        session,
        approval,
        "kyb-followup",
        company_id=company.id,
        assignee_id=company.rm_id,
        title=f"KYB issue on {doc.file_name}: obtain a corrected document",
        due_in=5,
    )
    return {"kyb_status": company.kyb_status.value, "document": "REJECTED", "task_id": str(task)}


class OwnerEntry(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    ownership_pct: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class UpdateKybRecordPayload(BaseModel):
    company_id: uuid.UUID
    document_id: uuid.UUID
    owners: list[OwnerEntry] = Field(min_length=1, max_length=20)
    discrepancies: list[Discrepancy] = Field(min_length=1)
    rationale: str | None = Field(default=None, max_length=2000)

    @field_validator("owners")
    @classmethod
    def _total_at_most_100(cls, owners: list[OwnerEntry]) -> list[OwnerEntry]:
        if sum((o.ownership_pct for o in owners), Decimal(0)) > Decimal(100):
            raise ValueError("ownership adds up to more than 100%")
        if len({o.full_name.casefold() for o in owners}) != len(owners):
            raise ValueError("an owner is listed twice")
        return owners


async def _apply_update_kyb_record(
    session: AsyncSession, approval: ApprovalItem, payload: BaseModel
) -> dict[str, Any]:
    p = UpdateKybRecordPayload.model_validate(payload.model_dump())
    doc = await session.get(Document, p.document_id)
    assert doc is not None and doc.company_id == p.company_id
    existing = {
        o.full_name.casefold(): o
        for o in await session.scalars(
            select(BeneficialOwner).where(BeneficialOwner.company_id == p.company_id)
        )
    }
    wanted = {o.full_name.casefold(): o for o in p.owners}
    changes: list[str] = []
    for key, entry in wanted.items():
        row = existing.get(key)
        if row is None:
            company = await session.get(Company, p.company_id)
            assert company is not None
            session.add(
                BeneficialOwner(
                    id=derived_id(approval, f"owner:{key}"),
                    company_id=p.company_id,
                    full_name=entry.full_name,
                    nationality=company.country,
                    ownership_pct=entry.ownership_pct,
                    pep_status=ScreeningStatus.PENDING,
                    sanctions_status=ScreeningStatus.PENDING,
                )
            )
            changes.append(f"added {entry.full_name} at {entry.ownership_pct}%")
        elif row.ownership_pct != entry.ownership_pct:
            changes.append(f"{row.full_name}: {row.ownership_pct}% -> {entry.ownership_pct}%")
            row.ownership_pct = entry.ownership_pct
    for key, row in existing.items():
        if key not in wanted:
            changes.append(f"removed {row.full_name}")
            await session.delete(row)
    doc.verification_status = VerificationStatus.VERIFIED
    doc.extracted_fields = {
        **(doc.extracted_fields or {}),
        "owners": [o.model_dump(mode="json") for o in p.owners],
    }
    return {"changes": changes, "document": "VERIFIED"}


Applier = Callable[[AsyncSession, ApprovalItem, BaseModel], Awaitable[dict[str, Any]]]

ACTIONS: dict[ActionType, tuple[type[BaseModel], Applier]] = {
    ActionType.CREATE_TASK: (CreateTaskPayload, _apply_create_task),
    ActionType.SEND_EMAIL: (SendEmailPayload, _apply_send_email),
    ActionType.ESCALATE_EWS: (EscalateEwsPayload, _apply_escalate_ews),
    ActionType.SUBMIT_CAM: (SubmitCamPayload, _apply_submit_cam),
    ActionType.FLAG_KYB: (FlagKybPayload, _apply_flag_kyb),
    ActionType.UPDATE_KYB_RECORD: (UpdateKybRecordPayload, _apply_update_kyb_record),
}

# Fields a reviewer may not change when editing: the evidence and the target stay as proposed.
LOCKED_FIELDS: dict[ActionType, tuple[str, ...]] = {
    ActionType.CREATE_TASK: ("company_id",),
    ActionType.SEND_EMAIL: ("company_id",),
    ActionType.ESCALATE_EWS: ("company_id", "signal_ids"),
    ActionType.SUBMIT_CAM: ("company_id", "deal_id", "ratios", "assumptions"),
    ActionType.FLAG_KYB: ("company_id", "document_id", "discrepancies"),
    ActionType.UPDATE_KYB_RECORD: ("company_id", "document_id", "discrepancies"),
}


def payload_schema(action: ActionType) -> type[BaseModel]:
    if action not in ACTIONS:
        raise NotImplementedError(f"{action.value} has no applier yet")
    return ACTIONS[action][0]


async def edit_error(
    session: AsyncSession, action: ActionType, proposed: dict[str, Any], edited: dict[str, Any]
) -> str | None:
    """Why a reviewer's edited payload can't be used, or None if it can. Locked fields stay as
    proposed; a task may go to any active user who can see the account (`can_hold`)."""
    for locked in LOCKED_FIELDS[action]:
        if edited.get(locked) != proposed.get(locked):
            what = "the account" if locked == "company_id" else locked.replace("_", " ")
            return f"You can't change {what}"
    assignee = edited.get("assignee_id")
    if action == ActionType.CREATE_TASK and assignee and assignee != proposed.get("assignee_id"):
        company = await session.get(Company, uuid.UUID(edited["company_id"]))
        holder = await session.get(User, uuid.UUID(assignee))
        if company is None or not can_hold(holder, company):
            return "No such assignee"
    return None
