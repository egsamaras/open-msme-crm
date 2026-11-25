"""Document upload and KYB checks (SPEC 4.2, graph 2)."""

import re
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.agents import runtime
from app.api.deps import SessionDep, require_roles
from app.models import AgentRun, Company, Document, User
from app.models.enums import AgentRunStatus, DocumentType, Role, VerificationStatus
from app.schemas.agents import AgentRunSummary
from app.services import audit
from app.services.access import account_or_404
from app.services.kyb import MAX_UPLOAD_BYTES, text_from_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])

KybUser = Annotated[User, Depends(require_roles(Role.RM, Role.COMPLIANCE))]


def _safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name.rsplit("/", 1)[-1]).strip("-.")
    return (base or "document")[:200]


async def _start_check(
    session: SessionDep, background: BackgroundTasks, user: User, doc: Document, company: Company
) -> AgentRunSummary:
    runs = await session.scalars(
        select(AgentRun).where(
            AgentRun.company_id == doc.company_id,
            AgentRun.agent_name == "kyb_intake",
            AgentRun.status.in_([AgentRunStatus.RUNNING, AgentRunStatus.AWAITING_APPROVAL]),
        )
    )
    for run in runs:
        if (run.result or {}).get("document_id") == str(doc.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A KYB check for this document is already in progress"
            )
    run = await runtime.create_run(
        session, agent_name="kyb_intake", user_id=user.id, company_id=doc.company_id
    )
    await audit.record(
        session,
        action="agent.started",
        entity_type="agent_run",
        entity_id=run.id,
        payload={"agent": "kyb_intake", "document_id": str(doc.id)},
        actor_user_id=user.id,
    )
    await session.commit()
    background.add_task(runtime.execute, run.id, {"document_id": str(doc.id)})
    return AgentRunSummary(
        id=run.id,
        thread_id=run.thread_id,
        agent_name=run.agent_name,
        status=run.status,
        company_id=company.id,
        company_name=company.trading_name,
        deal_id=None,
        triggered_by_name=user.full_name,
        created_at=run.created_at,
        finished_at=None,
    )


@router.post("/upload", response_model=AgentRunSummary, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background: BackgroundTasks,
    session: SessionDep,
    user: KybUser,
    company_id: Annotated[uuid.UUID, Form()],
    doc_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File(description=".txt, .json or .pdf, up to 1 MB")],
) -> AgentRunSummary:
    """Store a document (pending) and start its KYB check. Its text is treated as untrusted."""
    company = await account_or_404(session, company_id, user)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    name = _safe_name(file.filename or "document.txt")
    try:
        text = text_from_upload(name, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    doc = Document(
        id=uuid.uuid4(),
        company_id=company_id,
        doc_type=doc_type,
        file_name=name,
        content_text=text,
        verification_status=VerificationStatus.PENDING,
        extracted_fields={},
    )
    session.add(doc)
    await session.flush()
    await audit.record(
        session,
        action="document.uploaded",
        entity_type="document",
        entity_id=doc.id,
        payload={"company_id": str(company_id), "doc_type": doc_type.value, "file_name": name},
        actor_user_id=user.id,
    )
    return await _start_check(session, background, user, doc, company)


@router.post(
    "/{document_id}/check", response_model=AgentRunSummary, status_code=status.HTTP_202_ACCEPTED
)
async def check_document(
    document_id: uuid.UUID, background: BackgroundTasks, session: SessionDep, user: KybUser
) -> AgentRunSummary:
    """Run the KYB check on a document already on file."""
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such document")
    company = await account_or_404(session, doc.company_id, user, "No such document")
    if not doc.content_text:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This document has no text on file to check"
        )
    return await _start_check(session, background, user, doc, company)
