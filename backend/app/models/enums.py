from enum import StrEnum


class Role(StrEnum):
    RM = "RM"
    CREDIT_OFFICER = "CREDIT_OFFICER"
    COMPLIANCE = "COMPLIANCE"
    ADMIN = "ADMIN"


class MsmeTier(StrEnum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"


class KybStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PENDING_RENEWAL = "PENDING_RENEWAL"
    FLAGGED = "FLAGGED"


class ScreeningStatus(StrEnum):
    CLEAR = "CLEAR"
    HIT = "HIT"
    PENDING = "PENDING"


class Product(StrEnum):
    WORKING_CAPITAL = "WORKING_CAPITAL"
    TERM_LOAN = "TERM_LOAN"
    TRADE_FINANCE_LC = "TRADE_FINANCE_LC"
    LETTER_OF_GUARANTEE = "LETTER_OF_GUARANTEE"
    POS_MERCHANT = "POS_MERCHANT"
    FX_LINE = "FX_LINE"
    CASH_MANAGEMENT = "CASH_MANAGEMENT"
    MURABAHA = "MURABAHA"
    IJARA = "IJARA"


ISLAMIC_PRODUCTS = frozenset({Product.MURABAHA, Product.IJARA})

PRODUCT_LABEL: dict[Product, str] = {
    Product.WORKING_CAPITAL: "working capital",
    Product.TERM_LOAN: "term loan",
    Product.TRADE_FINANCE_LC: "trade finance (LC)",
    Product.LETTER_OF_GUARANTEE: "letter of guarantee",
    Product.POS_MERCHANT: "POS merchant",
    Product.FX_LINE: "FX line",
    Product.CASH_MANAGEMENT: "cash management",
    Product.MURABAHA: "Murabaha",
    Product.IJARA: "Ijara",
}


class PeriodType(StrEnum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class DealStage(StrEnum):
    LEAD = "LEAD"
    QUALIFICATION = "QUALIFICATION"
    DOC_COLLECTION = "DOC_COLLECTION"
    CREDIT_UNDERWRITING = "CREDIT_UNDERWRITING"
    APPROVAL = "APPROVAL"
    DISBURSED = "DISBURSED"
    LOST = "LOST"


class DocumentType(StrEnum):
    TRADE_LICENSE = "TRADE_LICENSE"
    CR_CERTIFICATE = "CR_CERTIFICATE"
    FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"
    BANK_STATEMENT = "BANK_STATEMENT"
    TAX_RETURN = "TAX_RETURN"
    UBO_DECLARATION = "UBO_DECLARATION"


class VerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InteractionType(StrEnum):
    CALL = "CALL"
    MEETING = "MEETING"
    EMAIL = "EMAIL"
    SITE_VISIT = "SITE_VISIT"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"


class TaskSource(StrEnum):
    MANUAL = "MANUAL"
    AGENT = "AGENT"


class EwsTrigger(StrEnum):
    CASHFLOW_DROP = "CASHFLOW_DROP"
    UTILIZATION_SPIKE = "UTILIZATION_SPIKE"
    DOC_EXPIRY = "DOC_EXPIRY"
    BOUNCED_CHEQUES = "BOUNCED_CHEQUES"
    COVENANT_BREACH = "COVENANT_BREACH"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EwsStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"


class AgentRunStatus(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class ActionType(StrEnum):
    SEND_EMAIL = "SEND_EMAIL"
    CREATE_TASK = "CREATE_TASK"
    ESCALATE_EWS = "ESCALATE_EWS"
    SUBMIT_CAM = "SUBMIT_CAM"
    FLAG_KYB = "FLAG_KYB"
    UPDATE_KYB_RECORD = "UPDATE_KYB_RECORD"


# Actions that need a second person with a specific role (SPEC 4.1, rule 2).
FOUR_EYES_ROLES: dict[ActionType, frozenset[Role]] = {
    ActionType.SUBMIT_CAM: frozenset({Role.CREDIT_OFFICER, Role.ADMIN}),
    ActionType.ESCALATE_EWS: frozenset({Role.CREDIT_OFFICER, Role.ADMIN}),
    ActionType.FLAG_KYB: frozenset({Role.COMPLIANCE, Role.ADMIN}),
    ActionType.UPDATE_KYB_RECORD: frozenset({Role.COMPLIANCE, Role.ADMIN}),
}


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EDITED_AND_APPROVED = "EDITED_AND_APPROVED"
    REJECTED = "REJECTED"


class OutboxStatus(StrEnum):
    SIMULATED = "SIMULATED"
