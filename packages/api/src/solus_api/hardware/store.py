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
from sqlalchemy.orm import aliased
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    EntityHardwareConfig,
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    PartConfig,
    _leaf_items,
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
from solus_api.services.solus_graph import CONFIG_NODE_KIND, ORIGIN, SolusGraph, lock_project

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


def config_of(entry: SolusEntry) -> HardwareConfig | EntityHardwareConfig:
    if entry.kind is not SolusEntryKind.CONFIG or entry.payload is None:
        raise APIError(404, "not_found", "Hardware config not found")
    if entry.payload.get("schema_version") == 2:
        return EntityHardwareConfig.model_validate(entry.payload)
    return HardwareConfig.model_validate(entry.payload)


async def hardware_entity(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> GraphEntity:
    entity = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.id == entity_id,
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if entity is None or entity.kind not in PART_KINDS | {ROBOT_KIND}:
        raise APIError(404, "not_found", "Hardware entity not found")
    if entity.kind == ROBOT_KIND and (entity.origin != ORIGIN or entity.source_id is not None):
        raise APIError(404, "not_found", "Hardware entity not found")
    return entity


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


async def configuration_entries(
    session: AsyncSession, project_id: uuid.UUID, entity_ids: Sequence[uuid.UUID]
) -> list[SolusEntry]:
    """Read current entries only when their subject and canonical graph links are live.

    An inconsistent live entry is a conflict, not absence: treating it as missing
    would permit attempted replacement and violate the unique subject constraint.
    """
    subject = aliased(GraphEntity)
    live_node = (
        select(GraphEntity.id)
        .where(
            GraphEntity.id == SolusEntry.entity_id,
            GraphEntity.project_id == project_id,
            GraphEntity.kind == CONFIG_NODE_KIND,
            GraphEntity.origin == ORIGIN,
            GraphEntity.source_id.is_(None),
            GraphEntity.deleted_at.is_(None),
        )
        .exists()
    )
    live_link = (
        select(GraphEdge.id)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.src_id == SolusEntry.entity_id,
            GraphEdge.dst_id == SolusEntry.configured_entity_id,
            GraphEdge.relation_type == CONFIGURES,
            GraphEdge.origin == ORIGIN,
            GraphEdge.source_id.is_(None),
            GraphEdge.deleted_at.is_(None),
        )
        .exists()
    )
    rows = await session.execute(
        select(SolusEntry, (live_node & live_link).label("active_graph"))
        .join(subject, subject.id == SolusEntry.configured_entity_id)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == SolusSection.HARDWARE,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.configured_entity_id.in_(entity_ids),
            subject.project_id == project_id,
            subject.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    entries: dict[uuid.UUID | None, SolusEntry] = {}
    for entry, active_graph in rows:
        if not active_graph or entry.configured_entity_id in entries:
            raise APIError(409, "config_conflict", "Configuration graph requires review")
        entries[entry.configured_entity_id] = entry
    return list(entries.values())


async def _find_entry(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> SolusEntry | None:
    entries = await configuration_entries(session, project_id, [entity_id])
    return entries[0] if entries else None


async def read_entity_config(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> tuple[SolusEntry | None, EntityHardwareConfig | None]:
    entry = await _find_entry(session, project_id, entity_id)
    if entry is None:
        return None, None
    config = config_of(entry)
    if isinstance(config, HardwareConfig):
        raise APIError(409, "config_upgrade_required", "Hardware configuration requires migration")
    return entry, config


async def _create_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    subject: GraphEntity,
    config: EntityHardwareConfig,
    *,
    created_by: uuid.UUID | None,
) -> SolusEntry:
    graph = await SolusGraph.ensure(session, project_id)
    entry = SolusEntry(
        project_id=project_id,
        section=SolusSection.HARDWARE,
        kind=SolusEntryKind.CONFIG,
        text=f"Hardware config — {subject.name}",
        payload=config.model_dump(mode="json"),
        configured_entity_id=subject.id,
        config_version=1,
        author="user",
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    node = graph.attach_entry(entry)
    node.attrs = {**node.attrs, "configured_entity_id": str(subject.id)}
    await graph.flush()
    session.add(
        GraphEdge(
            project_id=project_id,
            src_id=node.id,
            dst_id=subject.id,
            relation_type=CONFIGURES,
            domain_pair=f"project<->{subject.domain.value}",
            origin=ORIGIN,
        )
    )
    if subject.origin == ORIGIN and subject.source_id is None:
        subject.attrs = {**subject.attrs, "hardware_config_ref": str(entry.id)}
    await session.flush()
    return entry


async def put_entity_config(
    session: AsyncSession,
    project_id: uuid.UUID,
    subject: GraphEntity,
    config: EntityHardwareConfig,
    *,
    expected_version: int,
    created_by: uuid.UUID | None,
) -> SolusEntry:
    from solus_api.hardware.bindings import synchronize_bindings

    await lock_project(session, project_id)
    subject = await hardware_entity(session, project_id, subject.id)
    if config.entity_id != subject.id:
        raise APIError(422, "validation_error", "config.entity_id must match this entity")
    targets = {item.part_entity_id for item in config.bus_map if item.part_entity_id is not None}
    if targets:
        actual = set(
            await session.scalars(
                select(GraphEntity.id).where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(targets),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.kind.in_(PART_KINDS),
                )
            )
        )
        if actual != targets:
            raise APIError(404, "not_found", "A configured part was not found in this project")
    entry = await _find_entry(session, project_id, subject.id)
    version = entry.config_version if entry else 0
    if version != expected_version:
        raise APIError(
            409,
            "config_conflict",
            "Configuration changed; review the current version",
            details=[{"current_version": version}],
        )
    if entry is None:
        entry = await _create_entry(session, project_id, subject, config, created_by=created_by)
    else:
        entry.payload = config.model_dump(mode="json")
        entry.configured_entity_id = subject.id
        entry.config_version = version + 1
        if entry.entity_id is not None:
            node = await session.get(GraphEntity, entry.entity_id)
            if node is not None:
                node.version += 1
    await synchronize_bindings(session, project_id, entry, config)
    await session.flush()
    return entry


async def ensure_config(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    created_by: uuid.UUID | None,
) -> tuple[SolusEntry, HardwareConfig]:
    """Mutation-only compatibility helper. Read routes use read_entity_config instead."""
    from solus_api.hardware.runtime import resolve_runtime_config

    await lock_project(session, project_id)
    entry = await _find_entry(session, project_id, robot.id)
    if entry is None:
        entry = await put_entity_config(
            session,
            project_id,
            robot,
            EntityHardwareConfig(entity_id=robot.id),
            expected_version=0,
            created_by=created_by,
        )
    return entry, await resolve_runtime_config(session, project_id, robot.id)


async def put_config(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    config: HardwareConfig,
    *,
    created_by: uuid.UUID | None,
) -> SolusEntry:
    """Trusted internal adapter. Persist v2 subjects, never a second runtime aggregate.

    HTTP legacy writes are separately version-gated; callers of this adapter hold a reviewed
    operation/project lock and assemble the complete current runtime view before editing.
    """
    from solus_api.hardware.migration import split_legacy_document

    if config.robot_entity_id != robot.id:
        raise APIError(422, "validation_error", "config.robot_entity_id must be this robot")
    await lock_project(session, project_id)
    documents = split_legacy_document(config.model_dump(mode="json"), source_namespace=project_id)
    await _require_complete_compatibility_view(session, project_id, set(documents))
    owner_entry = None
    # Validate every subject before any update; callers keep this in one transaction.
    subjects = {
        entity_id: await hardware_entity(session, project_id, entity_id) for entity_id in documents
    }
    for entity_id, document in documents.items():
        previous, current = await read_entity_config(session, project_id, entity_id)
        if current is not None:
            document = (
                _preserve_owner_component(current, document)
                if entity_id == robot.id
                else _preserve_part_connection(current, document)
            )
        if (
            current == document
            and previous is not None
            and previous.payload is not None
            and previous.payload.get("schema_version") == 2
        ):
            entry = previous
        else:
            entry = await put_entity_config(
                session,
                project_id,
                subjects[entity_id],
                document,
                expected_version=previous.config_version if previous else 0,
                created_by=created_by,
            )
        if entity_id == robot.id:
            owner_entry = entry
    assert owner_entry is not None
    from solus_api.hardware.topology import sync_topology

    await sync_topology(session, project_id, robot.id)
    return owner_entry


async def _require_complete_compatibility_view(
    session: AsyncSession, project_id: uuid.UUID, subjects: set[uuid.UUID]
) -> None:
    """A filtered runtime bus is not a reviewed replacement for durable evidence."""
    disabled = await session.scalar(
        select(GraphEdge.id)
        .join(SolusEntry, SolusEntry.entity_id == GraphEdge.src_id)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation_type == "binds",
            GraphEdge.origin == ORIGIN,
            GraphEdge.source_id.is_(None),
            GraphEdge.deleted_at.is_(None),
            GraphEdge.attrs["enabled"].as_boolean().is_(False),
            SolusEntry.project_id == project_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.configured_entity_id.in_(subjects),
        )
        .limit(1)
    )
    if disabled is not None:
        raise APIError(
            409,
            "config_upgrade_required",
            "Disabled bindings require review through the per-entity configuration",
        )


def _preserve_part_connection(
    current: EntityHardwareConfig, incoming: EntityHardwareConfig
) -> EntityHardwareConfig:
    """A parent's v1 parts map exposes components, never a child's own connection."""
    provenance = {
        path: record
        for path, record in incoming.provenance.items()
        if path == "component" or path.startswith("component.")
    }
    provenance.update(
        {
            path: record
            for path, record in current.provenance.items()
            if path.split(".")[0] in {"identity", "protocol", "bus_map", "disambiguated_by"}
        }
    )
    return EntityHardwareConfig.model_validate(
        {
            **current.model_dump(),
            "component": incoming.component,
            "provenance": provenance,
        }
    )


def _preserve_owner_component(
    current: EntityHardwareConfig, incoming: EntityHardwareConfig
) -> EntityHardwareConfig:
    """v1 exposes owner firmware only; preserve v2-only component fields in place."""
    if current.component is None:
        return incoming
    firmware = incoming.component.firmware if incoming.component else {}
    component = current.component.model_copy(update={"firmware": firmware})
    provenance = {
        path: record
        for path, record in incoming.provenance.items()
        if path != "component" and not path.startswith("component.")
    }
    for path, _ in _leaf_items(component.model_dump(exclude={"firmware"}), "component."):
        provenance[path] = current.provenance_of(path)
    for key, value in firmware.items():
        if value is not None:
            path = f"component.firmware.{key}"
            provenance[path] = incoming.provenance_of(path)
    return EntityHardwareConfig.model_validate(
        {
            **incoming.model_dump(),
            "component": component,
            "provenance": provenance,
        }
    )


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
    """All live part-like entities, including named manual parts, without a robot owner."""
    return select(GraphEntity).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind.in_(PART_KINDS),
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
    await lock_project(session, project_id)
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
            previous, own = await read_entity_config(session, project_id, entity_id)
            if own is not None and own.component is not None:
                document["parts"][str(entity_id)] = own.component.model_dump(mode="json")
                for path in own.provenance:
                    if path == "component" or path.startswith("component."):
                        document["provenance"][
                            f"parts.{entity_id}" + path.removeprefix("component")
                        ] = own.provenance[path].model_dump(mode="json")
            else:
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
