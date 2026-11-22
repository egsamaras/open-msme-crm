import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, Json, TimestampMixin, str_enum, utcnow
from app.models.enums import ActionType, AgentRunStatus, ApprovalStatus, OutboxStatus


class AgentRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

    thread_id: Mapped[str] = mapped_column(String(100), unique=True)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"), index=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id"))
    status: Mapped[AgentRunStatus] = mapped_column(
        str_enum(AgentRunStatus), default=AgentRunStatus.RUNNING
    )
    trace: Mapped[Json] = mapped_column(default=list)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "approval_items"

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    action_type: Mapped[ActionType] = mapped_column(str_enum(ActionType))
    proposed_payload: Mapped[Json]
    edited_payload: Mapped[Json | None]
    status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True
    )
    initiator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "outbox_messages"

    approval_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_items.id", ondelete="SET NULL")
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    to_address: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[OutboxStatus] = mapped_column(
        str_enum(OutboxStatus), default=OutboxStatus.SIMULATED
    )


class AuditEvent(Base):
    """Append-only. A database trigger rejects UPDATE and DELETE (see the initial migration)."""

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_agent: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[Json] = mapped_column(default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
