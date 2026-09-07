"""The HardwareConfig store (R5, docs/api/hardware.md §2).

A robot's config is ONE `.solus` Hardware-configs entry of kind CONFIG whose payload is the
validated document; the robot root points at it through `attrs.hardware_config_ref`. Parts are
graph entities under the robot's category nodes; their calibration, limits, telemetry and
lifecycle live in the document keyed by entity id, so a promotion never touches the graph.
Callers own the commit (and publish the graph hint after it).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    PartConfig,
    promote_part,
)
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
)
from solus_api.services.physical_robots import ROBOT_CATEGORIES
from solus_api.services.solus_graph import CONFIG_NODE_KIND, ORIGIN, SolusGraph

ROBOT_KIND = "physical_robot"
CATEGORY_KIND = "robot_category"
PART_KIND = "part"
CONFIGURES = "configures"
MAX_SPECS = 32
_DOMAIN_PAIR = "project<->project"

__all__ = [
    "CONFIG_NODE_KIND",
    "PART_KIND",
    "config_of",
    "create_part",
    "ensure_config",
    "promote",
    "put_config",
    "robot_root",
]


def config_of(entry: SolusEntry) -> HardwareConfig:
    if entry.kind is not SolusEntryKind.CONFIG or entry.payload is None:
        raise APIError(404, "not_found", "Hardware config not found")
    return HardwareConfig.model_validate(entry.payload)


async def robot_root(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID
) -> GraphEntity:
    """Only a live, manual, source-less Physical Robot root in THIS project (else 404)."""
    root = await session.get(GraphEntity, robot_id)
    if (
        root is None
        or root.project_id != project_id
        or root.deleted_at is not None
        or root.kind != ROBOT_KIND
        or root.origin != ORIGIN
        or root.source_id is not None
    ):
        raise APIError(404, "not_found", "Robot not found")
    return root


async def _find_entry(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID
) -> SolusEntry | None:
    entry: SolusEntry | None = await session.scalar(
        select(SolusEntry)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == SolusSection.HARDWARE,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.payload["robot_entity_id"].astext == str(robot_id),
        )
        .order_by(SolusEntry.created_at, SolusEntry.id)
        .limit(1)
    )
    return entry


async def _create_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    config: HardwareConfig,
    *,
    created_by: uuid.UUID | None,
) -> SolusEntry:
    graph = await SolusGraph.ensure(session, project_id)  # holds the project lock
    entry = SolusEntry(
        project_id=project_id,
        section=SolusSection.HARDWARE,
        kind=SolusEntryKind.CONFIG,
        text=f"Hardware config — {robot.name}",
        payload=config.model_dump(mode="json"),
        author="user",
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    node = graph.attach_entry(entry)
    node.attrs = {**node.attrs, "robot_id": str(robot.id)}
    await graph.flush()
    session.add(
        GraphEdge(
            project_id=project_id,
            src_id=node.id,
            dst_id=robot.id,
            relation_type=CONFIGURES,
            domain_pair=_DOMAIN_PAIR,
            origin=ORIGIN,
        )
    )
    robot.attrs = {**robot.attrs, "hardware_config_ref": str(entry.id)}
    await session.flush()
    return entry


async def ensure_config(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    created_by: uuid.UUID | None,
) -> tuple[SolusEntry, HardwareConfig]:
    """The robot's config entry, created empty on first use (idempotent)."""
    entry = await _find_entry(session, project_id, robot.id)
    if entry is not None:
        return entry, config_of(entry)
    config = HardwareConfig(robot_entity_id=robot.id)
    return await _create_entry(session, project_id, robot, config, created_by=created_by), config


