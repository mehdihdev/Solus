"""App factory. Run with: uvicorn --factory solus_api.main:create_app"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from solus_api.agent.fake_systems import FakeSolSystems
from solus_api.agent.runtime import ScaffoldRunner
from solus_api.bridge.allowlist import load_allowlist
from solus_api.bridge.registry import InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.connectors.mcp_acquire import BridgeExportAcquirer
from solus_api.connectors.registry import AcquirerFactory, ConnectorContext, build_registry
from solus_api.connectors.secrets import build_secret_store
from solus_api.core.config import Settings
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.core.errors import register_error_handlers
from solus_api.core.ratelimit import RateLimitMiddleware
from solus_api.core.security import build_jwks_client
from solus_api.models import Base
from solus_api.routers import (
    activity,
    artifacts,
    billing,
    bridge,
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
from solus_api.services.artifacts import FixedWindowLimiter
from solus_api.services.supabase_admin import build_supabase_admin
from solus_api.storage import build_artifact_store


async def create_all_tables(engine: AsyncEngine) -> None:
    """Create tables from ORM metadata (dev only — production uses migrations).

    The pgvector extension must exist before the embedding columns can be created.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


def _build_bridge_acquirer_factory(app: FastAPI, settings: Settings) -> AcquirerFactory:
    """Closes over `app` (not its `.state` attributes) so this may be built
    and handed to `build_registry` at ANY point during app assembly — the
    factory only reads `app.state.bridge_sessions`/`sessionmaker`/
    `artifact_store` lazily, the first time a sync actually dispatches a live
    export (well after `create_app` returns and every attribute is set)."""

    def _factory(ctx: ConnectorContext, tool_name: str) -> BridgeExportAcquirer:
        return BridgeExportAcquirer(
            sessions=app.state.bridge_sessions,
            sessionmaker=app.state.sessionmaker,
            store=app.state.artifact_store,
            project_id=ctx.project_id,
            team_id=ctx.team_id,
            acting_user_id=ctx.acting_user_id,
            tool_name=tool_name,
            call_cap_bytes=settings.bridge_tool_call_max_bytes,
            artifact_ttl_seconds=settings.artifact_ttl_seconds,
            inline_max_bytes=settings.artifact_inline_max_bytes,
            dispatch_timeout_seconds=settings.bridge_tool_timeout_seconds,
        )

    return _factory


def _scrub_sentry_event(event: Any, _hint: Any) -> Any:
    """§7 (sec review C1): the ASGI integration attaches request data the default
    scrubber misses — `query_string` carries OAuth authorization codes on the
    integration callback routes. Strip the query surface entirely."""
    request = event.get("request") if isinstance(event, dict) else None
    if isinstance(request, dict):
        request.pop("query_string", None)
        url = request.get("url")
        if isinstance(url, str):
            request["url"] = url.split("?", 1)[0]
    return event


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    # Settings' required fields (the JWT secret) come from the environment at
    # runtime; mypy can't see env-driven init, hence the targeted ignore.
    resolved_settings = settings if settings is not None else Settings()  # type: ignore[call-arg]
    resolved_engine = engine if engine is not None else build_engine(resolved_settings.database_url)

    if resolved_settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        # §7: PII, stack-frame locals, request bodies, and query strings stay OUT
        # of Sentry — an OAuth callback's ?code=… must never ride an error event
        # (sec review C1), and ERROR logs must not auto-become events carrying raw
        # exception strings from tools/providers (sec review M1): only deliberate
        # Solus capture_* calls create events; log breadcrumbs remain.
        sentry_sdk.init(
            dsn=resolved_settings.sentry_dsn,
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            before_send=_scrub_sentry_event,
            integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        )

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
    # T4b (MCP-04): the EDA family also gets a bridge export acquirer factory
    # here (the API process HAS a bridge session registry, unlike the ARQ
    # worker — connectors/worker.py's `build_registry` call passes none).
    app.state.connector_registry = build_registry(
        resolved_settings,
        acquirer_factory=_build_bridge_acquirer_factory(app, resolved_settings),
    )
    app.state.secret_store = build_secret_store(resolved_settings, app.state.sessionmaker)
    # Supabase admin (service-role) for account-lifecycle actions (SOLUSDEV-82).
    app.state.supabase_admin = build_supabase_admin(resolved_settings)
    # JWKS client for verifying Supabase's asymmetric (ES256) access tokens
    # (SOLUSDEV-152, ADR-009). None when supabase_url is unset — then only legacy
    # HS256 tokens validate. Keys are cached in-process; the auth path never fetches
    # per request once warm.
    app.state.jwks_client = build_jwks_client(resolved_settings)
    # SOL chat seam (SOLUSDEV-135, mock-and-swap): the W0-07 systems impl and the
    # reasoning-loop runner. Swap these for the real systems impl / SOL-01/02 reasoning
    # with a one-line change here and no endpoint edit.
    app.state.sol_systems = FakeSolSystems()
    app.state.agent_runner = ScaffoldRunner()
    # Local bridge (SOLUSDEV-154): session registry + allowlist + connect limiter.
    # Allowlist root is loaded ONCE at assembly; tests point it at a fixture dir.
    app.state.bridge_sessions = InMemoryBridgeSessionRegistry()
    app.state.bridge_allowlist = load_allowlist(Path(resolved_settings.bridge_allowlist_root))
    app.state.bridge_connect_limiter = ConnectRateLimiter(
        resolved_settings.bridge_connect_rate_per_minute
    )
    # SEC-M1: separate PRE-AUTH per-IP throttle (the per-user one runs post-auth).
    app.state.bridge_ip_connect_limiter = ConnectRateLimiter(
        resolved_settings.bridge_connect_rate_per_minute
    )
    # Artifacts (SOLUSDEV-100 T4c): byte-storage backend (S3 prod / local dev)
    # + the §4.5 upload-route budgets (separate from the global rate limiter).
    app.state.artifact_store = build_artifact_store(resolved_settings)
    app.state.artifact_upload_request_limiter = FixedWindowLimiter(window_seconds=60)
    app.state.artifact_upload_byte_limiter = FixedWindowLimiter(window_seconds=3600)

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
    app.include_router(billing.actions_router)
    app.include_router(sources.router)
    app.include_router(artifacts.router)
    app.include_router(entities.router)
    app.include_router(sol.router)
    app.include_router(bridge.router)
    app.include_router(orchestration.router)
    return app
