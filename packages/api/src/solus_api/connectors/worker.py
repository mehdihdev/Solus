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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import (
    NO_SIGNAL_CODES,
    AuthKind,
    ConnectorError,
    Credentials,
    SyncContext,
)
from solus_api.connectors.httpcache import (
    _KEY_PREFIX,
    CacheStore,
    InMemoryCacheStore,
    RedisCacheStore,
    release_flight,
    single_flight,
)
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry, build_registry
from solus_api.connectors.runtime import _resolve_credentials, run_sync
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore, build_secret_store
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.graph.live import LiveHub
from solus_api.models import Source, SourceStatus, SyncTrigger

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.connectors.worker")

EnqueueFn = Callable[[uuid.UUID], Awaitable[None]]

#: How long one source's sync claim is held before it is assumed dead. Longer
#: than a slow Onshape export (translation + poll + download), short enough that
#: a killed worker does not park the source for an operator's coffee break.
_SYNC_FLIGHT_TTL_SECONDS = 300


async def execute_source_sync(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    source_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
    trigger: SyncTrigger = SyncTrigger.MANUAL,
    acting_user_id: uuid.UUID | None = None,
    store: CacheStore | None = None,
    force: bool = False,
    hub: Any | None = None,
) -> uuid.UUID | None:
    """Resolve the source's connector and run one sync. Returns the Sync id (or
    None if the source vanished before the run started).

    SINGLE-FLIGHT (SOLUSDEV-167). Concurrent syncs of one source collapse to one
    upstream pass: the first caller takes a claim and does the work, the rest
    wait for it and then run their own (now cheap) pass, where the freshness gate
    in `run_sync` sees the cursor the winner just wrote and skips. So N
    simultaneous triggers cost one export plus N-1 probes rather than N exports.

    This is the SYNC-level collapse, distinct from the read cache: an export is a
    POST-then-poll dance with no cacheable response, so only coalescing can
    prevent N of them. Fails open — without a store, behaviour is exactly as
    before.

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
        account_ref = source.account_external_id
        resolved_acting_user_id = (
            acting_user_id if acting_user_id is not None else source.created_by
        )
    ctx = ConnectorContext(
        project_id=project_id,
        team_id=team_id,
        acting_user_id=resolved_acting_user_id,
        account_ref=account_ref,
        # A manual trigger carries a job id; the sweep does not. Only a human's
        # explicit action keeps spending in the degraded band.
        purpose="user" if job_id is not None else "scheduled",
    )
    connector = registry.create_scoped(provider, ctx)
    if store is None:
        return await _run(
            connector,
            source_id,
            sessionmaker,
            secret_store,
            trigger,
            job_id,
            resolved_acting_user_id,
            force,
            hub,
        )
    flight = f"{_KEY_PREFIX}:sync:{source_id}"
    await single_flight(store, flight, ttl_seconds=_SYNC_FLIGHT_TTL_SECONDS)
    try:
        return await _run(
            connector,
            source_id,
            sessionmaker,
            secret_store,
            trigger,
            job_id,
            resolved_acting_user_id,
            force,
            hub,
        )
    finally:
        await release_flight(store, flight)


async def _run(
    connector: Any,
    source_id: uuid.UUID,
    sessionmaker: async_sessionmaker[AsyncSession],
    secret_store: SecretStore,
    trigger: SyncTrigger,
    job_id: uuid.UUID | None,
    resolved_acting_user_id: uuid.UUID | None,
    force: bool,
    hub: Any | None,
) -> uuid.UUID | None:
    return await run_sync(
        source_id=source_id,
        sessionmaker=sessionmaker,
        connector=connector,
        secret_store=secret_store,
        trigger=trigger,
        job_id=job_id,
        acting_user_id=resolved_acting_user_id,
        force=force,
        hub=hub,
    )


#: Per-sweep bounds (SOLUSDEV-167). The sweep is a SAFETY NET under the push
#: producers, not the primary path, so it may be small: a source that misses one
#: sweep is picked up by the next, and a real change arrives by webhook or bridge
#: frame long before either.
_MAX_SOURCES_PER_SWEEP = 500
_MAX_SOURCES_PER_TEAM_PER_SWEEP = 3


def _fair_sweep_query() -> Any:
    """Least-recently-synced first, at most N per team, then globally bounded.

    The fairness MUST be in SQL, and getting this wrong is subtle: an earlier
    version applied `LIMIT 500` in SQL and the per-team cap afterwards in Python.
    One tenant with 500+ connected sources then filled the entire snapshot, only
    3 of theirs were probed, and NO other tenant's sources entered the sweep at
    all. Worse, the 497 skipped ones were never synced, so their
    `last_synced_at` stayed NULL and they stayed pinned at the head of
    `NULLS FIRST` on every subsequent run — permanent, self-sustaining starvation
    of every other team, produced by the code meant to prevent it.

    A window function ranks within each team first, so the per-team cap applies
    BEFORE the global limit and every team is represented.
    """
    ranked = (
        select(
            Source.id.label("id"),
            func.row_number()
            .over(
                partition_by=Source.team_id,
                order_by=(Source.last_synced_at.nulls_first(), Source.id),
            )
            .label("rank"),
        )
        .where(Source.status == SourceStatus.CONNECTED)
        .subquery()
    )
    return (
        select(Source)
        .join(ranked, Source.id == ranked.c.id)
        .where(ranked.c.rank <= _MAX_SOURCES_PER_TEAM_PER_SWEEP)
        .order_by(Source.last_synced_at.nulls_first(), Source.id)
        .limit(_MAX_SOURCES_PER_SWEEP)
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
        sources = (await session.scalars(_fair_sweep_query())).all()
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
                s.account_external_id,
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
        account_ref,
    ) in snapshot:
        try:
            # F3: the scheduled/change-detection path falls back to
            # source.created_by (no manual requester exists here) — so a
            # connector's live acquirer (if any) still gets a chance to probe
            # the FRESH export, same fallback rule as the actual sync run.
            connector_ctx = ConnectorContext(
                project_id=project_id,
                team_id=team_id,
                acting_user_id=created_by,
                account_ref=account_ref,
                purpose="scheduled",
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
        except (ConnectorError, TimeoutError) as exc:
            # SOLUSDEV-167: "we could not ask" is not "it changed". A rate-limit,
            # an exhausted quota or a stalled probe used to fall into the generic
            # handler below and enqueue a FULL sync — so being throttled bought
            # more upstream traffic, which is the loop that empties an annual
            # allowance. Skip instead; the next sweep asks again.
            code = "probe_timeout" if isinstance(exc, TimeoutError) else exc.code
            if isinstance(exc, TimeoutError) or code in NO_SIGNAL_CODES:
                logger.warning("change-detection: no signal source=%s reason=%s", source_id, code)
                continue
            logger.warning("change-detection probe failed source=%s code=%s", source_id, code)
            changed = True
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
        store=ctx.get("integration_store"),
        hub=ctx.get("graph_hub"),
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
    # SOLUSDEV-167: the worker runs the UNATTENDED syncs — the ones that can
    # actually run away — so it must share the API's quota ledger rather than
    # silently degrade to an unmetered registry.
    ctx["registry"] = build_registry(settings, redis=ctx.get("redis"))
    ctx["secret_store"] = build_secret_store(settings, sessionmaker)
    ctx["artifact_store"] = build_artifact_store(settings)
    # SOLUSDEV-167. The worker runs the UNATTENDED syncs — the ones that can
    # actually run away — so it must share the API's cache and single-flight
    # store, not silently degrade to an uncoalesced one. `ctx["redis"]` is arq's
    # own ArqRedis, a redis.asyncio.Redis subclass, so no second connection.
    redis = ctx.get("redis")
    ctx["integration_store"] = RedisCacheStore(redis) if redis is not None else InMemoryCacheStore()
    # And the fan-out hub. Without this the ARQ path — which IS the production
    # path whenever Redis is configured, because _dispatch_sync enqueues rather
    # than running inline — published nothing at all, so live propagation worked
    # only in dev's sync_inline mode and in tests calling execute_source_sync
    # directly. Publish-only here: the API tasks hold the subscribers.
    hub = LiveHub(redis)
    await hub.start()
    ctx["graph_hub"] = hub


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    hub = ctx.get("graph_hub")
    if hub is not None:
        await hub.stop()
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


def build_worker_settings(settings: Settings) -> type:
    """Construct the ARQ WorkerSettings class. Imported lazily so the API runs
    without arq/redis present in environments that don't run the worker."""
    from arq import cron
    from arq.connections import RedisSettings

    from solus_api.billing.reconciliation import reconcile_credit_debits
    from solus_api.extensions.review import extension_review

    redis_url = settings.redis_url or "redis://localhost:6379"

    class WorkerSettings:
        # reconcile_credit_debits (SOLUSDEV-83) sweeps the credit dead-letter every
        # minute and is also enqueueable on-demand after an inline debit fails
        # (cost.track_cost enqueues it by name after recording the dead-letter row).
        # extension_review (SOLUSDEV-235 / ADR-035 §5) is enqueued by name from the
        # publish route; it reviews one published bundle and never raises.
        functions = [sync_source, reconcile_credit_debits, extension_review]
        cron_jobs = [
            # SOLUSDEV-167: was `minute=None`, which in arq means EVERY value —
            # with the default `second=0` that fired once a MINUTE, sweeping
            # every connected source globally. For Onshape that is 2 calls per
            # document per minute against a quota of 2,500 per YEAR. The sweep is
            # now the missed-delivery safety net under the webhook and bridge
            # producers, so hourly is ample.
            cron(scheduled_change_detection, minute={0}, run_at_startup=False),
            cron(reconcile_credit_debits, minute=None, run_at_startup=False),
            # SOLUSDEV-100 T4c built + tested sweep_expired_artifacts; this
            # registration was explicitly deferred to T4b.
            cron(sweep_artifacts, minute=None, run_at_startup=False),
        ]
        on_startup = _on_startup
        on_shutdown = _on_shutdown
        redis_settings = RedisSettings.from_dsn(redis_url)
        # Phase 4 H1(5): bound the pool (arq's default is 10). Reviews inflate
        # zip members — CPU-bound work that would otherwise let one flood of
        # publishes crowd out syncs; `extension_review` additionally holds at
        # most 2 slots per publisher (extensions/review.py).
        max_jobs = 4

    return WorkerSettings
