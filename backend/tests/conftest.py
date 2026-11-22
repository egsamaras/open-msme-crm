import os

# Point everything at the test database before the app reads its settings.
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://crm:crm@localhost:5432/crm_test"
)
os.environ["DATABASE_URL"] = TEST_DB
os.environ["CHECKPOINT_DATABASE_URL"] = TEST_DB.replace("+asyncpg", "")
os.environ["ENVIRONMENT"] = "development"
os.environ["LLM_PROVIDER"] = "mock"

import asyncio  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.agents import graphs  # noqa: E402, F401  (registers agent graphs)
from app.agents.checkpointer import close_checkpointer, open_checkpointer  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    """Fresh schema, real migrations, real seed — once per test session."""
    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("DROP SCHEMA IF EXISTS langgraph CASCADE"))
    await engine.dispose()

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DB
    # env.py calls asyncio.run(), which can't nest inside the test loop; run it in a thread.
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with get_sessionmaker()() as session:
        await seed(session)
    # ASGITransport doesn't run the app lifespan, so open the checkpointer here.
    await open_checkpointer(os.environ["CHECKPOINT_DATABASE_URL"])
    yield
    await close_checkpointer()
    await dispose_engine()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c


async def login(client: AsyncClient, email: str, password: str = "demo1234") -> None:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
