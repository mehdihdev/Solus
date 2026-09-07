"""Sync executor — runs a connector against a Source and lands the result in
the graph (SOLUSDEV-103). The shared seam every connector flows through.

State persistence: each run creates a Sync record, updates the Source's status
/cursor/last_error, and (when driven by an endpoint) resolves a linked Job.
Graph writes are upserts keyed on (source_id, external_ref) so re-syncs update
rather than duplicate, and stale connector-owned rows are soft-deleted (ADR-027
graph-as-living-documentation), never physically removed.

Heavy work runs as a background job (ADR-005), never in the request path —
the API enqueues this; the ARQ worker (and a dev inline fallback) invokes it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import (
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    OAuthConnector,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.graph.live import graph_changed_frame
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    Job,
    JobStatus,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    SyncTrigger,
    utcnow,
)
from solus_api.services.local_links import reconcile_local_links

logger = logging.getLogger("solus.connectors.runtime")

#: Sources whose sync can move a local clone ↔ code-host repo link (SOLUSDEV-249).
_LINKABLE_TYPES: Final = frozenset({SourceType.LOCAL, SourceType.GITHUB, SourceType.GITLAB})

#: Bounds for the persisted, API-visible `last_error` payload (§7 — bound
#: message sizes; a connector/provider error must not round-trip unbounded
#: text into every source list).
ERROR_CODE_MAX = 128
ERROR_MESSAGE_MAX = 1024

#: Shown for non-ConnectorError failures instead of raw exception text, which
#: can echo SQL statements, bound parameters, or ingested content back to the
#: UI (SOLUSDEV-114 security review). The full detail stays in server logs.
INTERNAL_SYNC_ERROR_MESSAGE = "Internal sync error — details are in the server logs."

#: A source whose secret_ref points at nothing (e.g. the token lived in the
#: in-memory dev store and evaporated on restart). Actionable, and it must not
#: echo the opaque ref itself — that's what SecretNotFoundError carries.
MISSING_CREDENTIALS_MESSAGE = (
    "The stored credentials for this source could not be found — "
    "disconnect and reconnect it to store a new token."
)


def connector_error_payload(exc: Exception) -> dict[str, str]:
    """API-safe ``{code, message}`` for a sync/connect failure.

    Connector-authored errors pass through bounded; a vanished stored secret
    gets an actionable message; anything else degrades to a generic message so
    internal exception text never reaches a client.
    """
    if isinstance(exc, ConnectorError):
        return {"code": exc.code[:ERROR_CODE_MAX], "message": exc.message[:ERROR_MESSAGE_MAX]}
    if isinstance(exc, SecretNotFoundError):
        return {"code": "missing_credentials", "message": MISSING_CREDENTIALS_MESSAGE}
    return {"code": "sync_error", "message": INTERNAL_SYNC_ERROR_MESSAGE}


class _Counts:
    __slots__ = (
        "entities_created",
        "entities_deleted",
        "entities_updated",
        "relations_created",
        "relations_deleted",
    )

    def __init__(self) -> None:
        self.entities_created = 0
        self.entities_updated = 0
        self.entities_deleted = 0
        self.relations_created = 0
        self.relations_deleted = 0

    @property
    def changed(self) -> bool:
        """Did this sync actually move the graph? (SOLUSDEV-167)

        `entities_deleted` exists for this verdict. Without it a DELETE-ONLY
        sync leaves every counter at zero and reads as "nothing happened" — so
        the live-propagation publish would be suppressed and a teammate would
        never learn entities were removed.
        """
        return bool(
            self.entities_created
            or self.entities_updated
            or self.entities_deleted
            or self.relations_created
            or self.relations_deleted
        )


async def apply_sync_result(
    session: AsyncSession, source: Source, result: SyncResult
) -> tuple[_Counts, list[dict[str, str]]]:
    """Reconcile a connector's output into the graph for one source.

    Entities are upserted by external_ref (== the connector's source_key); stale
    ones are soft-deleted (ADR-027 living documentation). Relations are diffed by
    (src, dst, type). Returns counts + non-fatal per-item errors.
    """
    counts = _Counts()
    errors: list[dict[str, str]] = [dict(e) for e in _as_error_dicts(result)]

    # Serialize per SOURCE (SOLUSDEV-167). Below is a read-modify-write: SELECT
    # the live rows, then branch insert/update in Python. Two concurrent syncs of
    # one source both SELECT before either commits, both INSERT, and the loser
    # raises UniqueViolationError on uq_graph_entity_source_ref — the partial
    # unique index turns the race into an error, not into correctness.
    # Transaction-scoped, so it releases on commit; different sources and tenants
    # never contend. Same idiom as fingerprint ingestion and the linker, which
    # take the equivalent lock keyed on project.
    # ponytail: a per-row ON CONFLICT upsert is the upgrade if this ever
    # contends; serializing one source's syncs costs nothing today.
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"sync:{source.id}", 0)))
    )

    existing = (
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.source_id == source.id, GraphEntity.deleted_at.is_(None)
            )
        )
    ).all()
    by_key: dict[str, GraphEntity] = {e.external_ref: e for e in existing if e.external_ref}
    seen: set[str] = set()

    for out in result.entities:
        if out.domain.value == "workspace":  # the connector contract's own Domain enum
            # SOLUSDEV-246 ST2 (ADR-027): the workspace layer is Solus-written
            # only; a connector claiming it is refused per item, never landed.
            errors.append(
                {"item": out.source_key, "message": "connectors may not emit the workspace domain"}
            )
            continue
        seen.add(out.source_key)
        row = by_key.get(out.source_key)
        props = dict(out.properties)
        hints = dict(out.modality_hints)  # W0-06 fingerprint channel → its own column
        if row is None:
            row = GraphEntity(
                project_id=source.project_id,
                source_id=source.id,
                source_connector=source.type.value,
                origin="connector",
                external_ref=out.source_key,
                kind=out.type,
                domain=out.domain,
                name=out.name,
                attrs=props,
                modality_hints=hints,
            )
            session.add(row)
            by_key[out.source_key] = row
            counts.entities_created += 1
        elif (
            row.name != out.name
            or row.kind != out.type
            or row.domain != out.domain
            or row.attrs != props
            or row.modality_hints != hints
        ):
            row.name = out.name
            row.kind = out.type
            row.domain = out.domain
            row.attrs = props
            row.modality_hints = hints
            row.version += 1
            counts.entities_updated += 1

    await session.flush()  # assign ids to newly inserted entities
    key_to_id = {key: row.id for key, row in by_key.items() if key in seen}
    key_to_domain = {key: row.domain.value for key, row in by_key.items() if key in seen}

    await _reconcile_relations(session, source, result, key_to_id, key_to_domain, counts, errors)

    # ponytail: soft-deletes THIS source's own stale entities. Cross-source edges
    # (e.g. the fingerprint's same_as links, not built yet) that point at a
    # tombstoned endpoint are not reconciled here — revisit when Feature Area 4
    # starts creating cross-source edges.
    stale = [row for key, row in by_key.items() if key not in seen]
    for row in stale:
        row.deleted_at = utcnow()
        # A tombstone IS a change (SOLUSDEV-167). Without the bump a
        # version-watching consumer sees the row's last live version forever and
        # never learns it was removed.
        row.version += 1
        counts.entities_deleted += 1
    if stale:
        await session.flush()
    return counts, errors


def _as_error_dicts(result: SyncResult) -> list[dict[str, str]]:
    return [{"item": e.item, "message": e.message} for e in result.errors]


async def _reconcile_relations(
    session: AsyncSession,
    source: Source,
    result: SyncResult,
    key_to_id: dict[str, uuid.UUID],
    key_to_domain: dict[str, str],
    counts: _Counts,
    errors: list[dict[str, str]],
) -> None:
    # Only CONNECTOR-origin edges are the sync's to reconcile. A `derived` edge
    # (SOLUSDEV-249: the local clone's `clone_of` link to its code-host repo)
    # sits under the same source_id but is owned by `services/local_links.py`,
    # which reconciles it after every relevant sync — tombstoning it here would
    # churn it on every pass.
    existing_rels = (
        await session.scalars(
            select(GraphEdge).where(
                GraphEdge.source_id == source.id,
                GraphEdge.origin == "connector",
                GraphEdge.deleted_at.is_(None),
            )
        )
    ).all()
    existing_map = {(r.src_id, r.dst_id, r.relation_type): r for r in existing_rels}

    desired: dict[tuple[uuid.UUID, uuid.UUID, str], dict[str, object]] = {}
    domain_pairs: dict[tuple[uuid.UUID, uuid.UUID, str], str] = {}
    for rel in result.relations:
        from_id = key_to_id.get(rel.from_key)
        to_id = key_to_id.get(rel.to_key)
        if from_id is None or to_id is None:
            errors.append(
                {
                    "item": f"{rel.from_key} -> {rel.to_key}",
                    "message": "relation endpoint is not an emitted entity",
                }
            )
            continue
        edge = (from_id, to_id, rel.type)
        desired[edge] = dict(rel.properties)
        # domain_pair is derived from the endpoints' domains at write time (W0-05).
        domain_pairs[edge] = f"{key_to_domain[rel.from_key]}<->{key_to_domain[rel.to_key]}"

    for edge, props in desired.items():
        row = existing_map.get(edge)
        if row is None:
            session.add(
                GraphEdge(
                    project_id=source.project_id,
                    source_id=source.id,
                    origin="connector",
                    src_id=edge[0],
                    dst_id=edge[1],
                    relation_type=edge[2],
                    domain_pair=domain_pairs[edge],
                    confidence=1.0,
                    attrs=props,
                )
            )
            counts.relations_created += 1
        elif row.attrs != props or row.domain_pair != domain_pairs[edge]:
            # Same edge key, but its metadata moved: an endpoint's domain changed
            # (→ domain_pair) or RelationOut.properties changed. Keep it current
            # instead of freezing it at first-write.
            row.attrs = props
            row.domain_pair = domain_pairs[edge]
    for edge, row in existing_map.items():
        if edge not in desired:
            row.deleted_at = utcnow()
            counts.relations_deleted += 1
    await session.flush()


def refresh_secret_ref(secret_ref: str) -> str:
    """The SecretStore ref holding a source's OAuth REFRESH token (SOLUS-CAD-01).

    Derived from the access-token ref so the write (`_complete_oauth`) and the
    reads (here, and the post-refresh re-persist) can never drift — the same
    one-definition rule MCP-05's `license_secret_ref` follows. Sources connected
    before this ticket simply have no such secret; that is not an error.
    """
    return f"{secret_ref}/refresh"


async def resolve_credentials(secret_store: SecretStore, secret_ref: str) -> Credentials:
    """Access token plus, when one was stored, the refresh token."""
    token = await secret_store.get(secret_ref)
    try:
        refresh_token: str | None = await secret_store.get(refresh_secret_ref(secret_ref))
    except SecretNotFoundError:
        refresh_token = None
    return Credentials(token=token, refresh_token=refresh_token)


#: Back-compat alias for the private name this used to carry.
_resolve_credentials = resolve_credentials


async def call_with_refresh[T](
    *,
    connector: Connector,
    credentials: Credentials,
    secret_store: SecretStore,
    secret_ref: str | None,
    run: Callable[[Credentials], Awaitable[T]],
) -> T:
    """Run `run`, refreshing an expired OAuth token at most ONCE and retrying.

    Onshape access tokens live 60 minutes (SOLUS-CAD-01), so `invalid_credentials`
    is an ordinary, expected outcome rather than a user error — for a sync AND
    for any other authenticated connector call (the document/repo picker is the
    other one; a user editing their selection an hour after connecting would
    otherwise just get a 502). The runtime owns persistence because it holds the
    SecretStore; the connector owns the provider-specific refresh call. Bounded
    to a single attempt so a permanently-broken credential can never spin against
    the token endpoint.
    """
    try:
        return await run(credentials)
    except ConnectorError as exc:
        if (
            exc.code != "invalid_credentials"
            or not isinstance(connector, OAuthConnector)
            # The base `refresh_credentials` REFUSES, so calling it would replace
            # the caller's real `invalid_credentials` with a misleading
            # `oauth_refresh_failed`. GitLab already stores a refresh token
            # without having opted in — gate on the override, not the token.
            or type(connector).refresh_credentials is OAuthConnector.refresh_credentials
            or not credentials.refresh_token
            or not secret_ref
        ):
            raise
        logger.info("refreshing expired %s credentials", connector.provider)
        refreshed = await connector.refresh_credentials(credentials)
        # Persist BOTH, REFRESH TOKEN FIRST: providers that rotate the refresh
        # token (Onshape does, on every use) have already invalidated the old
        # one by now. If the second write fails, this ordering leaves a stale
        # access token beside a VALID refresh token — which the next call
        # self-heals. The reverse ordering would strand the source permanently.
        if refreshed.refresh_token:
            await secret_store.put(refresh_secret_ref(secret_ref), refreshed.refresh_token)
        await secret_store.put(secret_ref, refreshed.token)
        return await run(refreshed)


async def _sync_with_refresh(
    *,
    connector: Connector,
    credentials: Credentials,
    config: dict[str, Any],
    cursor: dict[str, Any],
    secret_store: SecretStore,
    secret_ref: str | None,
) -> SyncResult:
    """Run one sync, refreshing an expired OAuth token at most ONCE.

    The refresh-and-retry mechanics are shared with every other authenticated
    connector call (see `call_with_refresh`); this only supplies the sync.
    """
    return await call_with_refresh(
        connector=connector,
        credentials=credentials,
        secret_store=secret_store,
        secret_ref=secret_ref,
        run=lambda creds: connector.sync(
            SyncContext(credentials=creds, config=config, cursor=cursor)
        ),
    )


async def run_sync(
    *,
    source_id: uuid.UUID,
    sessionmaker: async_sessionmaker[AsyncSession],
    connector: Connector,
    secret_store: SecretStore,
    trigger: SyncTrigger = SyncTrigger.MANUAL,
    job_id: uuid.UUID | None = None,
    acting_user_id: uuid.UUID | None = None,
    force: bool = False,
    hub: Any | None = None,
) -> uuid.UUID | None:
    """Run one sync end-to-end. Records a Sync row and returns its id; failures
    are recorded on the Sync/Source/Job (never raised) so the caller's 202 stands
    and the error is answerable from the records (CLAUDE.md §6). Returns None only
    if the source vanished before the run could start (logged, nothing to record).

    `acting_user_id` (SOLUSDEV-100 T4b, F3) is the resolved user whose bridge
    session (if any) an EDA connector's live acquirer may use — resolution
    happens in `worker.execute_source_sync`; this is logged here purely for
    observability ("why did this sync not use live acquisition?" — CLAUDE.md
    §6), since `connector` is already fully constructed by the time it
    reaches `run_sync`.
    """
    try:
        sync_id, config, cursor, secret_ref = await _begin_sync_cancellable(
            sessionmaker, source_id, trigger, job_id
        )
    except Exception:
        logger.exception("sync setup failed for source=%s (deleted before start?)", source_id)
        return None
    logger.info(
        "sync acting_user=%s source=%s sync=%s",
        acting_user_id,
        source_id,
        sync_id,
    )

    probing = False
    try:
        if connector.auth_kind is AuthKind.NONE:
            # Committed-export connectors (EDA family) carry no tool credential
            # by design (SOLUSDEV-100) — sync runs with empty credentials.
            credentials = Credentials(token="")
        elif not secret_ref:
            raise ConnectorError("no_credentials", "Source has no stored credentials")
        else:
            credentials = await _resolve_credentials(secret_store, secret_ref)
        # An auth-none connector normally has no cheap probe (a committed export
        # IS the sync); one that declares `cheap_probe` (SOLUSDEV-249: the local
        # folder's content digest over the bridge) gets the freshness gate too.
        probes = connector.auth_kind is not AuthKind.NONE or bool(
            getattr(connector, "cheap_probe", False)
        )
        if not force and cursor and probes:
            probing = True
            changed, credentials = await detect_changes_with_refresh(
                connector=connector,
                credentials=credentials,
                config=config,
                cursor=cursor,
                secret_store=secret_store,
                secret_ref=secret_ref,
            )
            probing = False
            if not changed:
                await _commit_skipped(sessionmaker, source_id, sync_id, job_id)
                return sync_id
        result = await _sync_with_refresh(
            connector=connector,
            credentials=credentials,
            config=config,
            cursor=cursor,
            secret_store=secret_store,
            secret_ref=secret_ref,
        )
    except asyncio.CancelledError:
        await _record_cancelled_sync(sessionmaker, source_id, sync_id, job_id)
        raise
    except Exception as exc:
        await _record_failure(sessionmaker, source_id, sync_id, job_id, exc, probe=probing)
        return sync_id

    try:
        await _commit_success(sessionmaker, source_id, sync_id, job_id, result, hub)
    except asyncio.CancelledError:
        await _record_cancelled_sync(sessionmaker, source_id, sync_id, job_id)
        raise
    except Exception as exc:  # graph-write failure is still a sync failure
        logger.exception("sync apply failed for source=%s", source_id)
        await _record_failure(sessionmaker, source_id, sync_id, job_id, exc)
    return sync_id


async def _unchanged(
    *,
    connector: Connector,
    credentials: Credentials,
    config: dict[str, object],
    cursor: dict[str, object],
) -> bool:
    """Read the cheap signal; errors propagate without authorizing an export."""
    if not cursor:
        return False  # never synced: there is nothing to compare against
    if connector.auth_kind is AuthKind.NONE:
        # The committed-export (EDA) family has NO cheap signal: its probe is
        # `content_sha` over the FULL export, so `detect_changes` performs the
        # same bridge round-trip / kicad-cli run that `sync()` is about to make.
        # Gating here would HALVE nothing and DOUBLE the changed path. Their
        # saving comes from the sensor upstream (the companion's `change` frame)
        # deciding whether to trigger a sync at all.
        # ponytail: revisit if the export tool ever grows a cheap fingerprint
        # argument — then this branch becomes the same one-call probe as the rest.
        return False
    ctx = SyncContext(credentials=credentials, config=config, cursor=cursor)
    return not await connector.detect_changes(ctx)


async def detect_changes_with_refresh(
    *,
    connector: Connector,
    credentials: Credentials,
    config: dict[str, Any],
    cursor: dict[str, Any],
    secret_store: SecretStore,
    secret_ref: str | None,
) -> tuple[bool, Credentials]:
    """Refresh around the cheap probe and return the credentials it actually used.

    In particular, the following sync must not retry with an already-rotated
    refresh token. All probe errors propagate; absence of evidence never buys
    an export.
    """
    used = credentials

    async def probe(creds: Credentials) -> bool:
        nonlocal used
        used = creds
        return await connector.detect_changes(
            SyncContext(credentials=creds, config=config, cursor=cursor)
        )

    changed = await call_with_refresh(
        connector=connector,
        credentials=credentials,
        secret_store=secret_store,
        secret_ref=secret_ref,
        run=probe,
    )
    return changed, used


def retryable_probe_error(exc: Exception) -> bool:
    """Authentication failures require user action; transport/cache failures defer."""
    return not isinstance(exc, SecretNotFoundError) and not (
        isinstance(exc, ConnectorError)
        and exc.code
        in {
            "invalid_credentials",
            "oauth_refresh_failed",
            "no_credentials",
            "missing_credentials",
            "invalid_config",
            "config_invalid",
            "invalid_repo",
            "invalid_branch",
            "oauth_not_configured",
            "forbidden",
        }
    )


async def _commit_skipped(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
    job_id: uuid.UUID | None,
) -> None:
    """Close out a sync that was not needed.

    This CANNOT be a bare `return` from `run_sync`: `_begin_sync` has already
    committed `Sync.status = RUNNING`, `Source.status = SYNCING` and the Job,
    so returning early would leave the source permanently SYNCING — which 409s
    every manual sync from then on and drops the source out of the change
    sweep, since that selects only CONNECTED. The cursor is deliberately left
    untouched: nothing was read, so there is nothing new to remember.
    """
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        sync = await session.get(Sync, sync_id)
        if source is None or sync is None:
            raise ValueError("source/sync vanished mid-run")
        source.status = SourceStatus.CONNECTED
        source.last_synced_at = utcnow()
        source.last_error = None
        sync.status = JobStatus.SUCCEEDED
        sync.finished_at = utcnow()
        await _mark_job(session, job_id, JobStatus.SUCCEEDED, progress=100)
        await session.commit()
    logger.info("sync skipped (unchanged) source=%s sync=%s", source_id, sync_id)


async def _begin_sync_cancellable(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    trigger: SyncTrigger,
    job_id: uuid.UUID | None,
) -> tuple[uuid.UUID, dict[str, object], dict[str, object], str | None]:
    setup = asyncio.create_task(_begin_sync(sessionmaker, source_id, trigger, job_id))
    try:
        return await asyncio.shield(setup)
    except asyncio.CancelledError:
        # Finish setup before closing its own records: cancellation at commit
        # must not leave an accepted Job/Sync permanently RUNNING.
        try:
            interrupted_id, _, _, _ = await setup
        except Exception:
            logger.exception("sync setup failed during cancellation source=%s", source_id)
        else:
            await _record_cancelled_sync(sessionmaker, source_id, interrupted_id, job_id)
        raise


async def _begin_sync(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    trigger: SyncTrigger,
    job_id: uuid.UUID | None,
) -> tuple[uuid.UUID, dict[str, object], dict[str, object], str | None]:
    async with sessionmaker() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        if source is None:
            raise ValueError(f"source {source_id} not found")
        sync = Sync(
            source_id=source.id,
            project_id=source.project_id,
            job_id=job_id,
            trigger=trigger,
            status=JobStatus.RUNNING,
            started_at=utcnow(),
        )
        source.status = SourceStatus.SYNCING
        session.add(sync)
        await _mark_job(session, job_id, JobStatus.RUNNING)
        await session.commit()
        await session.refresh(sync)
        logger.info("sync started source=%s sync=%s trigger=%s", source_id, sync.id, trigger.value)
        return sync.id, dict(source.config), dict(source.cursor), source.secret_ref


async def _commit_success(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
    job_id: uuid.UUID | None,
    result: SyncResult,
    hub: Any | None = None,
) -> None:
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        sync = await session.get(Sync, sync_id)
        if source is None or sync is None:
            raise ValueError("source/sync vanished mid-run")
        counts, errors = await apply_sync_result(session, source, result)
        source.cursor = dict(result.cursor)
        # SOLUSDEV-249: a local clone's `clone_of` edge to its code-host repo is
        # derived from BOTH sides — reconcile it whenever either side moved.
        if source.type in _LINKABLE_TYPES:
            await reconcile_local_links(session, source.project_id)
        source.last_synced_at = utcnow()
        source.status = SourceStatus.CONNECTED
        source.last_error = None
        sync.status = JobStatus.SUCCEEDED
        sync.entities_created = counts.entities_created
        sync.entities_updated = counts.entities_updated
        sync.relations_created = counts.relations_created
        sync.relations_deleted = counts.relations_deleted
        sync.errors = errors
        sync.finished_at = utcnow()
        await _mark_job(session, job_id, JobStatus.SUCCEEDED, progress=100)
        await session.commit()
        project_id = source.project_id
        logger.info(
            "sync ok source=%s sync=%s created=%d updated=%d rels=+%d/-%d errors=%d",
            source_id,
            sync_id,
            counts.entities_created,
            counts.entities_updated,
            counts.relations_created,
            counts.relations_deleted,
            len(errors),
        )
    # AFTER the commit, and in its own guard (SOLUSDEV-167). Publishing inside
    # the transaction would let a subscriber refetch pre-commit state, and
    # publishing unguarded would be worse: `_commit_success` is called inside
    # `run_sync`'s try/except, so a dead Redis or a closed socket would flip an
    # ALREADY-COMMITTED successful sync to FAILED. Fan-out is never worth a lie
    # about whether the sync worked.
    #
    # Gated on `counts.changed` so a no-op sync does not wake every open session
    # — which is also why `_Counts` had to learn about deletions: a delete-only
    # sync leaves every other counter at zero.
    if hub is not None and counts.changed:
        try:
            await hub.publish(
                project_id,
                graph_changed_frame(
                    project_id=project_id,
                    source_id=source_id,
                    sync_id=sync_id,
                    counts=counts,
                    at=utcnow().isoformat(),
                ),
            )
        except Exception:  # noqa: BLE001 — see above
            logger.exception("graph fan-out failed source=%s (sync stands)", source_id)


async def _record_cancelled_sync(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
    job_id: uuid.UUID | None,
) -> None:
    """Close only this canceled run; never overwrite a successor's source state."""
    error = {"code": "sync_cancelled", "message": "Synchronization was interrupted; retry later"}
    async with sessionmaker() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        sync = await session.get(Sync, sync_id)
        if sync is None or sync.status is not JobStatus.RUNNING:
            return  # a committed successful result remains successful
        sync.status = JobStatus.FAILED
        sync.errors = [*sync.errors, {"item": "sync", "message": error["message"]}]
        sync.finished_at = utcnow()
        await _mark_job(session, job_id, JobStatus.FAILED, error=dict(error))
        latest = await session.scalar(
            select(Sync.id)
            .where(Sync.source_id == source_id)
            .order_by(Sync.created_at.desc(), Sync.id.desc())
            .limit(1)
        )
        if source is not None and latest == sync_id and source.status is SourceStatus.SYNCING:
            source.status = SourceStatus.CONNECTED
            source.last_error = dict(error)
        await session.commit()


async def _record_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
    job_id: uuid.UUID | None,
    exc: Exception,
    *,
    probe: bool = False,
) -> None:
    payload = connector_error_payload(exc)
    # Log the FULL exception text — only the sanitized payload is persisted.
    logger.warning(
        "sync failed source=%s sync=%s code=%s: %s", source_id, sync_id, payload["code"], exc
    )
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        sync = await session.get(Sync, sync_id)
        if source is None or sync is None:
            # The rows vanished mid-run; nothing left to mark. Log loudly so a
            # stuck RUNNING sync is at least traceable (CLAUDE.md §6).
            logger.error(
                "could not record sync failure: source=%s sync=%s missing", source_id, sync_id
            )
        if source is not None:
            source.status = (
                SourceStatus.CONNECTED
                if probe and retryable_probe_error(exc)
                else SourceStatus.ERROR
            )
            source.last_error = dict(payload)
        if sync is not None:
            sync.status = JobStatus.FAILED
            sync.errors = [*sync.errors, {"item": "sync", "message": payload["message"]}]
            sync.finished_at = utcnow()
        await _mark_job(session, job_id, JobStatus.FAILED, error=dict(payload))
        await session.commit()


async def _mark_job(
    session: AsyncSession,
    job_id: uuid.UUID | None,
    status: JobStatus,
    *,
    progress: int | None = None,
    error: dict[str, object] | None = None,
) -> None:
    if job_id is None:
        return
    job = await session.get(Job, job_id)
    if job is None:
        return
    job.status = status
    if progress is not None:
        job.progress = progress
    if error is not None:
        job.error = error
    if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
        job.finished_at = utcnow()


async def source_entity_count(session: AsyncSession, source_id: uuid.UUID) -> int:
    """Total entities a source owns — used in source detail summaries."""
    total = await session.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None))
    )
    return int(total or 0)


async def source_entity_counts(
    session: AsyncSession, source_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Entity counts for many sources in one grouped query (avoids N+1 on the
    source-list endpoint)."""
    if not source_ids:
        return {}
    rows = await session.execute(
        select(GraphEntity.source_id, func.count())
        .where(GraphEntity.source_id.in_(source_ids), GraphEntity.deleted_at.is_(None))
        .group_by(GraphEntity.source_id)
    )
    return {sid: int(count) for sid, count in rows.all() if sid is not None}
