from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import SessionDep, require_roles
from app.core.config import get_settings
from app.models import User
from app.models.enums import Role
from app.schemas.common import AppInfo, AuditChainOut
from app.services import audit

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/info", response_model=AppInfo)
async def info() -> AppInfo:
    s = get_settings()
    return AppInfo(
        environment=s.environment,
        llm_provider=s.llm_provider,
        dev_persona_switch=s.is_dev,
        default_currency=s.default_currency,
    )


@router.get("/audit/verify", response_model=AuditChainOut)
async def verify_audit_chain(
    session: SessionDep,
    _: Annotated[User, Depends(require_roles(Role.COMPLIANCE))],
) -> AuditChainOut:
    result = await audit.verify_chain(session)
    return AuditChainOut(
        ok=result.ok, events_checked=result.events_checked, first_bad_seq=result.first_bad_seq
    )
