"""SOLUSDEV-322 P7-T3: sim-run payload retention (docs/api/bench-runs.md, Retention).

A simulated run (`attrs.summary.origin == "sim"`) that ended more than `keep_days` ago and is not
among the newest `keep_newest` of its robot loses its PAYLOAD — the manifest artifact is
soft-deleted and its bytes removed — unless it is pinned, the robot's baseline or linked to
findings. The run record itself stays live with its summary and `attrs.sim`; only
`attrs.payload_deleted_at` is added. Real runs and the rung-4 `sim_result` are never candidates.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.livebench.runs.store import RUN_KIND
from solus_api.models import Artifact, GraphEntity
from solus_api.services.solus_graph import lock_project
from solus_api.storage import ArtifactStore

logger = logging.getLogger(__name__)

#: A run carrying any of these keeps its payload whatever its age (`POST …/pin`,
#: `POST …/baseline`, `store.save(final=True)`).
KEEP_FLAGS = ("pinned", "baseline", "findings_linked")


@dataclass(frozen=True)
class PruneReport:
    deleted: int
    kept: int


def _ended_at(entity: GraphEntity) -> datetime | None:
    raw = entity.attrs.get("summary", {}).get("ended_at")
    if not raw:
        return None
    ended = datetime.fromisoformat(raw)
    return ended if ended.tzinfo else ended.replace(tzinfo=UTC)


def _recency_key(entity: GraphEntity) -> datetime:
    return _ended_at(entity) or datetime.max.replace(tzinfo=UTC)  # still running: newest


def _prunable(entity: GraphEntity, cutoff: datetime) -> bool:
    ended = _ended_at(entity)
    return (
        ended is not None
        and ended < cutoff
        and not any(entity.attrs.get(flag) for flag in KEEP_FLAGS)
    )


async def prune_sim_runs(
    session: AsyncSession,
    store: ArtifactStore,
    *,
    now: datetime,
    keep_days: int = 30,
    keep_newest: int = 20,
) -> PruneReport:
    """Module docstring. `kept` counts the live sim runs whose payload is still there."""
    rows = (
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.kind == RUN_KIND,
                GraphEntity.origin == "system",
                GraphEntity.deleted_at.is_(None),
                GraphEntity.attrs["summary"]["origin"].astext == "sim",
                GraphEntity.attrs["payload_deleted_at"].astext.is_(None),
            )
        )
    ).all()
    cutoff = now - timedelta(days=keep_days)
    by_robot: dict[tuple[UUID, str], list[GraphEntity]] = defaultdict(list)
    for row in rows:
        by_robot[(row.project_id, str(row.attrs["summary"].get("robot_id")))].append(row)
    doomed: dict[UUID, list[GraphEntity]] = defaultdict(list)
    for (project_id, _robot), runs in by_robot.items():
        runs.sort(key=_recency_key, reverse=True)
        doomed[project_id].extend(run for run in runs[keep_newest:] if _prunable(run, cutoff))
    deleted = 0
    for project_id, runs in doomed.items():
        deleted += await _delete_payloads(session, store, project_id, runs, now, cutoff)
    return PruneReport(deleted=deleted, kept=len(rows) - deleted)


async def _reread_under_lock(
    session: AsyncSession, project_id: UUID, runs: list[GraphEntity], cutoff: datetime
) -> list[GraphEntity]:
    """The candidates again, locked and refreshed: a pin, baseline or prune committed between
    the candidate read and the project lock wins over the stale snapshot."""
    fresh = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.id.in_([run.id for run in runs]),
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["payload_deleted_at"].astext.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return [run for run in fresh if _prunable(run, cutoff)]


async def _delete_payloads(
    session: AsyncSession,
    store: ArtifactStore,
    project_id: UUID,
    candidates: list[GraphEntity],
    now: datetime,
    cutoff: datetime,
) -> int:
    """Soft-delete the runs' checkpoint artifacts and stamp the records, one commit per project
    under the project lock; the bytes go after the commit, as `store.save` drops an old
    checkpoint. A deleted project is skipped, not an error."""
    try:
        await lock_project(session, project_id)
    except APIError:
        logger.info("sim run retention skipped project=%s: project gone", project_id)
        return 0
    runs = await _reread_under_lock(session, project_id, candidates, cutoff)
    ids = [UUID(run.attrs["checkpoint_id"]) for run in runs if run.attrs.get("checkpoint_id")]
    artifacts = (
        await session.scalars(
            select(Artifact)
            .where(
                Artifact.id.in_(ids),
                Artifact.project_id == project_id,
                Artifact.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).all()
    for artifact in artifacts:
        artifact.retained = False
        artifact.deleted_at = now
    for run in runs:
        run.attrs = {**run.attrs, "payload_deleted_at": now.isoformat()}
    await session.commit()
    for artifact in artifacts:
        try:
            await store.delete(str(artifact.id))
        except Exception:  # noqa: BLE001 — the row is already soft-deleted; bytes are inert
            logger.warning("sim run payload cleanup failed: artifact=%s", artifact.id)
    logger.info("sim run retention project=%s payloads_deleted=%s", project_id, len(runs))
    return len(runs)
