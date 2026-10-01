"""App factory. Run with: uvicorn --factory solus_api.main:create_app"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import redis.asyncio as redis_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.perf import SemanticCache
from solus_api.agent.runtime import LlmRunner
from solus_api.bridge.allowlist import load_allowlist
from solus_api.bridge.registry import InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.connectors.httpcache import InMemoryCacheStore, RedisCacheStore
from solus_api.connectors.local_acquire import BridgeFolderAcquirer
from solus_api.connectors.mcp_acquire import BridgeExportAcquirer
from solus_api.connectors.registry import (
    AcquirerFactory,
    ConnectorContext,
    LocalAcquirerFactory,
    build_integration_cache,
    build_registry,
)
from solus_api.connectors.secrets import build_secret_store
from solus_api.core.body_limits import SolMessageBodyLimit
from solus_api.core.config import Settings
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.core.errors import register_error_handlers
from solus_api.core.logging import configure_logging
from solus_api.core.ratelimit import RateLimitMiddleware
from solus_api.core.security import build_jwks_client
from solus_api.core.startup_checks import report_provider_refs
from solus_api.corpus import router as corpus_router
from solus_api.extensions.bom_catalog_setup import prepare_catalog
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.live import LiveHub
from solus_api.graph.live_access import StreamLimiter
from solus_api.graph.resolver import CachingEntityResolver, DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.hardware import hardware_router, library_router
from solus_api.hardware.connections import HardwareConnections
from solus_api.hardware.device_watch import DeviceWatcher, watcher_wanted
from solus_api.livebench.bench_router import BenchEventRing, ObserverEventIn
from solus_api.livebench.bench_router import router as bench_router
from solus_api.livebench.runs.capture import RunCaptureManager
from solus_api.livebench.runs.router import router as bench_runs_router
from solus_api.livebench.scene.router import router as bench_scene_router
from solus_api.livebench.sessions import SessionManager, load_local
from solus_api.models import Base
from solus_api.orchestration.embeddings import build_embed_fn
from solus_api.routers import (
    account_hosted,
    activity,
    artifacts,
    billing,
    bridge,
    code_environment,
    connections,
    entities,
    events,
    extensions,
    hosted,
    integrations,
    invites,
    jobs,
    live,
    local_folder,
    members,
    meta,
    notifications,
    orchestration,
    panel,
    projects,
    simulation_models,
    sol,
    solus_config,
    sources,
    sourcing,
    teams,
    users,
    webhooks,
    widgets,
    workspace_layout,
)
from solus_api.routers.users import PANEL_APPROVALS_PER_MINUTE
from solus_api.services.artifacts import FixedWindowLimiter
from solus_api.services.supabase_admin import build_supabase_admin
from solus_api.storage import build_artifact_store
from solus_api.toolkb import router as toolkb


async def create_all_tables(engine: AsyncEngine) -> None:
    """Create tables from ORM metadata (dev only — production uses migrations).

    The pgvector extension must exist before the embedding columns can be created.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_warn_on_missing_columns)


def _warn_on_missing_columns(conn: Any) -> None:
    """Say so when the dev database is behind the models.

    `create_all` creates missing TABLES and silently does nothing about missing
    COLUMNS on tables that already exist. So a dev database that predates a new
    column boots perfectly and then fails deep inside whichever request first
    touches it — SOLUSDEV-168 lost an evening to exactly that: the app came up
    clean, the FeatureScript enable flow registered its OAuth client, and only
    then died on `oauth_states.code_verifier does not exist`.

    Dev-only and advisory: production runs migrations, and a warning must never
    stop a server booting. Anything unexpected here is swallowed for the same
    reason — a broken drift CHECK must not be worse than the drift.
    """
    from sqlalchemy import inspect as sa_inspect

    try:
        inspector = sa_inspect(conn)
        missing: list[str] = []
        for name, table in Base.metadata.tables.items():
            if not inspector.has_table(name):
                continue
            live = {column["name"] for column in inspector.get_columns(name)}
            missing.extend(f"{name}.{c.name}" for c in table.columns if c.name not in live)
    except Exception:  # noqa: BLE001 — advisory only
        logging.getLogger("solus.main").debug(
            "could not check the dev schema against the models", exc_info=True
        )
        return
    if missing:
        logging.getLogger("solus.main").warning(
            "DEV DATABASE IS BEHIND THE MODELS — %d column(s) missing: %s. "
            "`create_all` cannot add a column to an existing table. "
            "Run `cd packages/api && uv run alembic upgrade head`, or requests "
            "touching these will fail at runtime, not at startup.",
            len(missing),
            ", ".join(sorted(missing)[:12]),
        )


