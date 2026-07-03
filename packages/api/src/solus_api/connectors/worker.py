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

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import Credentials, SyncContext
from solus_api.connectors.registry import ConnectorRegistry, build_registry
from solus_api.connectors.runtime import run_sync
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
) -> uuid.UUID | None:
    """Resolve the source's connector and run one sync. Returns the Sync id (or
    None if the source vanished before the run started)."""
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise ValueError(f"source {source_id} not found")
        provider = source.type.value
    connector = registry.create(provider)
    return await run_sync(
        source_id=source_id,
        sessionmaker=sessionmaker,
        connector=connector,
        secret_store=secret_store,
        trigger=trigger,
        job_id=job_id,
    )


async def run_change_detection(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    enqueue: EnqueueFn,
) -> int:
    """Probe every connected source; enqueue a sync for each that changed.

    Returns the number enqueued. A probe failure is logged and treated as
    "needs sync" so a transient error never silently stalls a source."""
    async with sessionmaker() as session:
        sources = (
            await session.scalars(
                select(Source).where(Source.status == SourceStatus.CONNECTED)
            )
        ).all()
        snapshot = [
            (s.id, s.type.value, s.secret_ref, dict(s.config), dict(s.cursor)) for s in sources
        ]

    enqueued = 0
    for source_id, provider, secret_ref, config, cursor in snapshot:
        try:
            if not secret_ref:
                continue
            token = await secret_store.get(secret_ref)
            connector = registry.create(provider)
            ctx = SyncContext(
                credentials=Credentials(token=token), config=config, cursor=cursor
            )
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


async def sync_source(ctx: dict[str, Any], source_id: str, job_id: str | None = None) -> str:
    """ARQ task: run a sync for one source."""
    sync_id = await execute_source_sync(
        sessionmaker=ctx["sessionmaker"],
        registry=ctx["registry"],
        secret_store=ctx["secret_store"],
        source_id=uuid.UUID(source_id),
        job_id=uuid.UUID(job_id) if job_id else None,
        trigger=SyncTrigger.SCHEDULED if job_id is None else SyncTrigger.MANUAL,
    )
    return str(sync_id) if sync_id is not None else ""


async def scheduled_change_detection(ctx: dict[str, Any]) -> int:
    """ARQ cron: detect changes across all connected sources and enqueue syncs."""
    pool = ctx["redis"]

    async def _enqueue(source_id: uuid.UUID) -> None:
        await pool.enqueue_job("sync_source", str(source_id))

    return await run_change_detection(
        sessionmaker=ctx["sessionmaker"],
        registry=ctx["registry"],
        secret_store=ctx["secret_store"],
        enqueue=_enqueue,
    )


async def _on_startup(ctx: dict[str, Any]) -> None:
    from solus_api.core.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["sessionmaker"] = sessionmaker
    ctx["registry"] = build_registry(settings)
    ctx["secret_store"] = build_secret_store(settings, sessionmaker)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


def build_worker_settings(settings: Settings) -> type:
    """Construct the ARQ WorkerSettings class. Imported lazily so the API runs
    without arq/redis present in environments that don't run the worker."""
    from arq import cron
    from arq.connections import RedisSettings

    redis_url = settings.redis_url or "redis://localhost:6379"

    class WorkerSettings:
        functions = [sync_source]
        cron_jobs = [cron(scheduled_change_detection, minute=None, run_at_startup=False)]
        on_startup = _on_startup
        on_shutdown = _on_shutdown
        redis_settings = RedisSettings.from_dsn(redis_url)

    return WorkerSettings
