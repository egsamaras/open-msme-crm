"""Turn cited record ids into labels and links for the inspection drawer."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Deal, Document, EarlyWarningSignal, Facility, FinancialSnapshot
from app.models.enums import PRODUCT_LABEL
from app.schemas.agents import CitedRecord


async def describe_records(session: AsyncSession, ids: Iterable[uuid.UUID]) -> list[CitedRecord]:
    wanted = set(ids)
    if not wanted:
        return []
    out: dict[uuid.UUID, CitedRecord] = {}

    for c in await session.scalars(select(Company).where(Company.id.in_(wanted))):
        out[c.id] = CitedRecord(
            id=c.id, kind="Account", label=c.trading_name or c.legal_name, href=f"/accounts/{c.id}"
        )
    for f, name in await session.execute(
        select(Facility, Company.trading_name)
        .join(Company, Company.id == Facility.company_id)
        .where(Facility.id.in_(wanted))
    ):
        out[f.id] = CitedRecord(
            id=f.id,
            kind="Facility",
            label=f"{name} · {PRODUCT_LABEL[f.product][:1].upper()}{PRODUCT_LABEL[f.product][1:]}",
            href=f"/accounts/{f.company_id}",
        )
    for s, name in await session.execute(
        select(FinancialSnapshot, Company.trading_name)
        .join(Company, Company.id == FinancialSnapshot.company_id)
        .where(FinancialSnapshot.id.in_(wanted))
    ):
        out[s.id] = CitedRecord(
            id=s.id,
            kind="Financial snapshot",
            label=f"{name} · {s.period_end.strftime('%b %Y')}",
            href=f"/accounts/{s.company_id}",
        )
    for d in await session.scalars(select(Document).where(Document.id.in_(wanted))):
        out[d.id] = CitedRecord(
            id=d.id, kind="Document", label=d.file_name, href=f"/accounts/{d.company_id}"
        )
    for deal in await session.scalars(select(Deal).where(Deal.id.in_(wanted))):
        out[deal.id] = CitedRecord(id=deal.id, kind="Deal", label=deal.title, href="/deals")

    for sig, name in await session.execute(
        select(EarlyWarningSignal, Company.trading_name)
        .join(Company, Company.id == EarlyWarningSignal.company_id)
        .where(EarlyWarningSignal.id.in_(wanted))
    ):
        out[sig.id] = CitedRecord(
            id=sig.id,
            kind="Early-warning signal",
            label=f"{name} · {sig.trigger.value.replace('_', ' ').capitalize()}",
            href="/risk",
        )

    for missing in wanted - out.keys():
        out[missing] = CitedRecord(id=missing, kind="Unknown", label=str(missing), href=None)
    return sorted(out.values(), key=lambda r: (r.kind, r.label))
