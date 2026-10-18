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
import typing
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, get_args

from sqlalchemy import DateTime, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.billing.stripe_gateway import StripeGateway
from solus_api.connectors.contracts import (
    AuthKind,
    ConnectorError,
    Credentials,
)
from solus_api.connectors.github_app import configure_github_app
from solus_api.connectors.httpcache import (
    _KEY_PREFIX,
    CacheStore,
    InMemoryCacheStore,
    RedisCacheStore,
    release_flight,
    run_in_flight,
    single_flight,
)
from solus_api.connectors.onshape import ambient_settings
from solus_api.connectors.quota import CallLabel
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
from solus_api.storage import ArtifactStore
from solus_api.storage.cad_store import build_cad_store

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


#: Sync trigger -> the label its provider calls are attributed to (ADR-038 §4).
_TRIGGER_LABELS: dict[SyncTrigger, CallLabel] = {
    SyncTrigger.MANUAL: "sync",
    SyncTrigger.SCHEDULED: "sweep",
    SyncTrigger.WEBHOOK: "webhook",
}
_CALL_LABELS: frozenset[str] = frozenset(get_args(CallLabel))

#: ADR-038 §2 quiet period. One stable job id per source: a pending deferred job
#: absorbs every later hint, so a burst of edits queues exactly one sync.
_QUIET_MAX_WAIT_SECONDS = 600
_QUIET_JOB_PREFIX = "onshape-quiet"


def quiet_job_id(source_id: uuid.UUID | str) -> str:
    return f"{_QUIET_JOB_PREFIX}:{source_id}"


