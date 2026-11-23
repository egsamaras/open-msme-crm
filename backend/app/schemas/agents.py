import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ActionType, AgentRunStatus, ApprovalStatus, Role


class AgentRunSummary(BaseModel):
    id: uuid.UUID
    thread_id: str
    agent_name: str
    status: AgentRunStatus
    company_id: uuid.UUID | None
    company_name: str | None
    deal_id: uuid.UUID | None
    parent_run_id: uuid.UUID | None = None
    triggered_by_name: str | None
    created_at: datetime
    finished_at: datetime | None


class CitedRecord(BaseModel):
    id: uuid.UUID
    kind: str
    label: str
    href: str | None


class AgentRunDetail(AgentRunSummary):
    trace: list[dict[str, Any]]
    result: dict[str, Any] | None
    cited_records: list[CitedRecord]
    approval_ids: list[uuid.UUID]


class ApprovalOut(BaseModel):
    id: uuid.UUID
    action_type: ActionType
    status: ApprovalStatus
    proposed_payload: dict[str, Any]
    edited_payload: dict[str, Any] | None
    company_id: uuid.UUID | None
    company_name: str | None
    initiator_id: uuid.UUID | None
    initiator_name: str | None
    reviewer_name: str | None
    review_note: str | None
    created_at: datetime
    resolved_at: datetime | None
    required_roles: list[Role]
    four_eyes: bool
    can_review: bool
    review_blocker: str | None = Field(description="Why you can't review this, if you can't")
    run: AgentRunSummary


class ApprovalCount(BaseModel):
    pending_for_me: int
    pending_total: int


class ResolveIn(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    payload: dict[str, Any] | None = Field(
        default=None, description="Edited payload; if it differs from the proposal it's an edit"
    )
    note: str | None = Field(default=None, max_length=2000)


class AuditEventOut(BaseModel):
    seq: int
    occurred_at: datetime
    actor_name: str | None
    actor_agent: str | None
    action: str
    entity_type: str
    entity_id: str | None
    payload: dict[str, Any]
    hash: str