async def put_config(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    config: HardwareConfig,
    *,
    created_by: uuid.UUID | None,
) -> SolusEntry:
    """Replace the document. The document must be THIS robot's (422 otherwise)."""
    if config.robot_entity_id != robot.id:
        raise APIError(422, "validation_error", "config.robot_entity_id must be this robot")
    entry = await _find_entry(session, project_id, robot.id)
    if entry is None:
        return await _create_entry(session, project_id, robot, config, created_by=created_by)
    entry.payload = config.model_dump(mode="json")
    if entry.entity_id is not None:
        node = await session.get(GraphEntity, entry.entity_id)
        if node is not None:
            node.version += 1
    await session.flush()
    return entry


async def _category_node(
    session: AsyncSession, project_id: uuid.UUID, robot: GraphEntity, category: str
) -> GraphEntity:
    if category not in ROBOT_CATEGORIES:
        raise APIError(422, "validation_error", "Unknown robot category")
    node = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == CATEGORY_KIND,
            GraphEntity.origin == ORIGIN,
            GraphEntity.source_id.is_(None),
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["robot_id"].astext == str(robot.id),
            GraphEntity.attrs["category"].astext == category,
        )
    )
    if node is None:
        raise APIError(404, "not_found", "Robot category not found")
    return node


async def attach_part(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    name: str,
    category: str,
    attrs: Mapping[str, Any],
    provenance: FieldProvenance,
    external_ref: str | None = None,
) -> GraphEntity:
    """A manual `part` entity under the robot's category node. `external_ref` is the
    telemetry identity (`<device ref>/<address>`) for detected parts; authored parts have none."""
    label = " ".join(name.split())
    if not label or len(label) > 512:
        raise APIError(422, "validation_error", "name must be 1-512 characters")
    category_node = await _category_node(session, project_id, robot, category)
    part = GraphEntity(
        id=uuid7(),
        project_id=project_id,
        kind=PART_KIND,
        domain=Domain.PROJECT,
        origin=ORIGIN,
        name=label,
        external_ref=external_ref,
        attrs={
            **dict(attrs),
            "category": category,
            "robot_id": str(robot.id),
            "provenance": provenance.value,
        },
    )
    session.add(part)
    await session.flush()
    session.add(
        GraphEdge(
            project_id=project_id,
            src_id=category_node.id,
            dst_id=part.id,
            relation_type="contains",
            domain_pair=_DOMAIN_PAIR,
            origin=ORIGIN,
        )
    )
    await session.flush()
    return part


async def create_part(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    name: str,
    category: str,
    specs: Mapping[str, Any],
    lifecycle: LifecycleState,
    created_by: uuid.UUID | None,
) -> tuple[GraphEntity, SolusEntry]:
    """Author a part: a manual `part` entity under the category, plus its config slot."""
    if len(specs) > MAX_SPECS:
        raise APIError(422, "validation_error", f"at most {MAX_SPECS} specs")
    part = await attach_part(
        session,
        project_id,
        robot,
        name=name,
        category=category,
        attrs={"specs": dict(specs)},
        provenance=FieldProvenance.USER,
    )
    _, config = await ensure_config(session, project_id, robot, created_by=created_by)
    document = config.model_dump(mode="json")
    document["parts"][str(part.id)] = PartConfig(lifecycle=lifecycle).model_dump(mode="json")
    document["provenance"][f"parts.{part.id}"] = {
        "by": FieldProvenance.USER.value,
        "source": None,
    }
    entry = await put_config(
        session, project_id, robot, HardwareConfig.model_validate(document), created_by=created_by
    )
    return part, entry


#: Connector kinds that are physical parts a robot can own (the CAD/EDA vocabulary today).
PART_KINDS = frozenset({"part", "component", "cad_part", "assembly"})
MAX_ATTACH = 64


def _owned_part_ids(project_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """Targets of a live manual `contains` edge from any live robot category."""
    categories = select(GraphEntity.id).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind == CATEGORY_KIND,
        GraphEntity.origin == ORIGIN,
        GraphEntity.deleted_at.is_(None),
    )
    return select(GraphEdge.dst_id).where(
        GraphEdge.project_id == project_id,
        GraphEdge.origin == ORIGIN,
        GraphEdge.source_id.is_(None),
        GraphEdge.relation_type == "contains",
        GraphEdge.deleted_at.is_(None),
        GraphEdge.src_id.in_(categories),
    )