def _call_label(value: str | None) -> CallLabel | None:
    """A caller-supplied label, only if it is one the meter knows."""
    return value if value in _CALL_LABELS else None  # type: ignore[return-value]


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
    artifact_store: ArtifactStore | None = None,
    label: CallLabel | None = None,
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
        label=label or _TRIGGER_LABELS[trigger],
    )
    connector = registry.create_scoped(provider, ctx)
    await _ensure_onshape_subscription(
        sessionmaker,
        source_id,
        connector,
        secret_store,
        webhook_callback_base or _ambient_callback_base(provider),
        provider,
    )
    await _mark_webhook_health(sessionmaker, source_id, connector)

    async def run_owned() -> uuid.UUID | None:
        if not await _await_onshape_write_window(
            sessionmaker, source_id, project_id, job_id, defer_on_busy=defer_on_busy
        ):
            return None
        return await _run_with_scene(
            connector,
            source_id,
            sessionmaker,
            secret_store,
            trigger,
            job_id,
            resolved_acting_user_id,
            force,
            hub,
            artifact_store,
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


def _ambient_callback_base(provider: str) -> str | None:
    """The public callback base for paths that pass none (the inline dispatch in
    `routers/sources.py`, the bridge): without this, only the ARQ path ever registered
    webhooks. A non-public base is refused downstream without any provider call."""
    if provider != "onshape":
        return None
    base = getattr(ambient_settings(), "public_api_base_url", None)
    return base if isinstance(base, str) and base else None


async def _mark_webhook_health(
    sessionmaker: async_sessionmaker[AsyncSession], source_id: uuid.UUID, connector: Any
) -> None:
    """Tell the connector whether this source's webhook is verified-healthy, which is what
    lets a recorded `translation.complete` replace status polling."""
    from solus_api.connectors.onshape import OnshapeConnector, tracked_document_ids
    from solus_api.services.onshape_webhooks import healthy_subscription, state_for

    if not isinstance(connector, OnshapeConnector):
        return
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return
        try:
            documents = tracked_document_ids(source.config)
        except ConnectorError:
            return
        connector.webhook_healthy = healthy_subscription(state_for(source), documents)


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
                await register_onshape_webhooks(
                    session,
                    source,
                    connector,
                    client,
                    callback_base,
                    external_session_id=getattr(ambient_settings(), "onshape_session_id", None),
                )
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


async def _run_with_scene(
    connector: Any,
    source_id: uuid.UUID,
    sessionmaker: async_sessionmaker[AsyncSession],
    secret_store: SecretStore,
    trigger: SyncTrigger,
    job_id: uuid.UUID | None,
    resolved_acting_user_id: uuid.UUID | None,
    force: bool,
    hub: Any | None,
    artifact_store: ArtifactStore | None,
) -> uuid.UUID | None:
    from solus_api.connectors.onshape import OnshapeConnector
    from solus_api.livebench.scene.cad_refresh import complete, prepare

    plan = None
    if isinstance(connector, OnshapeConnector):
        async with sessionmaker() as session:
            plan = await prepare(session, source_id)
        connector.scene_export_observer = (
            plan.capture.observe if plan.models or plan.imports else None
        )
    result = await _run(
        connector,
        source_id,
        sessionmaker,
        secret_store,
        trigger,
        job_id,
        resolved_acting_user_id,
        force or (plan.force if plan else False),
        hub,
    )
    if plan is not None:
        await complete(sessionmaker, artifact_store, plan, result, hub)
    return result


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
    """What the sweep does with one source: "probe" (ask the provider), "dirty" (a recorded
    hint is due for recovery), "healthy" (nothing to spend), or "check" (a healthy
    subscription is due its daily one-call-per-subscription confirmation)."""
    from solus_api.connectors.onshape import tracked_document_ids
    from solus_api.services.onshape_webhooks import (
        STATE_KEY,
        dirty,
        healthy_subscription,
        recovery_due,
        subscription_check_due,
    )

    if provider != "onshape":
        return "probe"
    state = config.get(STATE_KEY, {})
    if dirty(state):
        return "dirty" if recovery_due(state) else "healthy"
    if healthy_subscription(state, tracked_document_ids(config)):
        return "check" if subscription_check_due(state, utcnow()) else "healthy"
    return "probe"


async def _record_local_check(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
) -> None:
    from solus_api.services.onshape_webhooks import save_state, state_for

    async with sessionmaker() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        if source is not None:
            state = state_for(source)
            now = utcnow().isoformat()
            # An old healthy state has no daily-check baseline: stamp one, no call.
            state.setdefault("health_checked_at", now)
            save_state(source, {**state, "last_checked_at": now})
            await session.commit()


async def _check_subscription(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    source_id: uuid.UUID,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    created_by: uuid.UUID | None,
    secret_ref: str | None,
    account_ref: str,
    onshape_application: str | None,
    timeout_seconds: float,
) -> None:
    """The bounded daily subscription check. Isolated: a failure here proves nothing about
    the source, so it never touches the source's status or error."""
    from solus_api.connectors.onshape import OnshapeConnector
    from solus_api.services.onshape_webhooks import verify_subscriptions

    if not secret_ref:
        return
    try:
        connector = registry.create_scoped(
            "onshape",
            ConnectorContext(
                project_id=project_id,
                team_id=team_id,
                acting_user_id=created_by,
                account_ref=account_ref,
                onshape_application=onshape_application,
                purpose="scheduled",
                label="sweep",
            ),
        )
        onshape = typing.cast(OnshapeConnector, connector)  # created for provider "onshape"
        credentials = await _resolve_credentials(secret_store, secret_ref)
        async with asyncio.timeout(timeout_seconds), sessionmaker() as session:
            source = await session.get(Source, source_id)
            if source is None or source.status is not SourceStatus.CONNECTED:
                return
            async with onshape.http(credentials) as client:
                await verify_subscriptions(session, source, onshape, client)
    except Exception as exc:  # noqa: BLE001 — a failed check changes nothing
        logger.warning(
            "webhook health check failed source=%s code=%s",
            source_id,
            connector_error_payload(exc)["code"],
        )


async def _settle_without_probe(
    disposition: str,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    enqueue: EnqueueFn,
    row: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID | None, str | None],
    account_ref: str,
    onshape_application: str | None,
    timeout_seconds: float,
) -> int:
    """The sweep outcomes that never probe the provider for changes. Returns 1 when a
    recorded hint was due and a sync was enqueued."""
    source_id, project_id, team_id, created_by, secret_ref = row
    if disposition == "dirty":
        await enqueue(source_id)
        return 1
    if disposition == "healthy":
        await _record_local_check(sessionmaker, source_id)
    elif disposition == "check":
        await _check_subscription(
            sessionmaker=sessionmaker,
            registry=registry,
            secret_store=secret_store,
            source_id=source_id,
            project_id=project_id,
            team_id=team_id,
            created_by=created_by,
            secret_ref=secret_ref,
            account_ref=account_ref,
            onshape_application=onshape_application,
            timeout_seconds=timeout_seconds,
        )
    return 0


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
            if disposition != "probe":
                enqueued += await _settle_without_probe(
                    disposition,
                    sessionmaker=sessionmaker,
                    registry=registry,
                    secret_store=secret_store,
                    enqueue=enqueue,
                    row=(source_id, project_id, team_id, created_by, secret_ref),
                    account_ref=account_ref,
                    onshape_application=onshape_application,
                    timeout_seconds=probe_timeout_seconds,
                )
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
                label="sweep",
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
    from solus_api.services.onshape_webhooks import dirty, state_for

    if webhook:
        return SyncTrigger.WEBHOOK
    if job_id is not None:
        return SyncTrigger.MANUAL
    async with sessionmaker() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        # A hint that arrived after the sweep queued this job but before it runs means
        # "it changed since": never trust a cached signal then. Otherwise the job IS the
        # sweep's own detection, and the signal it just recorded is the evidence to keep;
        # upgrading every queued job threw it away and paid for a second probe.
        if source is not None and source.type == SourceType.ONSHAPE and dirty(state_for(source)):
            return SyncTrigger.WEBHOOK
    return SyncTrigger.SCHEDULED


