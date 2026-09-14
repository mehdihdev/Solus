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
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import (
    AuthKind,
    ConnectorError,
    Credentials,
)
from solus_api.connectors.httpcache import (
    _KEY_PREFIX,
    CacheStore,
    InMemoryCacheStore,
    RedisCacheStore,
    release_flight,
    run_in_flight,
    single_flight,
)
from solus_api.connectors.registry import (
    ConnectorContext,
    ConnectorRegistry,
    Purpose,
    build_integration_cache,
    build_registry,
)
from solus_api.connectors.runtime import (
    _resolve_credentials,
    connector_error_payload,
    detect_changes_with_refresh,
    retryable_probe_error,
    run_sync,
)
from solus_api.connectors.secrets import SecretStore, build_secret_store
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.graph.live import LiveHub
from solus_api.models import Job, JobStatus, Source, SourceStatus, SyncTrigger, ensure_utc, utcnow
from solus_api.services.connections import account_ref_for, onshape_application_for

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.connectors.worker")

EnqueueFn = Callable[[uuid.UUID], Awaitable[None]]

#: How long one source's sync claim is held before it is assumed dead. Longer
#: than a slow Onshape export (translation + poll + download), short enough that
#: a killed worker does not park the source for an operator's coffee break.
_SYNC_FLIGHT_TTL_SECONDS = 300
#: Supported bounds: one hour of acquired sync work, up to two hours queued.
#: ARQ retries a busy accepted job every 30s; unrelated jobs keep their defaults.
_SYNC_OPERATION_SECONDS = 3600
_SYNC_QUEUE_SECONDS = 7200
_SYNC_DEFER_SECONDS = 30
#: One provider call (120 s) x the gateway's transient retries, plus slack; never retried by
#: ARQ — a retry would be a second billed model call (security review M2).
_SOURCING_JOB_SECONDS = 480
_SYNC_MAX_TRIES = _SYNC_QUEUE_SECONDS // _SYNC_DEFER_SECONDS + 1


#: Sync trigger → scoped-connector purpose (see `registry.Purpose`).
_PURPOSES: dict[SyncTrigger, Purpose] = {
    SyncTrigger.MANUAL: "user",
    SyncTrigger.SCHEDULED: "scheduled",
    SyncTrigger.WEBHOOK: "webhook",
}


