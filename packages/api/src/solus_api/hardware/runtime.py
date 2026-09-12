"""Assemble the existing driver input from independent entity-owned configurations."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    BusMapEntry,
    EntityHardwareConfig,
    HardwareConfig,
    PartConfig,
    ProvenanceRecord,
    TransportBinding,
)
from solus_api.models import GraphEdge, GraphEntity, SolusEntry


async def _owned_parts(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> set[uuid.UUID]:
    categories = select(GraphEntity.id).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind == "robot_category",
        GraphEntity.origin == "manual",
        GraphEntity.source_id.is_(None),
        GraphEntity.attrs["robot_id"].astext == str(entity_id),
        GraphEntity.deleted_at.is_(None),
    )
    return set(
        await session.scalars(
            select(GraphEdge.dst_id).where(
                GraphEdge.project_id == project_id,
                GraphEdge.src_id.in_(categories),
                GraphEdge.relation_type == "contains",
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
            )
        )
    )


async def _components(
    session: AsyncSession,
    project_id: uuid.UUID,
    targets: set[uuid.UUID],
    provenance: dict[str, ProvenanceRecord],
) -> dict[str, PartConfig]:
    from solus_api.hardware.store import config_of, configuration_entries

    entries = await configuration_entries(session, project_id, list(targets))
    components: dict[str, PartConfig] = {}
    for entry in entries:
        config = config_of(entry)
        if not isinstance(config, EntityHardwareConfig) or config.component is None:
            continue
        if config.entity_id != entry.configured_entity_id:
            continue
        part_id = str(config.entity_id)
        components[part_id] = config.component
        for path, record in config.provenance.items():
            if path == "component" or path.startswith("component."):
                provenance[f"parts.{part_id}" + path.removeprefix("component")] = record
    return components


async def _active_bus(
    session: AsyncSession,
    project_id: uuid.UUID,
    entry: SolusEntry,
    stored: EntityHardwareConfig,
    provenance: dict[str, ProvenanceRecord],
) -> list[BusMapEntry]:
    disabled = set(
        await session.scalars(
            select(GraphEdge.dst_id).where(
                GraphEdge.project_id == project_id,
                GraphEdge.src_id == entry.entity_id,
                GraphEdge.relation_type == "binds",
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
                GraphEdge.attrs["enabled"].as_boolean().is_(False),
            )
        )
    )
    active: list[BusMapEntry] = []
    for index, item in enumerate(stored.bus_map):
        if item.part_entity_id in disabled:
            continue
        new_index = len(active)
        active.append(item)
        for key, value in item.model_dump().items():
            if value is not None:
                provenance[f"bus_map.{new_index}.{key}"] = stored.provenance_of(
                    f"bus_map.{index}.{key}"
                )
    return active


async def resolve_runtime_config(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> HardwareConfig:
    from solus_api.hardware.store import _find_entry, config_of

    entry = await _find_entry(session, project_id, entity_id)
    if entry is None:
        return HardwareConfig(robot_entity_id=entity_id)
    stored = config_of(entry)
    if isinstance(stored, HardwareConfig):
        if str(entity_id) in stored.parts:
            raise APIError(
                409,
                "config_upgrade_required",
                "An owner embedded as its own part requires reviewed migration",
            )
        return stored
    targets = await _owned_parts(session, project_id, entity_id)
    targets.update(
        item.part_entity_id for item in stored.bus_map if item.part_entity_id is not None
    )
    targets.discard(entity_id)
    provenance = {
        path: record
        for path, record in stored.provenance.items()
        if path.split(".")[0] in {"identity", "protocol", "disambiguated_by"}
    }
    components = await _components(session, project_id, targets, provenance)
    bus_map = await _active_bus(session, project_id, entry, stored, provenance)
    firmware = stored.component.firmware if stored.component else {}
    for key, value in firmware.items():
        if value is not None:
            provenance[f"firmware.{key}"] = stored.provenance_of(f"component.firmware.{key}")
    return HardwareConfig(
        robot_entity_id=entity_id,
        identity=TransportBinding.model_validate(stored.identity.model_dump())
        if stored.identity
        else None,
        protocol=stored.protocol,
        bus_map=bus_map,
        parts=components,
        firmware=firmware,
        disambiguated_by=stored.disambiguated_by,
        provenance=provenance,
    )