async def quiet_wait_seconds(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    quiet_seconds: int,
) -> float:
    """Seconds left of a source's quiet period (0 = go). Read from the durable state so
    every worker and every restart agrees; bounded by `_QUIET_MAX_WAIT_SECONDS`."""
    from solus_api.models import SourceType
    from solus_api.services.onshape_webhooks import quiet_remaining, state_for

    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        if source is None or source.type != SourceType.ONSHAPE:
            return 0.0
        return quiet_remaining(
            state_for(source),
            now=utcnow(),
            quiet_seconds=quiet_seconds,
            max_wait_seconds=_QUIET_MAX_WAIT_SECONDS,
        )


def _quiet_period(ctx: dict[str, Any]) -> int:
    from solus_api.services.onshape_webhooks import DEFAULT_QUIET_SECONDS

    settings = ctx.get("settings")
    return int(getattr(settings, "onshape_quiet_period_seconds", DEFAULT_QUIET_SECONDS))


#: In-process quiet tasks (no worker/Redis): at most one pending per source per process.
_INLINE_QUIET: dict[uuid.UUID, asyncio.Task[None]] = {}
_quiet_sleep = asyncio.sleep


def schedule_inline_quiet(
    source_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    quiet_seconds: int,
    run: Callable[[], Awaitable[None]],
) -> bool:
    """The inline-mode twin of the deferred `onshape-quiet` job: the same rule, in-process.
    False when this source already has a task pending (it absorbs the new hint)."""
    pending = _INLINE_QUIET.get(source_id)
    if pending is not None and not pending.done():
        return False

    async def wait_then_run() -> None:
        await _quiet_sleep(quiet_seconds)
        while (wait := await quiet_wait_seconds(sessionmaker, source_id, quiet_seconds)) > 0:
            await _quiet_sleep(wait)
        await run()

    task = asyncio.create_task(wait_then_run())
    _INLINE_QUIET[source_id] = task

    def release(done: asyncio.Task[None]) -> None:
        if _INLINE_QUIET.get(source_id) is done:
            del _INLINE_QUIET[source_id]
        if not done.cancelled() and done.exception() is not None:
            logger.warning("deferred inline sync failed source=%s", source_id)

    task.add_done_callback(release)
    return True


async def sync_source(
    ctx: dict[str, Any],
    source_id: str,
    job_id: str | None = None,
    acting_user_id: str | None = None,
    webhook: bool = False,
    quiet: bool = False,
    label: str | None = None,
) -> str:
    """ARQ task: run a sync for one source. `quiet` (ADR-038 §2) marks a hint-driven job:
    it re-defers itself until the source has been quiet for the configured period (bounded
    by `_QUIET_MAX_WAIT_SECONDS`). A job with a `job_id` is a human's "Sync now" and is
    never delayed. `acting_user_id` (SOLUSDEV-100 T4b,
    F3) is the MANUAL trigger's requesting user id, forwarded by
    `routers/sources.py`; the scheduled path (no `job_id`) leaves it unset and
    `execute_source_sync` falls back to `source.created_by`."""
    from arq import Retry

    if job_id is not None and await _queue_expired(
        ctx["sessionmaker"], uuid.UUID(source_id), uuid.UUID(job_id)
    ):
        return ""
    if quiet and job_id is None:
        wait = await quiet_wait_seconds(
            ctx["sessionmaker"], uuid.UUID(source_id), _quiet_period(ctx)
        )
        if wait > 0:
            raise Retry(defer=wait)
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
            artifact_store=ctx.get("artifact_store"),
            webhook_callback_base=(
                ctx["settings"].public_api_base_url if "settings" in ctx else None
            ),
            label=_call_label(label),
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


