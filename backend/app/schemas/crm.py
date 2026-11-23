import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    AgentRunStatus,
    DealStage,
    DocumentType,
    EwsStatus,
    EwsTrigger,
    InteractionType,
    KybStatus,
    MsmeTier,
    Product,
    ScreeningStatus,
    Severity,
    TaskSource,
    TaskStatus,
    VerificationStatus,
)
from app.schemas.common import OrmModel

# ---- Accounts ----


class OwnerOut(OrmModel):
    id: uuid.UUID
    full_name: str
    nationality: str
    ownership_pct: Decimal
    is_ubo: bool
    pep_status: ScreeningStatus
    sanctions_status: ScreeningStatus


class ContactOut(OrmModel):
    id: uuid.UUID
    full_name: str
    title: str | None
    email: str | None
    phone: str | None
    is_primary: bool


class AccountDetail(OrmModel):
    id: uuid.UUID
    legal_name: str
    trading_name: str | None
    cr_number: str
    country: str
    industry: str
    tier: MsmeTier
    annual_turnover: Decimal
    currency: str
    risk_rating: int
    kyb_status: KybStatus
    kyb_next_review: date | None
    rm_id: uuid.UUID | None
    rm_name: str | None
    ubo_threshold_pct: Decimal
    owners: list[OwnerOut]
    contacts: list[ContactOut]


class UtilizationPoint(BaseModel):
    as_of: date
    utilized_amount: Decimal
    utilization_pct: Decimal | None


class CovenantResult(BaseModel):
    metric: str
    operator: str
    threshold: Decimal
    actual: Decimal | None
    passes: bool | None
    tested_on: date | None


class FacilityOut(BaseModel):
    id: uuid.UUID
    product: Product
    is_islamic: bool
    sanctioned_limit: Decimal
    utilized_amount: Decimal
    utilization_pct: Decimal | None
    days_above_alert_threshold: int
    alert_threshold_pct: Decimal
    rate_pct: Decimal
    start_date: date
    maturity_date: date | None
    covenants: list[CovenantResult]
    history: list[UtilizationPoint]


class SnapshotOut(BaseModel):
    id: uuid.UUID
    period_end: date
    revenue: Decimal
    ebitda: Decimal
    net_profit: Decimal
    interest_expense: Decimal
    principal_repayment: Decimal
    total_debt: Decimal
    total_equity: Decimal
    current_assets: Decimal
    current_liabilities: Decimal
    avg_bank_balance: Decimal
    bounced_cheques: int
    # Computed by app.services.financial_math, never stored.
    dscr: Decimal | None
    debt_to_equity: Decimal | None
    debt_to_ebitda: Decimal | None
    current_ratio: Decimal | None
    balance_change_pct: Decimal | None = Field(
        description="Change in average bank balance versus the previous month"
    )


class DocumentOut(OrmModel):
    id: uuid.UUID
    deal_id: uuid.UUID | None
    doc_type: DocumentType
    file_name: str
    expiry_date: date | None
    verification_status: VerificationStatus
    created_at: datetime


class InteractionOut(OrmModel):
    id: uuid.UUID
    interaction_type: InteractionType
    occurred_at: datetime
    summary: str
    notes: str | None
    user_name: str | None


class InteractionIn(BaseModel):
    interaction_type: InteractionType
    occurred_at: datetime
    summary: str = Field(min_length=3, max_length=500)
    notes: str | None = Field(default=None, max_length=5000)


class EwsOut(OrmModel):
    id: uuid.UUID
    trigger: EwsTrigger
    severity: Severity
    status: EwsStatus
    metrics: dict[str, object]
    root_cause_summary: str | None
    resolution_note: str | None
    detected_at: datetime
    resolved_at: datetime | None


class EwsListItem(EwsOut):
    company_id: uuid.UUID
    company_name: str
    resolved_by_name: str | None


class EwsUpdate(BaseModel):
    status: Literal["INVESTIGATING", "RESOLVED"]
    note: str | None = Field(default=None, max_length=2000)


# ---- Tasks ----


class TaskOut(OrmModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    deal_id: uuid.UUID | None
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    title: str
    due_date: date | None
    status: TaskStatus
    source: TaskSource


class TaskIn(BaseModel):
    company_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    title: str = Field(min_length=3, max_length=255)
    due_date: date | None = None
    assignee_id: uuid.UUID | None = Field(default=None, description="Defaults to you")


class TaskPatch(BaseModel):
    status: TaskStatus


# ---- Deals ----


class DealOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    currency: str
    title: str
    product: Product
    stage: DealStage
    requested_amount: Decimal
    probability_pct: int
    expected_close: date | None
    owner_name: str | None
    has_draft_cam: bool


ChecklistState = Literal["MISSING", "EXPIRED", "PENDING", "VERIFIED", "REJECTED"]


class ChecklistItem(BaseModel):
    doc_type: DocumentType
    state: ChecklistState
    document_id: uuid.UUID | None
    expiry_date: date | None


class CamSectionOut(BaseModel):
    key: str
    title: str
    body: str


class DraftCamOut(BaseModel):
    """The credit memo as approved by a credit officer (stored on the deal)."""

    sections: list[CamSectionOut]
    risk_grade: int
    ratios: dict[str, str | None]
    assumptions: dict[str, str]


class DealDetail(DealOut):
    checklist: list[ChecklistItem]
    checklist_complete: bool
    allowed_stages: list[DealStage]
    draft_cam: DraftCamOut | None = None
    credit_officer_name: str | None = None
    cam_run_id: uuid.UUID | None = Field(default=None, description="Latest credit memo run")
    cam_run_status: AgentRunStatus | None = None


class DealIn(BaseModel):
    company_id: uuid.UUID
    title: str = Field(min_length=3, max_length=255)
    product: Product
    requested_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    expected_close: date | None = None


class DealPatch(BaseModel):
    stage: DealStage | None = None
    probability_pct: int | None = Field(default=None, ge=0, le=100)
    requested_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    expected_close: date | None = None
