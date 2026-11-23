"""LangGraph checkpointer on Postgres, in its own `langgraph` schema (SPEC 3).

psycopg 3 (not asyncpg) with autocommit, no prepared statements and dict rows, as
langgraph-checkpoint-postgres requires. Opened once in the FastAPI lifespan.
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA = "langgraph"

_pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
_saver: AsyncPostgresSaver | None = None


async def open_checkpointer(conninfo: str) -> AsyncPostgresSaver:
    global _pool, _saver
    if _saver is not None:
        return _saver
    # Make sure the schema exists before the pool pins search_path to it.
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={SCHEMA}",
        },
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    _pool, _saver = pool, saver
    return saver


def get_checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("Checkpointer not opened; it is opened in the FastAPI lifespan")
    return _saver


async def close_checkpointer() -> None:
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool, _saver = None, None