async def _enqueue_sweep_hit(ctx: dict[str, Any], source_id: uuid.UUID) -> None:
    """The sweep found a change. For Onshape that is itself a hint: the quiet period applies
    (a deferred job under the per-source id) and `last_hint_at` is recorded WITHOUT a new
    dirty generation, so the signal the sweep just cached stays trusted."""
    from solus_api.models import SourceType
    from solus_api.services.onshape_webhooks import dirty, note_hint, save_state, state_for

    quiet = _quiet_period(ctx)
    async with ctx["sessionmaker"]() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        is_onshape = source is not None and source.type == SourceType.ONSHAPE
        if source is not None and is_onshape and not dirty(state_for(source)):
            save_state(source, note_hint(state_for(source), quiet_seconds=quiet))
            await session.commit()
    if not is_onshape:
        await ctx["redis"].enqueue_job("sync_source", str(source_id))
        return
    await ctx["redis"].enqueue_job(
        "sync_source", str(source_id), _job_id=quiet_job_id(source_id), _defer_by=quiet, quiet=True
    )


async def scheduled_change_detection(ctx: dict[str, Any]) -> int:
    """ARQ cron: detect changes across all connected sources and enqueue syncs."""

    async def _enqueue(source_id: uuid.UUID) -> None:
        await _enqueue_sweep_hit(ctx, source_id)

    settings: Settings = ctx["settings"]
    return await run_change_detection(
        sessionmaker=ctx["sessionmaker"],
        registry=ctx["registry"],
        secret_store=ctx["secret_store"],
        enqueue=_enqueue,
        probe_timeout_seconds=settings.bridge_tool_timeout_seconds,
    )


