"""Assemble the existing driver input from independent entity-owned configurations.

A stored config lists its brains (SOLUSDEV-326). `resolve_runtime_config` keeps the v1 aggregate
its readers know (identity and protocol of the FIRST brain, every bus row with its brain, every
part), so a one-brain robot reads exactly as before; `per_brain()` is the driver input, one v1
document per brain with only that brain's rows (no `brain` on them) and parts.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import PrivateAttr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    EntityHardwareConfig,
    HardwareConfig,
    PartConfig,
    ProvenanceRecord,
    _leaf_items,
    lookup,
)
from solus_api.models import GraphEdge, SolusEntry
from solus_api.services.physical_robots import ownership_edge


class RuntimeConfig(HardwareConfig):
    """The v1 aggregate the hardware readers share, plus its brains' own documents."""

    _brains: tuple[HardwareConfig, ...] = PrivateAttr(default=())

    def per_brain(self) -> list[HardwareConfig]:
        """One v1 driver document per brain of the stored config, in order."""
        return list(self._brains)


def brains_of(config: HardwareConfig) -> list[HardwareConfig]:
    """The per-brain documents a v1 config speaks for; a plain v1 document, or an aggregate of a
    robot with no brain yet, is its own one."""
    brains = config.per_brain() if isinstance(config, RuntimeConfig) else []
    return brains or [config]


def bound_refs(config: HardwareConfig) -> set[str]:
    """The device refs of a config's bound brains."""
    return {brain.identity.device_ref for brain in brains_of(config) if brain.identity is not None}


async def _owned_parts(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> set[uuid.UUID]:
    """What the robot contains (`ownership_edge`); `attrs.robot_id` is not required."""
    return set(
        await session.scalars(
            select(GraphEdge.dst_id).where(
                ownership_edge(project_id), GraphEdge.src_id == entity_id
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


async def _active_rows(
    session: AsyncSession, project_id: uuid.UUID, entry: SolusEntry, stored: EntityHardwareConfig
) -> list[int]:
    """Bus rows whose part binding is not disabled (an ownership change awaits review)."""
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
    return [i for i, row in enumerate(stored.bus_map) if row.part_entity_id not in disabled]


def _brain_records(stored: EntityHardwareConfig, item: int) -> dict[str, ProvenanceRecord]:
    """Brain `item`'s records under their v1 names, keyed as stored (a prefix stays a prefix,
    so an upgraded one-brain config reads back the records it always had)."""
    records: dict[str, ProvenanceRecord] = {}
    for path, record in sorted(stored.provenance.items(), key=lambda pair: pair[0].count(".")):
        head, _, rest = path.partition(".")
        index, _, sub = rest.partition(".")
        field, _, leaf = sub.partition(".")
        if head != "identity" or (index and index != str(item)):
            continue
        if not field:
            records["identity"] = record
        elif field in ("binding", "protocol"):
            name = "identity" if field == "binding" else "protocol"
            records[name + (f".{leaf}" if leaf else "")] = record
    return records


def _document(
    stored: EntityHardwareConfig,
    item: int | None,
    rows: Sequence[int],
    parts: Mapping[str, PartConfig],
    part_records: Mapping[str, ProvenanceRecord],
    *,
    keep_brain: bool,
) -> dict[str, Any]:
    """The v1 document of brain `item` (None: no brain) over the given bus rows and parts."""
    brain = stored.identity[item] if item is not None else None
    provenance = _brain_records(stored, item) if item is not None else {}
    head = {
        "identity": brain.binding.model_dump(mode="json") if brain and brain.binding else None,
        "protocol": brain.protocol.model_dump(mode="json") if brain and brain.protocol else None,
    }
    for path, _ in _leaf_items(head):
        if lookup(provenance, path) is None:
            field, _, rest = path.partition(".")
            stored_field = "binding" if field == "identity" else "protocol"
            provenance[path] = stored.provenance_of(f"identity.{item}.{stored_field}.{rest}")
    provenance.update(
        {path: record for path, record in stored.provenance.items() if path == "disambiguated_by"}
    )
    provenance.update(
        {path: record for path, record in part_records.items() if path.split(".")[1] in parts}
    )
    bus = []
    for new, old in enumerate(rows):
        row = stored.bus_map[old].model_dump(mode="json", exclude=None if keep_brain else {"brain"})
        bus.append(row)
        for key, value in row.items():
            if value is not None:
                provenance[f"bus_map.{new}.{key}"] = stored.provenance_of(f"bus_map.{old}.{key}")
    firmware = stored.component.firmware if stored.component else {}
    for key, value in firmware.items():
        if value is not None:
            provenance[f"firmware.{key}"] = stored.provenance_of(f"component.firmware.{key}")
    return {
        **head,
        "robot_entity_id": stored.entity_id,
        "bus_map": bus,
        "parts": dict(parts),
        "firmware": firmware,
        "disambiguated_by": stored.disambiguated_by,
        "provenance": provenance,
    }


def assemble(
    stored: EntityHardwareConfig,
    active: Sequence[int],
    components: Mapping[str, PartConfig],
    part_records: Mapping[str, ProvenanceRecord],
) -> RuntimeConfig:
    """The aggregate over the active rows, with one driver document per brain: a lone brain
    has every row and part, one of several only its rows and the parts they map."""
    first = 0 if stored.identity else None
    aggregate = RuntimeConfig.model_validate(
        _document(stored, first, active, components, part_records, keep_brain=True)
    )
    brains = []
    for index, brain in enumerate(stored.identity):
        single = len(stored.identity) == 1
        rows = [i for i in active if single or stored.bus_map[i].brain == brain.device_ref]
        mapped = {str(stored.bus_map[i].part_entity_id) for i in rows}
        parts = {key: part for key, part in components.items() if single or key in mapped}
        document = _document(stored, index, rows, parts, part_records, keep_brain=False)
        brains.append(HardwareConfig.model_validate(document))
    aggregate._brains = tuple(brains)
    return aggregate


async def resolve_runtime_config(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> RuntimeConfig:
    from solus_api.hardware.store import _find_entry, config_of

    entry = await _find_entry(session, project_id, entity_id)
    if entry is None:
        return RuntimeConfig(robot_entity_id=entity_id)
    stored = config_of(entry)
    if isinstance(stored, HardwareConfig):
        if str(entity_id) in stored.parts:
            raise APIError(
                409,
                "config_upgrade_required",
                "An owner embedded as its own part requires reviewed migration",
            )
        legacy = RuntimeConfig.model_validate(stored.model_dump(mode="json"))
        legacy._brains = (stored,) if stored.identity or stored.protocol else ()
        return legacy
    targets = await _owned_parts(session, project_id, entity_id)
    targets.update(
        item.part_entity_id for item in stored.bus_map if item.part_entity_id is not None
    )
    targets.discard(entity_id)
    part_records: dict[str, ProvenanceRecord] = {}
    components = await _components(session, project_id, targets, part_records)
    active = await _active_rows(session, project_id, entry, stored)
    return assemble(stored, active, components, part_records)
