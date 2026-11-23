"""Rebuild a database from scratch: drop everything, migrate, seed.

    uv run python -m app.db.reset --yes

Uses DATABASE_URL (and creates that database if it doesn't exist). Deletes all data in it,
including agent runs, approvals and the audit trail, so it refuses to run in production and
needs --yes. Handy before a demo, and the end-to-end tests use it for a clean start.
"""

import argparse
import asyncio
import os
import sys

import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def _plain_url(url: str, database: str | None = None) -> str:
    u = make_url(url).set(drivername="postgresql")
    if database is not None:
        u = u.set(database=database)
    return u.render_as_string(hide_password=False)


async def _recreate(url: str) -> None:
    name = make_url(url).database
    admin = await asyncpg.connect(_plain_url(url, "postgres"))
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(_plain_url(url))
    try:
        await conn.execute(
            "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
            "DROP SCHEMA IF EXISTS langgraph CASCADE; CREATE SCHEMA langgraph;"
        )
    finally:
        await conn.close()


async def _seed() -> int:
    from app.db.seed import seed
    from app.db.session import dispose_engine, get_sessionmaker

    async with get_sessionmaker()() as session:
        n = await seed(session)
    await dispose_engine()
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--yes", action="store_true", help="really delete all data")
    args = parser.parse_args(argv)
    s = get_settings()
    db = make_url(s.database_url).database
    if s.environment == "production":
        print("Refusing to reset a production database.", file=sys.stderr)
        return 2
    if not args.yes:
        print(f"This deletes ALL data in '{db}'. Re-run with --yes.", file=sys.stderr)
        return 1
    asyncio.run(_recreate(s.database_url))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
    cfg.attributes["database_url"] = s.database_url
    command.upgrade(cfg, "head")
    n = asyncio.run(_seed())
    print(f"Reset '{db}': migrated and seeded {n} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
