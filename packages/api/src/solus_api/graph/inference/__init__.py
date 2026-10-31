"""Edge inference (SOLUSDEV-320 Phase 3, docs/api/relations.md).

Every module reads what connectors and reviewed hardware flows already landed and writes
`origin=inferred` edges through `graph.edges.write_edge`: idempotent, never deleting or
downgrading a manual edge. Shared code dispatches by connector *capability* and by entity
kind, never by provider name (`tests/test_capability_hygiene.py` sweeps this package).

Each module runs under a SAVEPOINT through `run_guarded`: a failure is logged with the
project id and rolled back, and never fails the sync or the confirm that triggered it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import Capability
from solus_api.graph import kinds
from solus_api.graph.inference.common import InferenceReport
from solus_api.models import GraphEntity, Source

if TYPE_CHECKING:
    from solus_api.connectors.registry import ConnectorRegistry

__all__ = [
    "InferenceReport",
    "infer_after_acceptance",
    "infer_after_host_confirm",
    "infer_after_scene",
    "infer_after_sync",
    "run_guarded",
]

logger = logging.getLogger("solus.graph.inference")

#: A STRUCTURE source is "code-ish" when it landed any of these kinds.
CODE_KINDS: Final = frozenset(
    {
        kinds.CODE_REPO,
        kinds.LOCAL_CLONE,
        kinds.LOCAL_FOLDER,
        kinds.CODE_FILE,
        kinds.CODE_MODULE,
        kinds.ARDUINO_SKETCH,
        kinds.PYTHON_REQUIREMENT,
        kinds.PACKAGE_REQUIREMENT,
    }
)
#: A STRUCTURE source that landed any of these, or any CODE_KINDS, runs `ros_edges` (SOLUSDEV-321
#: P6): a re-sync that removed a source's last ROS package lands no ROS kind, and the pass is what
#: retires the inferred edges of the nodes it tombstoned.
ROS_KINDS: Final = frozenset({kinds.ROS_NODE, kinds.ROS_TOPIC})

Module = Callable[[], Awaitable[InferenceReport]]


async def run_guarded(
    session: AsyncSession, project_id: UUID, name: str, run: Module
) -> InferenceReport | None:
    try:
        async with session.begin_nested():
            report = await run()
    except Exception:
        logger.exception("inference failed module=%s project=%s", name, project_id)
        return None
    logger.info(
        "inference module=%s project=%s created=%d updated=%d skipped=%d candidates=%d",
        report.module,
        project_id,
        report.created,
        report.updated,
        report.skipped,
        report.candidates,
    )
    return report


async def _run_all(
    session: AsyncSession, project_id: UUID, plan: list[tuple[str, Module]]
) -> list[InferenceReport]:
    reports = [await run_guarded(session, project_id, name, run) for name, run in plan]
    return [r for r in reports if r is not None]


async def infer_after_sync(
    session: AsyncSession, project_id: UUID, *, source_id: UUID, registry: ConnectorRegistry
) -> list[InferenceReport]:
    """After `apply_sync_result`, in the same session: which modules run is decided by the
    source's connector capabilities (`registry.providers_of`) and the kinds it landed."""
    source = await session.get(Source, source_id)
    if source is None or source.project_id != project_id:
        logger.warning("inference skipped: source %s not in project %s", source_id, project_id)
        return []
    provider = source.type.value

    def has(capability: Capability) -> bool:
        return provider in registry.providers_of(capability)

    landed = set(
        await session.scalars(
            select(GraphEntity.kind)
            .where(GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None))
            .distinct()
        )
    )
    plan: list[tuple[str, Module]] = []
    if has(Capability.NETLIST):
        from solus_api.graph.inference import power_nets

        plan.append(("power_nets", lambda: power_nets.infer(session, project_id)))
    if has(Capability.STRUCTURE) and landed & CODE_KINDS:
        from solus_api.graph.inference import firmware_edges, manifest_edges

        plan.append(("manifest_edges", lambda: manifest_edges.infer(session, project_id)))
        plan.append(("firmware_edges", lambda: firmware_edges.infer(session, project_id)))
    if has(Capability.STRUCTURE) and landed & (CODE_KINDS | ROS_KINDS):
        from solus_api.graph.inference import ros_edges

        plan.append(("ros_edges", lambda: ros_edges.infer(session, project_id)))
    if has(Capability.GEOMETRY):
        from solus_api.graph.inference import mates

        plan.append(("mates", lambda: mates.infer(session, project_id)))
    return await _run_all(session, project_id, plan)


async def infer_after_acceptance(
    session: AsyncSession, project_id: UUID, *, robot_id: UUID
) -> list[InferenceReport]:
    """After reviewed extraction evidence is accepted for `robot_id` (not on replay)."""
    from solus_api.graph.inference import firmware_edges, joint_limits, overlay_edges

    return await _run_all(
        session,
        project_id,
        [
            ("firmware_edges", lambda: firmware_edges.infer(session, project_id)),
            ("overlay_edges", lambda: overlay_edges.infer(session, project_id, robot_id=robot_id)),
            ("joint_limits", lambda: joint_limits.infer(session, project_id)),
        ],
    )


async def infer_after_host_confirm(
    session: AsyncSession, project_id: UUID, *, robot_id: UUID, machine_id: str
) -> list[InferenceReport]:
    """After a host brain is confirmed for `robot_id` (not on replay)."""
    from solus_api.graph.inference import overlay_edges

    return await _run_all(
        session,
        project_id,
        [
            (
                "overlay_edges",
                lambda: overlay_edges.infer(
                    session, project_id, robot_id=robot_id, machine_id=machine_id
                ),
            )
        ],
    )


async def infer_after_scene(session: AsyncSession, project_id: UUID) -> list[InferenceReport]:
    """After a scene model is imported, replaced or mapped (`livebench/scene/router.finish`)."""
    from solus_api.graph.inference import joint_limits

    return await _run_all(
        session, project_id, [("joint_limits", lambda: joint_limits.infer(session, project_id))]
    )
