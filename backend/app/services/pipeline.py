"""Deal pipeline rules: document checklist and who may move a deal where."""

from collections.abc import Iterable
from datetime import date

from app.models import Document
from app.models.enums import DealStage, DocumentType, Role, VerificationStatus
from app.schemas.crm import ChecklistItem, ChecklistState

REQUIRED_DOCUMENTS: tuple[DocumentType, ...] = (
    DocumentType.TRADE_LICENSE,
    DocumentType.CR_CERTIFICATE,
    DocumentType.UBO_DECLARATION,
    DocumentType.FINANCIAL_STATEMENT,
    DocumentType.BANK_STATEMENT,
)

OPEN_STAGES = (
    DealStage.LEAD,
    DealStage.QUALIFICATION,
    DealStage.DOC_COLLECTION,
    DealStage.CREDIT_UNDERWRITING,
)

# APPROVAL is reached only by submitting a credit memo through the four-eyes approval flow
# (SPEC 4.2, graph 4); DISBURSED only by a credit officer after approval.
CREDIT_ROLES = frozenset({Role.CREDIT_OFFICER, Role.ADMIN})


def _doc_state(doc: Document, today: date) -> ChecklistState:
    if doc.expiry_date is not None and doc.expiry_date < today:
        return "EXPIRED"
    return doc.verification_status.value


def build_checklist(documents: Iterable[Document], today: date) -> list[ChecklistItem]:
    """One row per required document type, using the newest document of that type."""
    newest: dict[DocumentType, Document] = {}
    for doc in documents:
        current = newest.get(doc.doc_type)
        if current is None or doc.created_at > current.created_at:
            newest[doc.doc_type] = doc
    items = []
    for doc_type in REQUIRED_DOCUMENTS:
        found = newest.get(doc_type)
        items.append(
            ChecklistItem(
                doc_type=doc_type,
                state=_doc_state(found, today) if found else "MISSING",
                document_id=found.id if found else None,
                expiry_date=found.expiry_date if found else None,
            )
        )
    return items


def checklist_complete(items: Iterable[ChecklistItem]) -> bool:
    return all(i.state == VerificationStatus.VERIFIED.value for i in items)


def allowed_stages(current: DealStage, role: Role) -> list[DealStage]:
    """Stages this role may move a deal to by hand from `current`.

    RMs work the open stages. Credit officers act only once a deal is in APPROVAL.
    Compliance can't move deals. Admin can do both.
    """
    if current in (DealStage.DISBURSED, DealStage.LOST):
        return []
    if current == DealStage.APPROVAL:
        return [DealStage.DISBURSED, DealStage.LOST] if role in CREDIT_ROLES else []
    if role in (Role.RM, Role.ADMIN):
        return [s for s in (*OPEN_STAGES, DealStage.LOST) if s != current]
    return []
