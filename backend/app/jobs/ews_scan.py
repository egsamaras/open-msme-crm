"""Cron entry point for the early-warning scan: `uv run python -m app.jobs.ews_scan`.

Runs the same graphs as the button, attributed to no user ("system"). Each flagged company's
review stops at its approval, which a person resolves later in the app.
"""

import asyncio

from app.agents import graphs  # noqa: F401  (registers the graphs)
from app.agents.checkpointer import close_checkpointer, open_checkpointer
from app.agents.graphs.ews import drive_scan, start_scan
from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.models import AgentRun


async def main() -> None:
    await open_checkpointer(get_settings().checkpoint_database_url)
    try:
        async with get_sessionmaker()() as session:
            run = await start_scan(session, None)
            await session.commit()
        await drive_scan(run.id)
        async with get_sessionmaker()() as session:
            done = await session.get(AgentRun, run.id)
            assert done is not None
            result = done.result or {}
        print(
            f"Scan {done.status.value}: {result.get('signals_found', 0)} signal(s) found, "
            f"{result.get('new_signals', 0)} new, {len(result.get('reviews', []))} review(s) "
            "waiting for approval."
        )
    finally:
        await close_checkpointer()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
