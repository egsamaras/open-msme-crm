from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.schema_filter import include_name
from app.models import Base


def _diff(connection: Connection) -> list[object]:
    ctx = MigrationContext.configure(
        connection,
        opts={"include_schemas": True, "include_name": include_name, "compare_type": True},
    )
    return list(compare_metadata(ctx, Base.metadata))


async def test_migrations_match_models(session: AsyncSession) -> None:
    """The migrated test database has exactly the schema the models describe."""
    conn = await session.connection()
    assert await conn.run_sync(_diff) == []


def test_alembic_ignores_the_langgraph_schema() -> None:
    assert include_name("langgraph", "schema", {}) is False
    assert include_name("public", "schema", {}) is True
    assert include_name(None, "schema", {}) is True
