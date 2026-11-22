import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, Json, Money, Pct, Ratio, TimestampMixin, str_enum
from app.models.enums import (
    DealStage,
    DocumentType,
    EwsStatus,
    EwsTrigger,
    InteractionType,
    KybStatus,
    MsmeTier,
    PeriodType,
    Product,
    Role,
    ScreeningStatus,
    Severity,
    TaskSource,
    TaskStatus,
    VerificationStatus,
)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(str_enum(Role))
    branch: Mapped[str | None] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (CheckConstraint("risk_rating BETWEEN 1 AND 10", name="risk_rating_range"),)

    legal_name: Mapped[str] = mapped_column(String(255))
    trading_name: Mapped[str | None] = mapped_column(String(255))
    cr_number: Mapped[str] = mapped_column(String(64), unique=True)
    country: Mapped[str] = mapped_column(String(2))
    industry: Mapped[str] = mapped_column(String(100))
    tier: Mapped[MsmeTier] = mapped_column(str_enum(MsmeTier))
    annual_turnover: Mapped[Money]
    currency: Mapped[str] = mapped_column(String(3))
    risk_rating: Mapped[int]
    kyb_status: Mapped[KybStatus] = mapped_column(str_enum(KybStatus))
    kyb_next_review: Mapped[date | None] = mapped_column(Date)
    rm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)

    rm: Mapped[User | None] = relationship(lazy="raise")


class BeneficialOwner(IdMixin, TimestampMixin, Base):
    __tablename__ = "beneficial_owners"
    __table_args__ = (
        CheckConstraint("ownership_pct >= 0 AND ownership_pct <= 100", name="ownership_range"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(200))
    nationality: Mapped[str] = mapped_column(String(2))
    ownership_pct: Mapped[Pct]
    pep_status: Mapped[ScreeningStatus] = mapped_column(str_enum(ScreeningStatus, "pep_status"))
    sanctions_status: Mapped[ScreeningStatus] = mapped_column(
        str_enum(ScreeningStatus, "sanctions_status")
    )


class Contact(IdMixin, TimestampMixin, Base):
    __tablename__ = "contacts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_primary: Mapped[bool] = mapped_column(default=False)


class Facility(IdMixin, TimestampMixin, Base):
    __tablename__ = "facilities"
    __table_args__ = (CheckConstraint("sanctioned_limit >= 0", name="limit_non_negative"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    product: Mapped[Product] = mapped_column(str_enum(Product))
    is_islamic: Mapped[bool] = mapped_column(default=False)
    sanctioned_limit: Mapped[Money]
    utilized_amount: Mapped[Money]
    rate_pct: Mapped[Ratio]
    start_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    covenants: Mapped[Json] = mapped_column(default=list)


class FacilityUtilization(IdMixin, Base):
    __tablename__ = "facility_utilizations"
    __table_args__ = (UniqueConstraint("facility_id", "as_of", name="facility_as_of"),)

    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), index=True
    )
    as_of: Mapped[date] = mapped_column(Date)
    utilized_amount: Mapped[Money]


class FinancialSnapshot(IdMixin, TimestampMixin, Base):
    """Raw inputs only. Ratios are computed by app.services.financial_math (SPEC 3)."""

    __tablename__ = "financial_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "period_type", "period_end", name="company_period"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[PeriodType] = mapped_column(str_enum(PeriodType))
    revenue: Mapped[Money]
    ebitda: Mapped[Money]
    net_profit: Mapped[Money]
    interest_expense: Mapped[Money]
    principal_repayment: Mapped[Money]
    total_debt: Mapped[Money]
    total_equity: Mapped[Money]
    current_assets: Mapped[Money]
    current_liabilities: Mapped[Money]
    avg_bank_balance: Mapped[Money]
    bounced_cheques: Mapped[int] = mapped_column(default=0)


class Deal(IdMixin, TimestampMixin, Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint("probability_pct BETWEEN 0 AND 100", name="probability_range"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    product: Mapped[Product] = mapped_column(str_enum(Product))
    stage: Mapped[DealStage] = mapped_column(str_enum(DealStage), index=True)
    requested_amount: Mapped[Money]
    probability_pct: Mapped[int]
    expected_close: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    draft_cam: Mapped[Json | None]


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"))
    doc_type: Mapped[DocumentType] = mapped_column(str_enum(DocumentType))
    file_name: Mapped[str] = mapped_column(String(255))
    content_text: Mapped[str | None] = mapped_column(Text)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus), default=VerificationStatus.PENDING
    )
    extracted_fields: Mapped[Json] = mapped_column(default=dict)


class Interaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "interactions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    interaction_type: Mapped[InteractionType] = mapped_column(str_enum(InteractionType))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus), default=TaskStatus.OPEN)
    source: Mapped[TaskSource] = mapped_column(str_enum(TaskSource), default=TaskSource.MANUAL)


class EarlyWarningSignal(IdMixin, TimestampMixin, Base):
    __tablename__ = "early_warning_signals"
    __table_args__ = (Index("ix_ews_status_severity", "status", "severity"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[EwsTrigger] = mapped_column(str_enum(EwsTrigger))
    severity: Mapped[Severity] = mapped_column(str_enum(Severity))
    status: Mapped[EwsStatus] = mapped_column(str_enum(EwsStatus), default=EwsStatus.OPEN)
    metrics: Mapped[Json] = mapped_column(default=dict)
    root_cause_summary: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
