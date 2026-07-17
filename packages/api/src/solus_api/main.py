"""App factory. Run with: uvicorn --factory solus_api.main:create_app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from solus_api.agent.fake_systems import FakeSolSystems
from solus_api.agent.runtime import ScaffoldRunner
from solus_api.connectors.registry import build_registry
from solus_api.connectors.secrets import build_secret_store
from solus_api.core.config import Settings
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.core.errors import register_error_handlers
from solus_api.core.ratelimit import RateLimitMiddleware
from solus_api.models import Base
from solus_api.routers import (
    activity,
    billing,
    entities,
    integrations,
    invites,
    jobs,
    members,
    meta,
    notifications,
    orchestration,
    projects,
    sol,
    sources,
    teams,
    users,
)


async def create_all_tables(engine: AsyncEngine) -> None:
    """Create tables from ORM metadata (dev only — production uses migrations).

    The pgvector extension must exist before the embedding columns can be created.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    # Settings' required fields (the JWT secret) come from the environment at
    # runtime; mypy can't see env-driven init, hence the targeted ignore.
    resolved_settings = settings if settings is not None else Settings()  # type: ignore[call-arg]
    resolved_engine = engine if engine is not None else build_engine(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if resolved_settings.auto_create_tables:
            await create_all_tables(resolved_engine)
        yield

    app = FastAPI(
        title="Solus API",
        version=resolved_settings.api_version,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = resolved_engine
    app.state.sessionmaker = build_sessionmaker(resolved_engine)
    # Connector framework (SOLUSDEV-103): one registry + secret store per app.
    app.state.connector_registry = build_registry(resolved_settings)
    app.state.secret_store = build_secret_store(resolved_settings, app.state.sessionmaker)
    # SOL chat seam (SOLUSDEV-135, mock-and-swap): the W0-07 systems impl and the
    # reasoning-loop runner. Swap these for the real systems impl / SOL-01/02 reasoning
    # with a one-line change here and no endpoint edit.
    app.state.sol_systems = FakeSolSystems()
    app.state.agent_runner = ScaffoldRunner()

    register_error_handlers(app)
    # CORS for the Electron renderer / browser dev server (must precede the
    # rate-limit middleware so preflight OPTIONS are answered, not counted).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        RateLimitMiddleware,
        limit_per_minute=resolved_settings.rate_limit_per_minute,
        # MO-04: the classify preview fires on typing pauses — its own generous
        # bucket, never counted against the shared budget.
        path_limits={
            "/api/v1/orchestration/classify": resolved_settings.classify_rate_limit_per_minute
        },
    )

    app.include_router(meta.router)
    app.include_router(users.router)
    app.include_router(notifications.router)
    app.include_router(teams.router)
    app.include_router(members.router)
    app.include_router(invites.team_router)
    app.include_router(invites.accept_router)
    app.include_router(activity.router)
    app.include_router(projects.team_router)
    app.include_router(projects.project_router)
    app.include_router(jobs.router)
    app.include_router(integrations.router)
    app.include_router(billing.router)
    app.include_router(sources.router)
    app.include_router(entities.router)
    app.include_router(sol.router)
    app.include_router(orchestration.router)
    return app