async def _record_recovery_attempt(
    sessionmaker: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> None:
    from solus_api.services.onshape_webhooks import note_recovery_attempt, save_state, state_for

    async with sessionmaker() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        if source is not None:
            save_state(source, note_recovery_attempt(state_for(source)))
            await session.commit()


async def recover_onshape_hints(ctx: dict[str, Any]) -> int:
    """Local-only recovery: queued dirty generations survive restart/enqueue failure.

    Each source that genuinely gets a job queued backs off exponentially (1 min doubling to
    1 h) until a sync acknowledges it, so a failing source is not re-enqueued every minute.
    The job joins the source's quiet-period queue: a hint-driven job already pending absorbs
    this enqueue and is not counted as a failure."""
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
        queued = await ctx["redis"].enqueue_job(
            "sync_source",
            str(source_id),
            _job_id=quiet_job_id(source_id),
            webhook=True,
            quiet=True,
            label="recovery",
        )
        if queued is not None:
            await _record_recovery_attempt(ctx["sessionmaker"], source_id)
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


async def purge_cad_accounts(ctx: dict[str, Any]) -> int:
    """ARQ cron (every minute and at start): run the durable CAD purge records that are due.

    Revocation queues a record in its own transaction; this is the retry-with-backoff
    that guarantees the objects are eventually deleted (ADR-038 §1), and the delayed
    second pass that catches a sync which was already running at revocation."""
    from solus_api.services.cad_purge import run_due_cad_purges

    async with ctx["sessionmaker"]() as session:
        return await run_due_cad_purges(session, ctx.get("cad_store"))


async def cancel_stripe_subscriptions(ctx: dict[str, Any]) -> int:
    """ARQ cron (every minute and at start): cancel Stripe subscriptions of deleted accounts.

    Drains the durable StripeCancelRequest rows (SOLUSDEV-313); a failing row backs off and is
    retried by the next run. Never raises to ARQ — the rows are the safety net."""
    from solus_api.services.stripe_cancel import run_due_stripe_cancels

    try:
        gateway = ctx.get("stripe_gateway") or StripeGateway(ctx["secret_store"])
        async with ctx["sessionmaker"]() as session:
            summary = await run_due_stripe_cancels(session, gateway)
    except Exception as exc:  # noqa: BLE001 — logged; the durable rows are retried next minute
        # Type name only: DB tracebacks carry bound parameters (customer/subscription ids).
        logger.error("stripe cancel cron failed: %s", type(exc).__name__)
        return 0
    return summary.completed


async def expire_comps(ctx: dict[str, Any]) -> int:
    """ARQ cron (every 15 minutes): clear expired staff comps and notify the users.

    Returns how many subscriptions were reverted; never raises to ARQ."""
    from solus_api.billing.comp_expiry import sweep_expired_comps

    try:
        async with ctx["sessionmaker"]() as session:
            return len(await sweep_expired_comps(session))
    except Exception as exc:  # noqa: BLE001 — logged; the sweep is idempotent and runs again
        logger.error("comp expiry sweep failed: %s", type(exc).__name__)
        return 0


async def prune_github_deliveries(ctx: dict[str, Any]) -> int:
    """ARQ cron (hourly): drop GitHub webhook delivery ids past the retention window.

    Returns how many rows were removed; never raises to ARQ (the next run retries)."""
    from solus_api.services.github_webhook_deliveries import prune_deliveries

    try:
        async with ctx["sessionmaker"]() as session:
            return await prune_deliveries(session)
    except Exception as exc:  # noqa: BLE001 — logged; pruning is idempotent
        logger.error("github delivery prune failed: %s", type(exc).__name__)
        return 0


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
    # The fan-out hub comes first: the sessionmaker carries it so worker COMMITS (syncs, job
    # status) publish live change hints through it (ADR-037 §3).
    # Without this the ARQ path — which IS the production path whenever Redis is configured,
    # because _dispatch_sync enqueues rather than running inline — published nothing at all,
    # so live propagation worked only in dev's sync_inline mode and in tests calling
    # execute_source_sync directly. Publish-only here: the API tasks hold the subscribers.
    redis = ctx.get("redis")
    hub = LiveHub(redis)
    await hub.start()
    ctx["graph_hub"] = hub
    sessionmaker = build_sessionmaker(engine, settings=settings, hub=hub)
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
    ctx["integration_store"] = RedisCacheStore(redis) if redis is not None else InMemoryCacheStore()
    # SOLUSDEV-241: and the read cache over it, handed to the scoped connectors
    # so the sweep's probes REFRESH the signals a human's sync then reads.
    # ADR-038 §1: the same durable CAD store as the API, so a sweep's exports are reused.
    ctx["cad_store"] = build_cad_store(settings)
    logger.info("durable CAD store %s", "enabled" if ctx["cad_store"] is not None else "disabled")
    ctx["integration_cache"] = build_integration_cache(
        settings, ctx["integration_store"], durable=ctx["cad_store"]
    )
    ctx["registry"] = build_registry(settings, redis=redis, cache=ctx["integration_cache"])
    ctx["secret_store"] = build_secret_store(settings, sessionmaker)
    configure_github_app(settings)
    ctx["artifact_store"] = build_artifact_store(settings)


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
            # keep_result=0: arq refuses to enqueue a job id whose RESULT key still exists,
            # so the stable per-source ids (`onshape-quiet:*`) would otherwise drop every
            # hint for an hour after the first sync. Nothing reads sync_source's result.
            func(
                sync_source,
                timeout=_SYNC_OPERATION_SECONDS + 60,
                max_tries=_SYNC_MAX_TRIES,
                keep_result=0,
            ),
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
            # ADR-038 §1: retries the durable CAD purges revocation queued.
            cron(purge_cad_accounts, minute=None, run_at_startup=True),
            # SOLUSDEV-313: durable Stripe cancels for deleted accounts (retry with backoff),
            # and materialising expired staff comps.
            cron(cancel_stripe_subscriptions, minute=None, run_at_startup=True),
            cron(expire_comps, minute={0, 15, 30, 45}, run_at_startup=False),
            # SOLUSDEV-216: GitHub App webhook delivery-id retention.
            cron(prune_github_deliveries, minute={0}, run_at_startup=False),
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