def _build_bridge_acquirer_factory(app: FastAPI, settings: Settings) -> AcquirerFactory:
    """Closes over `app` (not its `.state` attributes) so this may be built
    and handed to `build_registry` at ANY point during app assembly — the
    factory only reads `app.state.bridge_sessions`/`sessionmaker`/
    `artifact_store` lazily, the first time a sync actually dispatches a live
    export (well after `create_app` returns and every attribute is set)."""

    def _factory(ctx: ConnectorContext, tool_name: str) -> BridgeExportAcquirer:
        if ctx.project_id is None or ctx.team_id is None:
            # Live acquisition resolves a companion session by project; an
            # account-scoped context (SOLUSDEV-241) has none to resolve.
            raise ValueError("live export acquisition needs a project-scoped context")
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


def _build_local_acquirer_factory(app: FastAPI, settings: Settings) -> LocalAcquirerFactory:
    """The local-folder twin of `_build_bridge_acquirer_factory` (SOLUSDEV-249):
    reads `app.state.bridge_sessions` lazily, per sync run."""

    def _factory(ctx: ConnectorContext) -> BridgeFolderAcquirer:
        if ctx.project_id is None or ctx.team_id is None:
            raise ValueError("local folder acquisition needs a project-scoped context")
        return BridgeFolderAcquirer(
            sessions=app.state.bridge_sessions,
            project_id=ctx.project_id,
            team_id=ctx.team_id,
            acting_user_id=ctx.acting_user_id,
            call_cap_bytes=settings.bridge_tool_call_max_bytes,
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
    async def lifespan(served: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        if resolved_settings.auto_create_tables:
            await create_all_tables(resolved_engine)
        await prepare_catalog(
            served.state.sessionmaker, served.state.artifact_store, resolved_settings
        )
        # SOLUSDEV-252: name the missing provider refs at boot (never fatal).
        try:
            await report_provider_refs(served.state.secret_store, resolved_settings)
        except Exception:
            logging.getLogger("solus.main").exception("provider ref check failed")
        # SOLUSDEV-167: begin relaying cross-process graph frames. No-op without
        # Redis, in which case the hub still fans out within this process.
        async with AsyncExitStack() as cleanup:
            # Register before startup so partial startup and body failures also
            # release resources. ExitStack still closes later resources if one fails.
            cleanup.push_async_callback(served.state.graph_hub.stop)
            cleanup.push_async_callback(served.state.bench_sessions.aclose_all)
            cleanup.push_async_callback(served.state.bench_runs.aclose)
            cleanup.push_async_callback(served.state.hardware_connections.aclose)
            if served.state.device_watch is not None:
                cleanup.push_async_callback(served.state.device_watch.stop)
            await served.state.graph_hub.start()
            await served.state.hardware_connections.startup()
            if served.state.device_watch is not None:
                await served.state.device_watch.start()
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
    # SOLUSDEV-68 live verification: `/readyz` reported `redis: configured`
    # while nothing ever assigned this, so `check_frequency_cap` always took its
    # `redis is None` fail-open branch — turn-admission rate limiting (§7) was
    # off everywhere and the 429 path was dead code. `from_url` is lazy (no
    # connect at startup) and `redis.asyncio` satisfies the gate's `RedisLike`
    # protocol; a Redis outage still degrades to the gate's existing uniform
    # fail-open, so this adds enforcement without adding a failure mode.
    app.state.redis = (
        # redis.asyncio ships no stubs for from_url; the gate only needs the
        # five sorted-set commands its RedisLike protocol declares.
        redis_asyncio.from_url(resolved_settings.redis_url)  # type: ignore[no-untyped-call]
        if resolved_settings.redis_url
        else None
    )
    # SOLUSDEV-167: the integration cache + single-flight store. Redis when one
    # is configured (shared across processes AND users — two engineers on one
    # Onshape document then cost ONE fetch), otherwise per-process, which
    # coalesces this worker's callers only. Same assembly-time backend choice as
    # the telemetry buffer and the entity resolver below.
    app.state.integration_store = (
        RedisCacheStore(app.state.redis) if app.state.redis is not None else InMemoryCacheStore()
    )
    if app.state.redis is None:
        logging.getLogger("solus.main").warning(
            "integration cache is per-process (no SOLUS_REDIS_URL): concurrent "
            "syncs coalesce within one API process only"
        )
    # SOLUSDEV-241: the read side of the spine — listings, change signals and
    # versioned payloads, keyed on the provider ACCOUNT so projects and
    # teammates on one grant share one fetch. Same store, same backend choice.
    app.state.integration_cache = build_integration_cache(
        resolved_settings, app.state.integration_store
    )
    # SOLUSDEV-167: project-scoped graph-change fan-out. Routing is structural
    # — one channel per project — so a frame's channel, never its body, decides
    # who receives it.
    app.state.graph_hub = LiveHub(app.state.redis)
    # SOLUSDEV-312 (ADR-037): the hub rides every session so committed team/project changes
    # publish themselves (graph/live_publisher.py), and the SSE routes share one stream cap.
    app.state.sessionmaker = build_sessionmaker(
        resolved_engine, settings=resolved_settings, hub=app.state.graph_hub
    )
    app.state.live_stream_limiter = StreamLimiter()
    if app.state.graph_hub.fanout_mode == "local_only":
        logging.getLogger("solus.main").warning(
            "live fan-out is process-local (no SOLUS_REDIS_URL): teammates connected to a "
            "different API process will not receive live updates"
        )
    # Connector framework (SOLUSDEV-103): one registry + secret store per app.
    # T4b (MCP-04): the EDA family also gets a bridge export acquirer factory
    # here (the API process HAS a bridge session registry, unlike the ARQ
    # worker — connectors/worker.py's `build_registry` call passes none).
    app.state.connector_registry = build_registry(
        resolved_settings,
        acquirer_factory=_build_bridge_acquirer_factory(app, resolved_settings),
        local_acquirer_factory=_build_local_acquirer_factory(app, resolved_settings),
        redis=app.state.redis,
        cache=app.state.integration_cache,
    )
    app.state.secret_store = build_secret_store(resolved_settings, app.state.sessionmaker)
    # Supabase admin (service-role) for account-lifecycle actions (SOLUSDEV-82).
    app.state.supabase_admin = build_supabase_admin(resolved_settings)
    # JWKS client for verifying Supabase's asymmetric (ES256) access tokens
    # (SOLUSDEV-152, ADR-009). None when supabase_url is unset — then only legacy
    # HS256 tokens validate. Keys are cached in-process; the auth path never fetches
    # per request once warm.
    app.state.jwks_client = build_jwks_client(resolved_settings)
    # SOLUS-RUN-01: the real model-driven runner. `ScaffoldRunner` stays in
    # runtime.py as the model-free double the transport tests pin (conftest), so
    # the loop guard / timeout / error-masking suites still run with no API key.
    app.state.agent_runner = LlmRunner()
    # Local bridge (SOLUSDEV-154): session registry + allowlist + connect limiter.
    # Allowlist root is loaded ONCE at assembly; tests point it at a fixture dir.
    app.state.bridge_sessions = InMemoryBridgeSessionRegistry()
    app.state.bridge_allowlist = load_allowlist(Path(resolved_settings.bridge_allowlist_root))
    app.state.bridge_connect_limiter = ConnectRateLimiter(
        resolved_settings.bridge_connect_rate_per_minute
    )
    # A7-01: panel pairing approvals, keyed on the authenticated user. Its own
    # bucket so a burst of bridge connects cannot block someone linking a panel.
    app.state.panel_approve_limiter = ConnectRateLimiter(PANEL_APPROVALS_PER_MINUTE)
    # SEC-M1: separate PRE-AUTH per-IP throttle (the per-user one runs post-auth).
    app.state.bridge_ip_connect_limiter = ConnectRateLimiter(
        resolved_settings.bridge_connect_rate_per_minute
    )
    # Live Bench (SOLUSDEV-66 LB-05): the LNK-06 plumbing goes live — bounded
    # in-memory buffer + DB entity resolver + per-project observer-event ring.
    # Redis buffer backend is a one-line swap here when multi-process serving needs it.
    app.state.telemetry_plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(),
        # SOLUSDEV-72: positive-TTL cache — a 50 Hz per-joint stream must not
        # cost one DB query per packet. Negatives are never cached, so a
        # freshly-linked entity attaches on the next packet.
        CachingEntityResolver(DbEntityResolver(app.state.sessionmaker)),
    )
    app.state.bench_events = BenchEventRing()
    # SOLUSDEV-72: bench sessions — the server-side start/stop of local
    # connections. `bench_local` is the OPTIONAL runtime import of
    # livebench.local (never a declared dependency): on a server without
    # livebench it is None and every local source reports honestly unavailable.
    app.state.bench_local = load_local()
    app.state.bench_sessions = SessionManager(
        app.state.telemetry_plumbing,
        observer_factory=getattr(app.state.bench_local, "session_observers", None),
        event_sink=lambda project_id, event: app.state.bench_events.append(
            project_id, ObserverEventIn.model_validate(event)
        ),
    )
    provider_factory = getattr(app.state.bench_local, "presence_provider", None)
    app.state.presence_provider = (
        provider_factory()
        if resolved_settings.app_env == "dev" and callable(provider_factory)
        else None
    )
    app.state.hardware_connections = HardwareConnections(
        sessions=app.state.sessionmaker,
        manager=app.state.bench_sessions,
        local=app.state.bench_local,
        hub=app.state.graph_hub,
    )
    # SOLUSDEV-250: hot-detect — diff the machine's device list at ~1 Hz and push
    # it to subscribed sessions on THIS process only (never Redis).
    # A production API never watches its own host's ports for tenants, even if a future
    # image ships livebench: the watcher exists only for the local runtime.
    app.state.device_watch = (
        DeviceWatcher(app.state.graph_hub, app.state.bench_local)
        if watcher_wanted(resolved_settings.app_env, app.state.bench_local)
        else None
    )
    # SYS-04 (SOLUSDEV-138): SOL answers from the REAL W0-07 feeds — graph,
    # telemetry buffer, SYS-02 retrieval — never from canned fixtures. Sits after
    # the telemetry plumbing it wraps. Embeds at this seam are unmetered by
    # decision (ADR-018 ambient posture; volume is bounded by the metered,
    # frequency-capped turn admission) and degrade loudly to full-text retrieval
    # while `openai_api_key` is unseeded.
    app.state.sol_systems = DbSolSystems(
        app.state.sessionmaker,
        app.state.telemetry_plumbing,
        embed=build_embed_fn(app.state.secret_store, allow_unmetered=True),
        # SYS-05: TTL'd semantic cache over the retrieval feeds (hit-rate logged).
        cache=SemanticCache(),
    )
    # CORPUS C2 (ADR-036): the corpus is pulled through this same DbSolSystems
    # (rag_query source_type "corpus"); the HTTP search route is full-text only.
    # Artifacts (SOLUSDEV-100 T4c): byte-storage backend (S3 prod / local dev)
    # + the §4.5 upload-route budgets (separate from the global rate limiter).
    app.state.artifact_store = build_artifact_store(resolved_settings)
    app.state.bench_runs = RunCaptureManager(
        app.state.sessionmaker, app.state.artifact_store, app.state.bench_sessions
    )
    app.state.telemetry_plumbing.capture_sink = app.state.bench_runs.ingest
    # SOLUSDEV-167: per-source webhook delivery budget, in DAYS. One delivery
    # schedules a sync whose probe loops per tracked document, so a per-minute
    # window could authorise hundreds of upstream calls a minute against an
    # allowance of 2,500 a YEAR. See WEBHOOK_DELIVERIES_PER_DAY for the
    # arithmetic. ponytail: per-process like every FixedWindowLimiter here, so
    # the real ceiling is budget x instances — a shared Redis counter is the
    # upgrade, and the quota meter is the backstop underneath either way.
    app.state.webhook_limiter = FixedWindowLimiter(window_seconds=86_400)
    app.state.artifact_upload_request_limiter = FixedWindowLimiter(window_seconds=60)
    app.state.artifact_upload_byte_limiter = FixedWindowLimiter(window_seconds=3600)

    register_error_handlers(app)
    # SOLUSDEV-252 review M1: innermost, so a 411/413 still carries CORS headers
    # and counts against the write budget like any other rejected write.
    app.add_middleware(SolMessageBodyLimit)
    # Starlette wraps each add_middleware around the previous, so the LAST one
    # added is outermost. The limiter goes first so CORS ends up outside it:
    # preflight OPTIONS are answered by CORS, never counted, and a 429 still
    # carries the CORS headers the renderer needs to read `rate_limited`
    # (SOLUSDEV-234 — the old order had these backwards).
    app.add_middleware(
        RateLimitMiddleware,
        limit_per_minute=resolved_settings.rate_limit_per_minute,
        write_limit_per_minute=resolved_settings.write_rate_limit_per_minute,
        # MO-04: the classify preview fires on typing pauses — its own generous
        # bucket, never counted against the shared budget.
        path_limits={
            "/api/v1/orchestration/classify": resolved_settings.classify_rate_limit_per_minute,
            # A7-01: unauthenticated, and behind the ALB every caller shares one
            # bucket (core/ratelimit sees the LB's IP), so it gets its own rather
            # than eating the shared budget every panel load.
            "/api/v1/panel/pair/start": resolved_settings.panel_pair_rate_limit_per_minute,
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(meta.router)
    app.include_router(users.router)
    app.include_router(notifications.router)
    app.include_router(events.router)
    app.include_router(teams.router)
    app.include_router(members.router)
    app.include_router(invites.team_router)
    app.include_router(invites.accept_router)
    app.include_router(activity.router)
    app.include_router(projects.team_router)
    app.include_router(projects.project_router)
    app.include_router(jobs.router)
    app.include_router(integrations.router)
    app.include_router(connections.router)
    app.include_router(billing.router)
    app.include_router(billing.actions_router)
    from solus_api.routers import source_revisions

    app.include_router(source_revisions.router)
    app.include_router(sources.router)
    app.include_router(local_folder.router)
    app.include_router(code_environment.router)
    app.include_router(hosted.router)
    app.include_router(account_hosted.router)
    app.include_router(artifacts.router)
    app.include_router(solus_config.router)
    app.include_router(hardware_router.router)
    app.include_router(library_router.router)
    app.include_router(workspace_layout.router)
    app.include_router(entities.router)
    app.include_router(simulation_models.router)
    from solus_api.routers import isaac_connection

    app.include_router(isaac_connection.router)
    app.include_router(sol.router)
    from solus_api.livebench.stream import router as bench_stream_router

    app.include_router(bench_stream_router)
    app.include_router(bench_router)
    app.include_router(bench_runs_router)
    app.include_router(bench_scene_router)
    app.include_router(bridge.router)
    app.include_router(orchestration.router)
    app.include_router(panel.router)
    app.include_router(toolkb.router)
    app.include_router(corpus_router.router)
    app.include_router(webhooks.router)
    app.include_router(live.router)
    app.include_router(live.account_router)
    # SOLUSDEV-235: the extensions aggregator (catalog, publishing, installs,
    # storage, layout, policy sub-routers mount onto it as the EXT tasks land).
    app.include_router(extensions.router)
    # SOLUSDEV-246: first-party bundle capability routes (widget-bundles.md §3).
    app.include_router(widgets.router)
    app.include_router(sourcing.router)
    return app
