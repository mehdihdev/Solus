"""`drives` bus → device from the hardware topology overlay; `hosts` machine → robot from a
confirmed host brain (relations.md §1). New relation types, so `read_topology`'s tree is
untouched."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph import kinds
from solus_api.graph.inference.common import EdgeWriter, InferenceReport
from solus_api.models import GraphEdge, GraphEntity

MODULE: Final = "overlay_edges"
DRIVES_CONFIDENCE: Final = 0.9
HOST_ATTR: Final = "host_machine_id"


async def _overlay(session: AsyncSession, project_id: UUID, robot_id: UUID) -> list[GraphEdge]:
    return list(
        await session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == RelationType.HARDWARE_CONNECTED_TO.value,
                GraphEdge.attrs["robot_id"].astext == str(robot_id),
                GraphEdge.deleted_at.is_(None),
            )
            .order_by(GraphEdge.id)
        )
    )


async def _entities(
    session: AsyncSession, project_id: UUID, ids: set[UUID]
) -> dict[UUID, GraphEntity]:
    if not ids:
        return {}
    rows = await session.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.id.in_(ids),
            GraphEntity.deleted_at.is_(None),
        )
    )
    return {row.id: row for row in rows}


async def _hosts(
    session: AsyncSession, project_id: UUID, writer: EdgeWriter, robot_id: UUID, machine_id: str
) -> None:
    robot = await session.get(GraphEntity, robot_id)
    if robot is None or robot.project_id != project_id or robot.deleted_at is not None:
        return
    if robot.attrs.get(HOST_ATTR) != machine_id:
        robot.attrs = {**robot.attrs, HOST_ATTR: machine_id}
        robot.version += 1
        await session.flush()
    machine = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.MACHINE,
            GraphEntity.canonical_key == f"machine:{machine_id}",
            GraphEntity.deleted_at.is_(None),
        )
    )
    if machine is None:
        return
    await writer.write(
        machine,
        robot,
        RelationType.HOSTS.value,
        confidence=1.0,
        evidence=[EdgeEvidence(kind=EvidenceKind.CONFIG, ref=f"host:{machine_id}")],
    )


async def infer(
    session: AsyncSession, project_id: UUID, *, robot_id: UUID, machine_id: str | None = None
) -> InferenceReport:
    writer = await EdgeWriter.open(
        session, project_id, MODULE, (RelationType.DRIVES.value, RelationType.HOSTS.value)
    )
    overlay = await _overlay(session, project_id, robot_id)
    entities = await _entities(
        session, project_id, {e.src_id for e in overlay} | {e.dst_id for e in overlay}
    )
    for edge in overlay:
        bus, device = entities.get(edge.src_id), entities.get(edge.dst_id)
        if bus is None or device is None:
            continue
        if bus.kind != kinds.HARDWARE_BUS or device.kind == kinds.HARDWARE_BUS:
            continue
        ref = edge.attrs.get("address") or edge.attrs.get("protocol") or bus.name
        await writer.write(
            bus,
            device,
            RelationType.DRIVES.value,
            confidence=DRIVES_CONFIDENCE,
            evidence=[EdgeEvidence(kind=EvidenceKind.BUS_ENUMERATION, ref=str(ref))],
            attrs={"protocol": edge.attrs.get("protocol"), "address": edge.attrs.get("address")},
        )
    if machine_id is not None:
        await _hosts(session, project_id, writer, robot_id, machine_id)
    return writer.report
