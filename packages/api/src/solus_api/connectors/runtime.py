"""Sync executor — runs a connector against a Source and lands the result in
the graph (SOLUSDEV-103). The shared seam every connector flows through.

State persistence: each run creates a Sync record, updates the Source's status
/cursor/last_error, and (when driven by an endpoint) resolves a linked Job.
Graph writes are upserts keyed on (source_id, source_key) so re-syncs update
rather than duplicate, and stale connector-owned entities are reconciled away.

Heavy work runs as a background job (ADR-005), never in the request path —
the API enqueues this; the ARQ worker (and a dev inline fallback) invokes it.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import (
    Connector,
    ConnectorError,
    Credentials,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.secrets import SecretStore
from solus_api.models import (
    Entity,
    Job,
    JobStatus,
    Relation,
    Source,
    SourceStatus,
    Sync,
    SyncTrigger,
    utcnow,
)

logger = logging.getLogger("solus.connectors.runtime")


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

    Entities are upserted by source_key (stale ones deleted); relations are
    diffed by (from, to, type). Returns counts + non-fatal per-item errors.
    """
    counts = _Counts()
    errors: list[dict[str, str]] = [dict(e) for e in _as_error_dicts(result)]

    existing = (
        await session.scalars(select(Entity).where(Entity.source_id == source.id))
    ).all()
    by_key: dict[str, Entity] = {e.source_key: e for e in existing}
    seen: set[str] = set()

    for out in result.entities:
        seen.add(out.source_key)
        row = by_key.get(out.source_key)
        props = dict(out.properties)
        if row is None:
            row = Entity(
                project_id=source.project_id,
                source_id=source.id,
                origin="connector",
                source_key=out.source_key,
                type=out.type,
                domain=out.domain.value,
                name=out.name,
                properties=props,
            )
            session.add(row)
            by_key[out.source_key] = row
            counts.entities_created += 1
        elif (
            row.name != out.name
            or row.type != out.type
            or row.domain != out.domain.value
            or row.properties != props
        ):
            row.name = out.name
            row.type = out.type
            row.domain = out.domain.value
            row.properties = props
            row.version += 1
            counts.entities_updated += 1

    await session.flush()  # assign ids to newly inserted entities
    key_to_id = {key: row.id for key, row in by_key.items() if key in seen}

    await _reconcile_relations(session, source, result, key_to_id, counts, errors)

    stale = [row for key, row in by_key.items() if key not in seen]
    for row in stale:
        await session.delete(row)
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
    counts: _Counts,
    errors: list[dict[str, str]],
) -> None:
    existing_rels = (
        await session.scalars(select(Relation).where(Relation.source_id == source.id))
    ).all()
    existing_map = {(r.from_entity_id, r.to_entity_id, r.type): r for r in existing_rels}

    desired: dict[tuple[uuid.UUID, uuid.UUID, str], dict[str, object]] = {}
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
        desired[(from_id, to_id, rel.type)] = dict(rel.properties)

    for edge, props in desired.items():
        if edge not in existing_map:
            session.add(
                Relation(
                    project_id=source.project_id,
                    source_id=source.id,
                    origin="connector",
                    from_entity_id=edge[0],
                    to_entity_id=edge[1],
                    type=edge[2],
                    properties=props,
                )
            )
            counts.relations_created += 1
    for edge, row in existing_map.items():
        if edge not in desired:
            await session.delete(row)
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
) -> uuid.UUID | None:
    """Run one sync end-to-end. Records a Sync row and returns its id; failures
    are recorded on the Sync/Source/Job (never raised) so the caller's 202 stands
    and the error is answerable from the records (CLAUDE.md §6). Returns None only
    if the source vanished before the run could start (logged, nothing to record)."""
    try:
        sync_id, config, cursor, secret_ref = await _begin_sync(
            sessionmaker, source_id, trigger, job_id
        )
    except Exception:
        logger.exception("sync setup failed for source=%s (deleted before start?)", source_id)
        return None

    try:
        if not secret_ref:
            raise ConnectorError("no_credentials", "Source has no stored credentials")
        token = await secret_store.get(secret_ref)
        ctx = SyncContext(credentials=Credentials(token=token), config=config, cursor=cursor)
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
    code = exc.code if isinstance(exc, ConnectorError) else "sync_error"
    message = exc.message if isinstance(exc, ConnectorError) else str(exc)
    logger.warning("sync failed source=%s sync=%s code=%s: %s", source_id, sync_id, code, message)
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
            source.last_error = {"code": code, "message": message}
        if sync is not None:
            sync.status = JobStatus.FAILED
            sync.errors = [*sync.errors, {"item": "sync", "message": message}]
            sync.finished_at = utcnow()
        await _mark_job(session, job_id, JobStatus.FAILED, error={"code": code, "message": message})
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
        select(func.count()).select_from(Entity).where(Entity.source_id == source_id)
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
        select(Entity.source_id, func.count())
        .where(Entity.source_id.in_(source_ids))
        .group_by(Entity.source_id)
    )
    return {sid: int(count) for sid, count in rows.all() if sid is not None}
