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

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import (
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.secrets import SecretStore
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    Job,
    JobStatus,
    Source,
    SourceStatus,
    Sync,
    SyncTrigger,
    utcnow,
)

logger = logging.getLogger("solus.connectors.runtime")

#: Bounds for the persisted, API-visible `last_error` payload (§7 — bound
#: message sizes; a connector/provider error must not round-trip unbounded
#: text into every source list).
ERROR_CODE_MAX = 128
ERROR_MESSAGE_MAX = 1024

#: Shown for non-ConnectorError failures instead of raw exception text, which
#: can echo SQL statements, bound parameters, or ingested content back to the
#: UI (SOLUSDEV-114 security review). The full detail stays in server logs.
INTERNAL_SYNC_ERROR_MESSAGE = "Internal sync error — details are in the server logs."


def connector_error_payload(exc: Exception) -> dict[str, str]:
    """API-safe ``{code, message}`` for a sync/connect failure.

    Connector-authored errors pass through bounded; anything else degrades to
    a generic message so internal exception text never reaches a client.
    """
    if isinstance(exc, ConnectorError):
        return {"code": exc.code[:ERROR_CODE_MAX], "message": exc.message[:ERROR_MESSAGE_MAX]}
    return {"code": "sync_error", "message": INTERNAL_SYNC_ERROR_MESSAGE}


class _Counts:
    __slots__ = ("entities_created", "entities_updated", "relations_created", "relations_deleted")

    def __init__(self) -> None:
        self.entities_created = 0
        self.entities_updated = 0
        self.relations_created = 0
        self.relations_deleted = 0


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
    existing_rels = (
        await session.scalars(
            select(GraphEdge).where(
                GraphEdge.source_id == source.id, GraphEdge.deleted_at.is_(None)
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


async def run_sync(
    *,
    source_id: uuid.UUID,
    sessionmaker: async_sessionmaker[AsyncSession],
    connector: Connector,
    secret_store: SecretStore,
    trigger: SyncTrigger = SyncTrigger.MANUAL,
    job_id: uuid.UUID | None = None,
    acting_user_id: uuid.UUID | None = None,
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
        sync_id, config, cursor, secret_ref = await _begin_sync(
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

    try:
        if connector.auth_kind is AuthKind.NONE:
            # Committed-export connectors (EDA family) carry no tool credential
            # by design (SOLUSDEV-100) — sync runs with empty credentials.
            credentials = Credentials(token="")
        elif not secret_ref:
            raise ConnectorError("no_credentials", "Source has no stored credentials")
        else:
            credentials = Credentials(token=await secret_store.get(secret_ref))
        ctx = SyncContext(credentials=credentials, config=config, cursor=cursor)
        result = await connector.sync(ctx)
    except Exception as exc:
        await _record_failure(sessionmaker, source_id, sync_id, job_id, exc)
        return sync_id

    try:
        await _commit_success(sessionmaker, source_id, sync_id, job_id, result)
    except Exception as exc:  # graph-write failure is still a sync failure
        logger.exception("sync apply failed for source=%s", source_id)
        await _record_failure(sessionmaker, source_id, sync_id, job_id, exc)
    return sync_id


async def _begin_sync(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    trigger: SyncTrigger,
    job_id: uuid.UUID | None,
) -> tuple[uuid.UUID, dict[str, object], dict[str, object], str | None]:
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
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
) -> None:
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        sync = await session.get(Sync, sync_id)
        if source is None or sync is None:
            raise ValueError("source/sync vanished mid-run")
        counts, errors = await apply_sync_result(session, source, result)
        source.cursor = dict(result.cursor)
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


async def _record_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
    job_id: uuid.UUID | None,
    exc: Exception,
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
            source.status = SourceStatus.ERROR
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
