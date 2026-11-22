import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import seed
from app.models import AuditEvent, Company, FacilityUtilization, FinancialSnapshot
from app.services import audit


async def test_chain_verifies_after_appends(session: AsyncSession) -> None:
    for i in range(3):
        await audit.record(
            session,
            action="test.event",
            entity_type="test",
            entity_id=str(i),
            payload={"n": i, "amount": "12.50"},
        )
    await session.commit()
    result = await audit.verify_chain(session)
    assert result.ok
    assert result.events_checked >= 3


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'x'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
async def test_audit_events_are_append_only(session: AsyncSession, statement: str) -> None:
    await audit.record(session, action="test.event", entity_type="test")
    await session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text(statement))
    await session.rollback()


async def test_verify_detects_tampering(session: AsyncSession) -> None:
    """Bypass the trigger (as the table owner would have to) and check the chain catches it."""
    await audit.record(session, action="test.event", entity_type="test", payload={"v": 1})
    await session.commit()
    try:
        await session.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        await session.execute(
            text(
                "UPDATE audit_events SET payload = '{\"v\": 2}' "
                "WHERE seq = (SELECT max(seq) FROM audit_events)"
            )
        )
        result = await audit.verify_chain(session)
        assert not result.ok
        assert result.first_bad_seq is not None
    finally:
        await session.rollback()  # undoes the tamper and re-enables the trigger
    assert (await audit.verify_chain(session)).ok


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    async def counts() -> tuple[int | None, ...]:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (Company, FinancialSnapshot, FacilityUtilization, AuditEvent)
            ]
        )

    before = await counts()
    await seed(session)
    assert await counts() == before
