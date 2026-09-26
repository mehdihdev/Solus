"""Project-scoped durable run records, checkpoint artifacts and final .solus filing."""

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.livebench.runs.models import RunManifest, RunSummary, encode_manifest, parse_manifest
from solus_api.models import Artifact, Domain, GraphEntity, SolusSection, utcnow
from solus_api.services.artifacts import create_artifact, fetch_artifact_bytes
from solus_api.services.solus_config import add_artifact_entry
from solus_api.storage import ArtifactStore

RUN_KIND = "bench_run"
logger = logging.getLogger(__name__)


async def record(
    session: AsyncSession, project_id: UUID, run_id: UUID, *, lock: bool = False
) -> GraphEntity:
    query = select(GraphEntity).where(
        GraphEntity.project_id == project_id,
        GraphEntity.id == run_id,
        GraphEntity.kind == RUN_KIND,
        GraphEntity.origin == "system",
        GraphEntity.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    entity = await session.scalar(query)
    if entity is None:
        raise APIError(404, "not_found", "Run not found")
    return entity


def summary(entity: GraphEntity) -> RunSummary:
    return RunSummary.model_validate(entity.attrs["summary"])


async def save(
    session: AsyncSession,
    store: ArtifactStore,
    entity: GraphEntity,
    info: RunSummary,
    manifest: RunManifest,
    user_id: UUID,
    *,
    final: bool,
) -> None:
    if manifest.sensors:
        ids = {sensor.artifact_id for sensor in manifest.sensors}
        sensors = list(
            await session.scalars(
                select(Artifact)
                .where(
                    Artifact.id.in_(ids),
                    Artifact.project_id == entity.project_id,
                    Artifact.deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        if {sensor.id for sensor in sensors} != ids:
            raise APIError(404, "not_found", "Sensor artifact not found")
        for sensor in sensors:
            sensor.retained = True
    data = await asyncio.to_thread(encode_manifest, manifest)
    artifact = await create_artifact(
        session,
        store,
        project_id=entity.project_id,
        created_by=user_id,
        data=data,
        media_type="application/vnd.solus.bench-run+json",
        source_tool="bench.capture",
        tool_call_id=None,
    )
    # Interrupted runs must survive the transient-artifact TTL as well.
    artifact.retained = True
    old_id = entity.attrs.get("checkpoint_id")
    info.packet_count = len(manifest.packets)
    if final:
        await add_artifact_entry(
            session,
            entity.project_id,
            SolusSection.DOCS,
            artifact_id=artifact.id,
            name=f"{info.name}.bench-run.json",
            created_by=user_id,
        )
        info.artifact_id = artifact.id
    entity.attrs = {
        "summary": info.model_dump(mode="json"),
        "checkpoint_id": str(artifact.id),
        "created_by": str(user_id),
    }
    if old_id:
        old = await session.scalar(
            select(Artifact).where(
                Artifact.id == UUID(old_id), Artifact.project_id == entity.project_id
            )
        )
        if old is not None:
            old.retained = False
            old.deleted_at = utcnow()
    await session.commit()
    logger.info(
        "run persisted project=%s run=%s status=%s packets=%s",
        entity.project_id,
        entity.id,
        info.status,
        info.packet_count,
    )
    if old_id:
        # DB now points at the new durable bytes. Cleanup failure must not
        # unwind a committed checkpoint or accidentally repeat an action.
        try:
            await store.delete(old_id)
        except Exception:
            logger.warning("old run checkpoint cleanup failed: run=%s", entity.id)


async def load(
    session: AsyncSession,
    store: ArtifactStore,
    entity: GraphEntity,
    user_id: UUID,
    ttl_seconds: int,
) -> RunManifest:
    checkpoint = entity.attrs.get("checkpoint_id")
    if not checkpoint:
        raise APIError(
            409, "checkpoint_unavailable", "No persisted capture checkpoint is available"
        )
    _, data = await fetch_artifact_bytes(
        session,
        store,
        project_id=entity.project_id,
        artifact_id=UUID(checkpoint),
        requester_id=user_id,
        ttl_seconds=ttl_seconds,
        max_bytes=8 * 1024 * 1024,
    )
    return await asyncio.to_thread(parse_manifest, data)


def new_record(project_id: UUID, info: RunSummary, user_id: UUID) -> GraphEntity:
    return GraphEntity(
        id=info.id,
        project_id=project_id,
        kind=RUN_KIND,
        domain=Domain.PROJECT,
        origin="system",
        name=info.name,
        attrs={"summary": info.model_dump(mode="json"), "created_by": str(user_id)},
    )


def detail(info: RunSummary, manifest: RunManifest) -> dict[str, Any]:
    return {"summary": info.model_dump(mode="json"), "manifest": manifest.model_dump(mode="json")}
