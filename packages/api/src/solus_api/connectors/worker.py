"""ARQ worker + dispatch glue (ADR-005: heavy sync work runs as a background
job, never in the request path).

`execute_source_sync` resolves a source's provider, instantiates its connector,
and runs the executor. `run_change_detection` is the scheduled sweep that probes
connected sources and enqueues a sync for any that changed. The ARQ
`WorkerSettings` wires both to Redis; the API enqueues via `dispatch_sync`.
When no Redis is configured (local dev), `dispatch_sync` falls back to an
in-process background task so the app stays functional without a worker.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import AuthKind, Credentials, SyncContext
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry, build_registry
from solus_api.connectors.runtime import _resolve_credentials, run_sync
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore, build_secret_store
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.models import Source, SourceStatus, SyncTrigger

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.connectors.worker")

EnqueueFn = Callable[[uuid.UUID], Awaitable[None]]


async def execute_source_sync(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    source_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
    trigger: SyncTrigger = SyncTrigger.MANUAL,
    acting_user_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Resolve the source's connector and run one sync. Returns the Sync id (or
    None if the source vanished before the run started).

    `acting_user_id` (SOLUSDEV-100 T4b, F3) is the caller-resolved acting user
    for THIS run — the manual `sources.py` trigger endpoint passes the
    requesting user's id. When not supplied (the scheduled/change-detection
    path), this falls back to `source.created_by`; if that is also unset, no
    live acquisition happens for this run (the acquirer declines, logged) —
    resolution is centralized HERE so every caller gets it for free."""
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise ValueError(f"source {source_id} not found")
        provider = source.type.value
        project_id = source.project_id
        team_id = source.team_id
        resolved_acting_user_id = (
            acting_user_id if acting_user_id is not None else source.created_by
        )
    ctx = ConnectorContext(
        project_id=project_id, team_id=team_id, acting_user_id=resolved_acting_user_id
    )
    connector = registry.create_scoped(provider, ctx)
    return await run_sync(
        source_id=source_id,
        sessionmaker=sessionmaker,
        connector=connector,
        secret_store=secret_store,
        trigger=trigger,
        job_id=job_id,
        acting_user_id=resolved_acting_user_id,
    )


async def run_change_detection(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    enqueue: EnqueueFn,
    probe_timeout_seconds: float = 30.0,
) -> int:
    """Probe every connected source; enqueue a sync for each that changed.

    Returns the number enqueued. A probe failure is logged and treated as
    "needs sync" so a transient error never silently stalls a source.

    Phase 4 L4: each `detect_changes` probe runs under its own timeout
    (reusing the C1 `bridge_tool_timeout_seconds` bound by convention — a
    connector's `detect_changes` may itself dispatch a live bridge call) so a
    single stalled probe can never stall the entire sweep; a timeout is
    treated identically to any other probe failure — logged, "needs sync"."""
    async with sessionmaker() as session:
        sources = (
            await session.scalars(select(Source).where(Source.status == SourceStatus.CONNECTED))
        ).all()
        snapshot = [
            (
                s.id,
                s.type.value,
                s.project_id,
                s.team_id,
                s.created_by,
                s.secret_ref,
                dict(s.config),
                dict(s.cursor),
            )
            for s in sources
        ]

    enqueued = 0
    for (
        source_id,
        provider,
        project_id,
        team_id,
        created_by,
        secret_ref,
        config,
        cursor,
    ) in snapshot:
        try:
            # F3: the scheduled/change-detection path falls back to
            # source.created_by (no manual requester exists here) — so a
            # connector's live acquirer (if any) still gets a chance to probe
            # the FRESH export, same fallback rule as the actual sync run.
            connector_ctx = ConnectorContext(
                project_id=project_id, team_id=team_id, acting_user_id=created_by
            )
            connector = registry.create_scoped(provider, connector_ctx)
            if connector.auth_kind is AuthKind.NONE:
                # Committed-export (EDA) connectors carry no tool credential
                # by design (SOLUSDEV-100) — probe with empty credentials
                # instead of skipping, same posture as `runtime.run_sync`.
                credentials = Credentials(token="")
            elif not secret_ref:
                continue
            else:
                # Resolve the REFRESH token too (SOLUS-CAD-01). Without it, every
                # Onshape probe 401s once the 60-minute access token expires, the
                # fail-safe reports "changed", and the sweep enqueues a full export
                # +parse every hour for a document nobody touched.
                credentials = await _resolve_credentials(secret_store, secret_ref)
            ctx = SyncContext(credentials=credentials, config=config, cursor=cursor)
            async with asyncio.timeout(probe_timeout_seconds):
                changed = await connector.detect_changes(ctx)
        except SecretNotFoundError:
            logger.warning("change-detection: no credentials for source=%s", source_id)
            continue
        except Exception:  # noqa: BLE001 — probe failure must not stall the sweep
            logger.exception("change-detection probe failed source=%s", source_id)
            changed = True
        if changed:
            await enqueue(source_id)
            enqueued += 1
    logger.info("change-detection swept %d sources, enqueued %d", len(snapshot), enqueued)
    return enqueued


