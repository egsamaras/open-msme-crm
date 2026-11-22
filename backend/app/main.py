from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.routes import accounts, auth, deals, system, tasks
from app.core.config import get_settings
from app.db.session import dispose_engine


def _operation_id(route: APIRoute) -> str:
    # Stable, readable names in the generated TypeScript client.
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Phase 3 opens the LangGraph checkpointer pool here and calls checkpointer.setup().
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Open MSME CRM",
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (system, auth, accounts, deals, tasks):
        app.include_router(module.router)
    return app


app = create_app()
