import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import KybStatus, MsmeTier, Role


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(OrmModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    branch: str | None


class SessionOut(BaseModel):
    user: UserOut | None


class LoginIn(BaseModel):
    # Plain str: demo accounts use the reserved .local domain, which EmailStr rejects.
    email: str = Field(min_length=3, max_length=255)
    password: str


class PersonaSwitchIn(BaseModel):
    user_id: uuid.UUID


class AppInfo(BaseModel):
    environment: str
    llm_provider: str
    dev_persona_switch: bool
    default_currency: str


class AccountListItem(OrmModel):
    id: uuid.UUID
    legal_name: str
    trading_name: str | None
    cr_number: str
    country: str
    industry: str
    tier: MsmeTier
    currency: str
    annual_turnover: Decimal
    risk_rating: int
    kyb_status: KybStatus
    kyb_next_review: date | None
    rm_name: str | None
    total_limit: Decimal
    total_utilized: Decimal
    open_ews: int


class AuditChainOut(BaseModel):
    ok: bool
    events_checked: int
    first_bad_seq: int | None