# --- ARQ wiring (only used when Redis is configured) ---


async def sync_source(
    ctx: dict[str, Any],
    source_id: str,
    job_id: str | None = None,
    acting_user_id: str | None = None,
) -> str:
    """ARQ task: run a sync for one source. `acting_user_id` (SOLUSDEV-100 T4b,
    F3) is the MANUAL trigger's requesting user id, forwarded by
    `routers/sources.py`; the scheduled path (no `job_id`) leaves it unset and
    `execute_source_sync` falls back to `source.created_by`."""
    sync_id = await execute_source_sync(
        sessionmaker=ctx["sessionmaker"],
        registry=ctx["registry"],
        secret_store=ctx["secret_store"],
        source_id=uuid.UUID(source_id),
        job_id=uuid.UUID(job_id) if job_id else None,
        trigger=SyncTrigger.SCHEDULED if job_id is None else SyncTrigger.MANUAL,
        acting_user_id=uuid.UUID(acting_user_id) if acting_user_id else None,
    )
    return str(sync_id) if sync_id is not None else ""


async def scheduled_change_detection(ctx: dict[str, Any]) -> int:
    """ARQ cron: detect changes across all connected sources and enqueue syncs."""
    pool = ctx["redis"]

    async def _enqueue(source_id: uuid.UUID) -> None:
        await pool.enqueue_job("sync_source", str(source_id))

    settings: Settings = ctx["settings"]
    return await run_change_detection(
        sessionmaker=ctx["sessionmaker"],
        registry=ctx["registry"],
        secret_store=ctx["secret_store"],
        enqueue=_enqueue,
        probe_timeout_seconds=settings.bridge_tool_timeout_seconds,
    )


async def sweep_artifacts(ctx: dict[str, Any]) -> int:
    """ARQ cron entrypoint — sweeps TTL-expired artifacts (T4c's
    `services.artifacts.sweep_expired_artifacts`; registration was explicitly
    deferred to T4b — see that function's own docstring)."""
    from solus_api.services.artifacts import sweep_expired_artifacts

    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as session:
        return await sweep_expired_artifacts(
            session, ctx["artifact_store"], ttl_seconds=settings.artifact_ttl_seconds
        )


async def _on_startup(ctx: dict[str, Any]) -> None:
    from solus_api.core.config import Settings
    from solus_api.storage import build_artifact_store

    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["sessionmaker"] = sessionmaker
    # The ARQ process has no bridge session registry (F2: EDA connectors here
    # construct acquirer-less, degrading to the committed-export fallback).
    ctx["registry"] = build_registry(settings)
    ctx["secret_store"] = build_secret_store(settings, sessionmaker)
    ctx["artifact_store"] = build_artifact_store(settings)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


def build_worker_settings(settings: Settings) -> type:
    """Construct the ARQ WorkerSettings class. Imported lazily so the API runs
    without arq/redis present in environments that don't run the worker."""
    from arq import cron
    from arq.connections import RedisSettings

    from solus_api.billing.reconciliation import reconcile_credit_debits

    redis_url = settings.redis_url or "redis://localhost:6379"

    class WorkerSettings:
        # reconcile_credit_debits (SOLUSDEV-83) sweeps the credit dead-letter every
        # minute and is also enqueueable on-demand after an inline debit fails
        # (cost.track_cost enqueues it by name after recording the dead-letter row).
        functions = [sync_source, reconcile_credit_debits]
        cron_jobs = [
            cron(scheduled_change_detection, minute=None, run_at_startup=False),
            cron(reconcile_credit_debits, minute=None, run_at_startup=False),
            # SOLUSDEV-100 T4c built + tested sweep_expired_artifacts; this
            # registration was explicitly deferred to T4b.
            cron(sweep_artifacts, minute=None, run_at_startup=False),
        ]
        on_startup = _on_startup
        on_shutdown = _on_shutdown
        redis_settings = RedisSettings.from_dsn(redis_url)

    return WorkerSettings