async def _await_onshape_write_window(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    project_id: uuid.UUID,
    job_id: uuid.UUID | None,
    *,
    defer_on_busy: bool,
) -> bool:
    """Queued work waits locally or defers through ARQ without touching the provider."""
    from solus_api.models import SourceType
    from solus_api.services.onshape_webhooks import active_write_holds, state_for

    try:
        async with asyncio.timeout(_SYNC_QUEUE_SECONDS):
            while True:
                async with sessionmaker() as session:
                    source = await session.scalar(
                        select(Source).where(
                            Source.id == source_id,
                            Source.project_id == project_id,
                        )
                    )
                    held = (
                        source is not None
                        and source.type == SourceType.ONSHAPE
                        and active_write_holds(state_for(source))
                    )
                if not held:
                    return True
                if defer_on_busy:
                    raise ConnectorError(
                        "single_flight_busy",
                        "CAD reconciliation deferred until active write turns finish",
                    )
                await asyncio.sleep(_SYNC_DEFER_SECONDS)
    except TimeoutError as exc:
        await _fail_accepted_job(sessionmaker, project_id, job_id, connector_error_payload(exc))
        return False
    except asyncio.CancelledError:
        await _fail_accepted_job(
            sessionmaker,
            project_id,
            job_id,
            {
                "code": "sync_cancelled",
                "message": "Synchronization was interrupted; retry later",
            },
        )
        raise


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
    defer_on_busy: bool = False,
    webhook_callback_base: str | None = None,
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
    prevent N of them. A supplied store fails closed when its claim cannot
    be acquired; no caller may proceed unclaimed.

    `acting_user_id` (SOLUSDEV-100 T4b, F3) is the caller-resolved acting user
    for THIS run — the manual `sources.py` trigger endpoint passes the
    requesting user's id. When not supplied (the scheduled/change-detection
    path), this falls back to `source.created_by`; if that is also unset, no
    live acquisition happens for this run (the acquirer declines, logged) —
    resolution is centralized HERE so every caller gets it for free."""
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        if source is None or source.revision_base_source_id is not None:
            raise ValueError(f"source {source_id} not found")
        provider = source.type.value
        project_id = source.project_id
        team_id = source.team_id
        # SOLUSDEV-241: the ONE identity rule for cache keys and the meter.
        account_ref = account_ref_for(source)
        onshape_application = onshape_application_for(source)
        resolved_acting_user_id = (
            acting_user_id if acting_user_id is not None else source.created_by
        )
    if not await _await_onshape_write_window(
        sessionmaker, source_id, project_id, job_id, defer_on_busy=defer_on_busy
    ):
        return None
    ctx = ConnectorContext(
        project_id=project_id,
        team_id=team_id,
        acting_user_id=resolved_acting_user_id,
        account_ref=account_ref,
        onshape_application=onshape_application,
        # Only a human's explicit action keeps spending in the degraded band —
        # and (SOLUSDEV-241) only it trusts a recorded change signal for the
        # full window; the sweep refreshes it, a doorbell never trusts it.
        purpose=_PURPOSES[trigger],
    )
    connector = registry.create_scoped(provider, ctx)
    await _ensure_onshape_subscription(
        sessionmaker, source_id, connector, secret_store, webhook_callback_base, provider
    )

    async def run_owned() -> uuid.UUID | None:
        if not await _await_onshape_write_window(
            sessionmaker, source_id, project_id, job_id, defer_on_busy=defer_on_busy
        ):
            return None
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

    if store is None:
        try:
            async with asyncio.timeout(_SYNC_OPERATION_SECONDS):
                return await run_owned()
        except TimeoutError as exc:
            await _fail_accepted_job(sessionmaker, project_id, job_id, connector_error_payload(exc))
            return None
    flight = f"{_KEY_PREFIX}:sync:{source_id}"
    try:
        async with asyncio.timeout(_SYNC_QUEUE_SECONDS):
            owner = await single_flight(
                store,
                flight,
                ttl_seconds=_SYNC_FLIGHT_TTL_SECONDS,
                wait_seconds=None
                if job_id is not None and not defer_on_busy
                else 0
                if defer_on_busy
                else 30,
            )
    except (ConnectorError, TimeoutError) as exc:
        if defer_on_busy and isinstance(exc, ConnectorError) and exc.code == "single_flight_busy":
            raise
        # No lease means no probe or export. Resolve a caller's accepted Job
        # honestly without modifying a different worker's active Source state.
        await _fail_accepted_job(sessionmaker, project_id, job_id, connector_error_payload(exc))
        return None
    except asyncio.CancelledError:
        await _fail_accepted_job(
            sessionmaker,
            project_id,
            job_id,
            {"code": "sync_cancelled", "message": "Synchronization was interrupted; retry later"},
        )
        raise

    return await _execute_claimed_sync(
        store,
        flight,
        owner,
        run_owned,
        sessionmaker,
        project_id,
        job_id,
        defer_on_busy=defer_on_busy,
    )


async def _execute_claimed_sync(
    store: CacheStore,
    flight: str,
    owner: str,
    run_owned: Callable[[], Awaitable[uuid.UUID | None]],
    sessionmaker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    job_id: uuid.UUID | None,
    *,
    defer_on_busy: bool,
) -> uuid.UUID | None:
    try:
        async with asyncio.timeout(_SYNC_OPERATION_SECONDS):
            return await run_in_flight(
                store, flight, owner, ttl_seconds=_SYNC_FLIGHT_TTL_SECONDS, run=run_owned
            )
    except (ConnectorError, TimeoutError) as exc:
        if defer_on_busy and isinstance(exc, ConnectorError) and exc.code == "single_flight_busy":
            raise
        # Initial renewal can fail before run_sync even starts. Finish that
        # scoped accepted Job too; runtime cancellation closes started runs.
        await _fail_accepted_job(sessionmaker, project_id, job_id, connector_error_payload(exc))
        return None
    except asyncio.CancelledError:
        await _fail_accepted_job(
            sessionmaker,
            project_id,
            job_id,
            {
                "code": "sync_cancelled",
                "message": "Synchronization was interrupted; retry later",
            },
        )
        raise
    finally:
        await release_flight(store, flight, owner)


async def _ensure_onshape_subscription(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    connector: Any,
    secret_store: SecretStore,
    callback_base: str | None,
    provider: str,
) -> None:
    from solus_api.services.onshape_webhooks import public_callback, register_onshape_webhooks

    if provider != "onshape" or callback_base is None:
        return

    try:
        async with sessionmaker() as session:
            source = await session.get(Source, source_id)
            if source is None or source.status != SourceStatus.CONNECTED or not source.secret_ref:
                return
            # Local unavailability requires no credential resolution or vendor request.
            credentials = (
                await _resolve_credentials(secret_store, source.secret_ref)
                if public_callback(callback_base)
                else Credentials(token="")
            )
            async with connector.http(credentials) as client:
                await register_onshape_webhooks(session, source, connector, client, callback_base)
    except Exception:  # noqa: BLE001 — lifecycle cannot destroy ordinary sync diagnostics
        logger.warning("Onshape webhook registration unavailable source=%s", source_id)


async def _fail_accepted_job(
    sessionmaker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    job_id: uuid.UUID | None,
    error: dict[str, str],
) -> None:
    if job_id is None:
        return
    async with sessionmaker() as session:
        job = await session.get(Job, job_id, with_for_update=True)
        if (
            job is not None
            and job.project_id == project_id
            and job.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ):
            job.status = JobStatus.FAILED
            job.error = dict(error)
            await session.commit()


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
    from solus_api.models import SourceType, Sync
    from solus_api.services.onshape_webhooks import acknowledge_state, save_state, state_for

    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        generation = (
            int(state_for(source).get("generation", 0))
            if source is not None and source.type == SourceType.ONSHAPE
            else 0
        )
    sync_id = await run_sync(
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
    if generation and sync_id:
        async with sessionmaker() as session:
            sync = await session.get(Sync, sync_id)
            source = await session.get(Source, source_id, with_for_update=True)
            if source is not None and sync is not None and sync.status == JobStatus.SUCCEEDED:
                save_state(source, acknowledge_state(state_for(source), generation))
                await session.commit()
    return sync_id


#: Per-sweep bounds (SOLUSDEV-167). The sweep is a SAFETY NET under the push
#: producers, not the primary path, so it may be small: a source that misses one
#: sweep is picked up by the next, and a real change arrives by webhook or bridge
#: frame long before either.
_MAX_SOURCES_PER_SWEEP = 500
_MAX_SOURCES_PER_TEAM_PER_SWEEP = 3


def _fair_sweep_query(*eligibility: Any) -> Any:
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
    checked_at = cast(
        Source.config["_onshape_webhook"]["last_checked_at"].as_string(), DateTime(timezone=True)
    )
    fair_time = case(
        (Source.type == "onshape", func.coalesce(checked_at, Source.last_synced_at)),
        else_=Source.last_synced_at,
    )
    ranked = (
        select(
            Source.id.label("id"),
            func.row_number()
            .over(
                partition_by=Source.team_id,
                order_by=(fair_time.nulls_first(), Source.id),
            )
            .label("rank"),
        )
        .where(
            Source.status == SourceStatus.CONNECTED,
            Source.revision_base_source_id.is_(None),
            *eligibility,
        )
        .subquery()
    )
    return (
        select(Source)
        .join(ranked, Source.id == ranked.c.id)
        .where(ranked.c.rank <= _MAX_SOURCES_PER_TEAM_PER_SWEEP)
        .order_by(fair_time.nulls_first(), Source.id)
        .limit(_MAX_SOURCES_PER_SWEEP)
    )


def _onshape_disposition(provider: str, config: dict[str, Any]) -> str:
    from solus_api.connectors.onshape import tracked_document_ids
    from solus_api.services.onshape_webhooks import (
        STATE_KEY,
        dirty,
        healthy_subscription,
        recovery_due,
    )

    if provider != "onshape":
        return "probe"
    state = config.get(STATE_KEY, {})
    if dirty(state):
        return "dirty" if recovery_due(state) else "healthy"
    if healthy_subscription(state, tracked_document_ids(config)):
        return "healthy"
    return "probe"


async def _record_local_check(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
) -> None:
    from solus_api.services.onshape_webhooks import save_state, state_for

    async with sessionmaker() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        if source is not None:
            save_state(source, {**state_for(source), "last_checked_at": utcnow().isoformat()})
            await session.commit()


async def run_change_detection(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    enqueue: EnqueueFn,
    probe_timeout_seconds: float = 30.0,
) -> int:
    """Probe every connected source; enqueue a sync for each that changed.

    Returns the number enqueued. Each probe has a timeout, refreshes expired
    OAuth credentials once, and must return change evidence before enqueueing.
    Retryable failures record an error and remain eligible for the next sweep;
    authentication failures stay visible for reconnection."""
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
                account_ref_for(s),
                onshape_application_for(s),
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
        onshape_application,
    ) in snapshot:
        try:
            disposition = _onshape_disposition(provider, config)
            if disposition == "dirty":
                await enqueue(source_id)
                enqueued += 1
                continue
            if disposition == "healthy":
                await _record_local_check(sessionmaker, source_id)
                continue
            # F3: the scheduled/change-detection path falls back to
            # source.created_by (no manual requester exists here) — so a
            # connector's live acquirer (if any) still gets a chance to probe
            # the FRESH export, same fallback rule as the actual sync run.
            connector_ctx = ConnectorContext(
                project_id=project_id,
                team_id=team_id,
                acting_user_id=created_by,
                account_ref=account_ref,
                onshape_application=onshape_application,
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
            async with asyncio.timeout(probe_timeout_seconds):
                changed, _ = await detect_changes_with_refresh(
                    connector=connector,
                    credentials=credentials,
                    config=config,
                    cursor=cursor,
                    secret_store=secret_store,
                    secret_ref=secret_ref,
                )
        except Exception as exc:  # noqa: BLE001 — isolate one source's failed probe
            logger.warning(
                "change-detection: no signal source=%s code=%s",
                source_id,
                connector_error_payload(exc)["code"],
            )
            async with sessionmaker() as session:
                source = await session.get(Source, source_id, with_for_update=True)
                if source is not None and source.status is SourceStatus.CONNECTED:
                    source.last_error = connector_error_payload(exc)
                    if not retryable_probe_error(exc):
                        source.status = SourceStatus.ERROR
                    await session.commit()
            continue
        if changed:
            await enqueue(source_id)
            enqueued += 1
    logger.info("change-detection swept %d sources, enqueued %d", len(snapshot), enqueued)
    return enqueued


# --- ARQ wiring (only used when Redis is configured) ---


async def _queue_expired(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    job_id: uuid.UUID,
) -> bool:
    async with sessionmaker() as session:
        job = await session.scalar(
            select(Job)
            .join(Source, Source.project_id == Job.project_id)
            .where(Source.id == source_id, Job.id == job_id)
            .with_for_update(of=Job)
        )
        if job is None or utcnow() - ensure_utc(job.created_at) <= timedelta(
            seconds=_SYNC_QUEUE_SECONDS
        ):
            return False
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            job.status = JobStatus.FAILED
            job.error = {
                "code": "sync_queue_timeout",
                "message": "Synchronization waited too long; retry the selection",
            }
            await session.commit()
        return True


async def _queued_sync_trigger(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: str,
    job_id: str | None,
    webhook: bool,
) -> SyncTrigger:
    from solus_api.models import SourceType

    if webhook:
        return SyncTrigger.WEBHOOK
    if job_id is not None:
        return SyncTrigger.MANUAL
    async with sessionmaker() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        # A queued Onshape reconciliation must never trust an old signal cache.
        # This also covers hints arriving after cron queued but before work starts.
        if source is not None and source.type == SourceType.ONSHAPE:
            return SyncTrigger.WEBHOOK
    return SyncTrigger.SCHEDULED


async def sync_source(
    ctx: dict[str, Any],
    source_id: str,
    job_id: str | None = None,
    acting_user_id: str | None = None,
    webhook: bool = False,
) -> str:
    """ARQ task: run a sync for one source. `acting_user_id` (SOLUSDEV-100 T4b,
    F3) is the MANUAL trigger's requesting user id, forwarded by
    `routers/sources.py`; the scheduled path (no `job_id`) leaves it unset and
    `execute_source_sync` falls back to `source.created_by`."""
    from arq import Retry

    if job_id is not None and await _queue_expired(
        ctx["sessionmaker"], uuid.UUID(source_id), uuid.UUID(job_id)
    ):
        return ""
    try:
        sync_id = await execute_source_sync(
            sessionmaker=ctx["sessionmaker"],
            registry=ctx["registry"],
            secret_store=ctx["secret_store"],
            source_id=uuid.UUID(source_id),
            job_id=uuid.UUID(job_id) if job_id else None,
            trigger=await _queued_sync_trigger(ctx["sessionmaker"], source_id, job_id, webhook),
            acting_user_id=uuid.UUID(acting_user_id) if acting_user_id else None,
            store=ctx.get("integration_store"),
            hub=ctx.get("graph_hub"),
            defer_on_busy=True,
            webhook_callback_base=(
                ctx["settings"].public_api_base_url if "settings" in ctx else None
            ),
        )
    except ConnectorError as exc:
        if exc.code != "single_flight_busy":
            raise
        # Keep the persisted Job queued and free this worker slot. The function
        # retry envelope is bounded independently of its acquired work timeout.
        if int(ctx.get("job_try", 1)) >= _SYNC_MAX_TRIES:
            async with ctx["sessionmaker"]() as session:
                source = await session.get(Source, uuid.UUID(source_id))
                project_id = source.project_id if source is not None else None
            if project_id is not None:
                await _fail_accepted_job(
                    ctx["sessionmaker"],
                    project_id,
                    uuid.UUID(job_id) if job_id is not None else None,
                    {
                        "code": "sync_queue_timeout",
                        "message": "Synchronization waited too long; retry the selection",
                    },
                )
            return ""
        raise Retry(defer=_SYNC_DEFER_SECONDS) from exc
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


async def recover_onshape_hints(ctx: dict[str, Any]) -> int:
    """Local-only recovery: queued dirty generations survive restart/enqueue failure."""
    from solus_api.models import SourceType
    from solus_api.services.onshape_webhooks import STATE_KEY, recovery_due, state_for

    async with ctx["sessionmaker"]() as session:
        sources = (
            await session.scalars(
                _fair_sweep_query(
                    Source.type == SourceType.ONSHAPE,
                    func.coalesce(Source.config[STATE_KEY]["generation"].as_integer(), 0)
                    > func.coalesce(Source.config[STATE_KEY]["acknowledged"].as_integer(), 0),
                    or_(
                        Source.config[STATE_KEY]["recover_after"].as_string().is_(None),
                        Source.config[STATE_KEY]["recover_after"].as_string()
                        <= utcnow().isoformat(),
                    ),
                )
            )
        ).all()
        ids = [source.id for source in sources if recovery_due(state_for(source))]
    for source_id in ids:
        await ctx["redis"].enqueue_job(
            "sync_source", str(source_id), _job_id=f"onshape-recovery:{source_id}", webhook=True
        )
    return len(ids)


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


async def source_revision(
    ctx: dict[str, Any], source_id: str, user_id: str, generation: str
) -> None:
    from solus_api.services.source_revisions import acquire_revision

    await acquire_revision(
        sessionmaker=ctx["sessionmaker"],
        registry=ctx["registry"],
        secret_store=ctx["secret_store"],
        source_id=uuid.UUID(source_id),
        user_id=uuid.UUID(user_id),
        generation=uuid.UUID(generation),
        hub=ctx.get("graph_hub"),
    )


async def _on_startup(ctx: dict[str, Any]) -> None:
    from solus_api.core.config import Settings
    from solus_api.storage import build_artifact_store

    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine, settings=settings)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["sessionmaker"] = sessionmaker
    # The ARQ process has no bridge session registry (F2: EDA connectors here
    # construct acquirer-less, degrading to the committed-export fallback).
    # SOLUSDEV-167: the worker runs the UNATTENDED syncs — the ones that can
    # actually run away — so it must share the API's quota ledger rather than
    # silently degrade to an unmetered registry.
    # SOLUSDEV-167. The worker runs the UNATTENDED syncs — the ones that can
    # actually run away — so it must share the API's cache and single-flight
    # store, not silently degrade to an uncoalesced one. `ctx["redis"]` is arq's
    # own ArqRedis, a redis.asyncio.Redis subclass, so no second connection.
    redis = ctx.get("redis")
    ctx["integration_store"] = RedisCacheStore(redis) if redis is not None else InMemoryCacheStore()
    # SOLUSDEV-241: and the read cache over it, handed to the scoped connectors
    # so the sweep's probes REFRESH the signals a human's sync then reads.
    ctx["integration_cache"] = build_integration_cache(settings, ctx["integration_store"])
    ctx["registry"] = build_registry(settings, redis=redis, cache=ctx["integration_cache"])
    ctx["secret_store"] = build_secret_store(settings, sessionmaker)
    ctx["artifact_store"] = build_artifact_store(settings)
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
    from arq import cron, func
    from arq.connections import RedisSettings

    from solus_api.billing.reconciliation import reconcile_credit_debits
    from solus_api.extensions.review import extension_review
    from solus_api.sourcing.worker import sourcing_request

    redis_url = settings.redis_url or "redis://localhost:6379"

    class WorkerSettings:
        # reconcile_credit_debits (SOLUSDEV-83) sweeps the credit dead-letter every
        # minute and is also enqueueable on-demand after an inline debit fails
        # (cost.track_cost enqueues it by name after recording the dead-letter row).
        # extension_review (SOLUSDEV-235 / ADR-035 §5) is enqueued by name from the
        # publish route; it reviews one published bundle and never raises.
        functions = [
            func(source_revision, timeout=200, max_tries=1),
            func(sync_source, timeout=_SYNC_OPERATION_SECONDS + 60, max_tries=_SYNC_MAX_TRIES),
            reconcile_credit_debits,
            extension_review,
            # SOLUSDEV-246 (STORE ST5): one sourcing request → candidates, metered.
            func(sourcing_request, timeout=_SOURCING_JOB_SECONDS, max_tries=1),
        ]
        cron_jobs = [
            # SOLUSDEV-167: was `minute=None`, which in arq means EVERY value —
            # with the default `second=0` that fired once a MINUTE, sweeping
            # every connected source globally. For Onshape that is 2 calls per
            # document per minute against a quota of 2,500 per YEAR. The sweep is
            # now the missed-delivery safety net under the webhook and bridge
            # producers, so hourly is ample.
            cron(scheduled_change_detection, minute={0}, run_at_startup=False),
            cron(recover_onshape_hints, minute=None, run_at_startup=False),
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