def unassigned_parts_stmt(project_id: uuid.UUID) -> Select[tuple[GraphEntity]]:
    """Connector-sourced part-like entities no live robot category owns."""
    return select(GraphEntity).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind.in_(PART_KINDS),
        GraphEntity.source_id.is_not(None),
        GraphEntity.deleted_at.is_(None),
        GraphEntity.id.not_in(_owned_part_ids(project_id)),
    )


async def attach_existing_parts(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    entity_ids: Sequence[uuid.UUID],
    category: str,
    created_by: uuid.UUID | None,
) -> tuple[list[uuid.UUID], list[uuid.UUID], SolusEntry]:
    """Attach parts already in the graph (From a file) under a category. A part under THIS
    robot is skipped; a part under another robot is a conflict; anything else is 404."""
    category_node = await _category_node(session, project_id, robot, category)
    wanted = list(dict.fromkeys(entity_ids))
    rows = {
        row.id: row
        for row in await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_(wanted),
                GraphEntity.kind.in_(PART_KINDS),
                GraphEntity.deleted_at.is_(None),
            )
        )
    }
    missing = [e for e in wanted if e not in rows]
    if missing:
        raise APIError(404, "not_found", f"{len(missing)} part(s) not found in this project")
    owners = {
        edge.dst_id: edge.src_id
        for edge in await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.dst_id.in_(wanted),
                GraphEdge.origin == ORIGIN,
                GraphEdge.source_id.is_(None),
                GraphEdge.relation_type == "contains",
                GraphEdge.deleted_at.is_(None),
            )
        )
    }
    mine = {
        node.id
        for node in await session.scalars(
            select(GraphEntity).where(
                GraphEntity.kind == CATEGORY_KIND,
                GraphEntity.attrs["robot_id"].astext == str(robot.id),
                GraphEntity.deleted_at.is_(None),
            )
        )
    }
    attached: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    for entity_id in wanted:
        owner = owners.get(entity_id)
        if owner in mine:
            skipped.append(entity_id)
            continue
        if owner is not None:
            raise APIError(
                409, "conflict", f"{rows[entity_id].name} already belongs to another robot"
            )
        session.add(
            GraphEdge(
                project_id=project_id,
                src_id=category_node.id,
                dst_id=entity_id,
                relation_type="contains",
                domain_pair=_DOMAIN_PAIR,
                origin=ORIGIN,
            )
        )
        attached.append(entity_id)
    await session.flush()
    entry, config = await ensure_config(session, project_id, robot, created_by=created_by)
    if attached:
        document = config.model_dump(mode="json")
        for entity_id in attached:
            document["parts"][str(entity_id)] = PartConfig().model_dump(mode="json")
            document["provenance"][f"parts.{entity_id}"] = {
                "by": FieldProvenance.USER.value,
                "source": None,
            }
        entry = await put_config(
            session,
            project_id,
            robot,
            HardwareConfig.model_validate(document),
            created_by=created_by,
        )
    return attached, skipped, entry


async def promote(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    part_id: uuid.UUID,
    state: LifecycleState,
    *,
    created_by: uuid.UUID | None,
) -> tuple[PartConfig, SolusEntry]:
    """Promote a part's lifecycle; the entity id and its edges are untouched."""
    _, config = await ensure_config(session, project_id, robot, created_by=created_by)
    part = await session.get(GraphEntity, part_id)
    if (
        str(part_id) not in config.parts
        or part is None
        or part.project_id != project_id
        or part.deleted_at is not None
    ):
        raise APIError(404, "not_found", "Part not found on this robot")
    promoted = promote_part(config, str(part_id), state)
    entry = await put_config(session, project_id, robot, promoted, created_by=created_by)
    return promoted.parts[str(part_id)], entry
