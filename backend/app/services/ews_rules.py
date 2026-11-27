"""Early-warning rules (SPEC 4.2, graph 3). Deterministic: no LLM decides whether a signal fires.

`load_inputs` reads what the rules need for every company; `evaluate` turns one company's inputs
into findings. Each finding carries the exact metric values that fired it and the ids of the
records they came from, so the agent can cite them and the Risk radar can show them.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Company, Document, Facility, FacilityUtilization, FinancialSnapshot
from app.models.enums import (
    DocumentType,
    EwsTrigger,
    PeriodType,
    Product,
    Severity,
    VerificationStatus,
)
from app.services import financial_math as fm

WORKING_CAPITAL_PRODUCTS = frozenset({Product.WORKING_CAPITAL, Product.MURABAHA})
EXPIRING_DOCS = frozenset({DocumentType.TRADE_LICENSE, DocumentType.CR_CERTIFICATE})

SEVERITY_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


@dataclass
class CompanyInputs:
    company: Company
    snapshots: list[FinancialSnapshot]  # monthly, oldest first
    facilities: list[Facility]
    utilization: dict[uuid.UUID, list[FacilityUtilization]] = field(default_factory=dict)
    documents: list[Document] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    trigger: EwsTrigger
    severity: Severity
    metrics: dict[str, Any]
    source_record_ids: list[uuid.UUID]


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def cashflow_drop(inp: CompanyInputs, s: Settings) -> Finding | None:
    """Average bank balance down more than the threshold across the last two months."""
    if len(inp.snapshots) < 3:
        return None
    start, end = inp.snapshots[-3], inp.snapshots[-1]
    change = fm.pct_change(start.avg_bank_balance, end.avg_bank_balance)
    if change is None or change >= -s.ews_balance_drop_pct:
        return None
    return Finding(
        EwsTrigger.CASHFLOW_DROP,
        Severity.CRITICAL if change <= Decimal(-40) else Severity.HIGH,
        {
            "from_period": start.period_end.isoformat(),
            "to_period": end.period_end.isoformat(),
            "from_balance": str(start.avg_bank_balance),
            "to_balance": str(end.avg_bank_balance),
            "change_pct": str(change),
            "threshold_pct": str(-s.ews_balance_drop_pct),
            "currency": inp.company.currency,
        },
        [start.id, end.id],
    )


def utilization_spikes(inp: CompanyInputs, s: Settings) -> list[Finding]:
    """Working-capital utilisation above the threshold on every weekly point for N+ days."""
    out = []
    for f in inp.facilities:
        if f.product not in WORKING_CAPITAL_PRODUCTS:
            continue
        points = [
            (u.as_of, pct)
            for u in inp.utilization.get(f.id, [])
            if (pct := fm.utilization_pct(u.utilized_amount, f.sanctioned_limit)) is not None
        ]
        days = fm.days_continuously_above(points, s.ews_utilization_pct)
        if days < s.ews_utilization_days:
            continue
        latest = max(points)[1]
        out.append(
            Finding(
                EwsTrigger.UTILIZATION_SPIKE,
                Severity.HIGH if days >= 60 or latest >= Decimal(97) else Severity.MEDIUM,
                {
                    "facility_product": f.product.value,
                    "days_above": days,
                    "latest_utilization_pct": str(latest),
                    "threshold_pct": str(s.ews_utilization_pct),
                    "threshold_days": s.ews_utilization_days,
                },
                [f.id],
            )
        )
    return out


def bounced_cheques(inp: CompanyInputs, s: Settings) -> Finding | None:
    if not inp.snapshots or inp.snapshots[-1].bounced_cheques <= 0:
        return None
    latest = inp.snapshots[-1]
    return Finding(
        EwsTrigger.BOUNCED_CHEQUES,
        Severity.HIGH if latest.bounced_cheques >= 3 else Severity.MEDIUM,
        {"period": latest.period_end.isoformat(), "count": latest.bounced_cheques},
        [latest.id],
    )


def doc_expiries(inp: CompanyInputs, s: Settings, today: date) -> list[Finding]:
    """The trade licence or CR certificate in force expires within the threshold.

    In force is the rule behind the Accounts list's next expiry: for each type, the verified
    document with the latest expiry date. A verified renewal takes over from the old document;
    pending and rejected uploads don't count. Of two with the same date, the one added first stays
    in force, so uploading a copy doesn't raise a second alert. The finding cites the document in
    force, which is how the scan matches it to an alert already open on that document.
    """
    in_force: dict[DocumentType, tuple[date, Document]] = {}
    for d in sorted(inp.documents, key=lambda doc: (doc.created_at, str(doc.id))):
        if (
            d.doc_type in EXPIRING_DOCS
            and d.verification_status == VerificationStatus.VERIFIED
            and d.expiry_date is not None
            and (d.doc_type not in in_force or d.expiry_date > in_force[d.doc_type][0])
        ):
            in_force[d.doc_type] = (d.expiry_date, d)
    out = []
    for doc_type, (expiry, d) in sorted(in_force.items()):
        days_left = (expiry - today).days
        if days_left > s.ews_doc_expiry_days:
            continue
        out.append(
            Finding(
                EwsTrigger.DOC_EXPIRY,
                Severity.HIGH if days_left <= 7 else Severity.MEDIUM,
                {
                    "document_type": doc_type.value,
                    "expiry_date": expiry.isoformat(),
                    "days_left": days_left,
                    "threshold_days": s.ews_doc_expiry_days,
                },
                [d.id],
            )
        )
    return out


def covenant_breaches(inp: CompanyInputs, s: Settings) -> list[Finding]:
    if not inp.snapshots:
        return []
    latest = inp.snapshots[-1]
    ratios = fm.snapshot_ratios(latest)
    out = []
    for f in inp.facilities:
        for cov in f.covenants or []:
            value = ratios.metric(cov["metric"])
            if fm.covenant_passes(value, cov["operator"], Decimal(cov["threshold"])) is False:
                out.append(
                    Finding(
                        EwsTrigger.COVENANT_BREACH,
                        Severity.HIGH,
                        {
                            "facility_product": f.product.value,
                            "metric": cov["metric"],
                            "operator": cov["operator"],
                            "threshold": cov["threshold"],
                            "actual": _s(value),
                            "period": latest.period_end.isoformat(),
                        },
                        [f.id, latest.id],
                    )
                )
    return out


def evaluate(inp: CompanyInputs, s: Settings, today: date) -> list[Finding]:
    findings: list[Finding] = []
    for single in (cashflow_drop(inp, s), bounced_cheques(inp, s)):
        if single is not None:
            findings.append(single)
    findings += utilization_spikes(inp, s)
    findings += doc_expiries(inp, s, today)
    findings += covenant_breaches(inp, s)
    return findings


def worst(severities: list[Severity]) -> Severity:
    return max(severities, key=SEVERITY_ORDER.index)


async def load_inputs(session: AsyncSession) -> list[CompanyInputs]:
    companies = list(await session.scalars(select(Company).order_by(Company.legal_name)))
    by_id = {c.id: CompanyInputs(company=c, snapshots=[], facilities=[]) for c in companies}
    for snap in await session.scalars(
        select(FinancialSnapshot)
        .where(FinancialSnapshot.period_type == PeriodType.MONTHLY)
        .order_by(FinancialSnapshot.period_end)
    ):
        by_id[snap.company_id].snapshots.append(snap)
    facilities = {f.id: f for f in await session.scalars(select(Facility))}
    for f in facilities.values():
        by_id[f.company_id].facilities.append(f)
    for u in await session.scalars(select(FacilityUtilization).order_by(FacilityUtilization.as_of)):
        by_id[facilities[u.facility_id].company_id].utilization.setdefault(
            u.facility_id, []
        ).append(u)
    # Every licence and certificate, whatever its status: `doc_expiries` picks the one in force.
    for d in await session.scalars(select(Document).where(Document.doc_type.in_(EXPIRING_DOCS))):
        by_id[d.company_id].documents.append(d)
    return list(by_id.values())
