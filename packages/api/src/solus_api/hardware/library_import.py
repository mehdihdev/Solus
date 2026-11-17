"""Library imports as services (docs/api/hardware.md §5) that the library routes and SOL's hardware
tools both call (SOLUSDEV-326 P2): a platform as a new robot, a part into a robot, and a
standalone part through the scoped operation ledger. Each takes the project and the acting member
explicitly, reads through the caller's bound read scope, flushes and never commits; the caller
emits the events, commits and publishes. Vendor names never appear here: they are definitions.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.hardware.config import (
    ConfigLayer,
    EntityHardwareConfig,
    FieldProvenance,
    HardwareConfig,
    merge_layers,
)
from solus_api.hardware.detect import DetectedDeviceOut
from solus_api.hardware.library import Library, PartDefinition, PlatformDefinition
from solus_api.hardware.links import (
    PartObservation,
    RobotCandidate,
    persist_suggestions,
    suggest_links,
)
from solus_api.hardware.operations import ReviewedHardwareOperations
from solus_api.hardware.store import (
    attach_part,
    ensure_config,
    put_config,
    put_entity_config,
    robot_root,
)
from solus_api.models import Domain, GraphEntity, HardwareSuggestion, SolusEntry
from solus_api.schemas import serialize_entity
from solus_api.services.physical_robots import PhysicalRobotService

logger = logging.getLogger(__name__)


async def _attach_definition(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    part: PartDefinition,
    *,
    name: str,
    extra: dict[str, Any],
) -> GraphEntity:
    """A library part as a manual `part` entity the robot contains. No `external_ref`: the
    wire assigns identity later, through detection and the suggestion inbox."""
    return await attach_part(
        session,
        project_id,
        robot,
        name=name,
        attrs={
            "model": part.name,
            "manufacturer": part.manufacturer,
            "definition_id": part.id,
            "specs": dict(part.specs),
            **extra,
        },
        provenance=FieldProvenance.LIBRARY,
    )


async def _reconcile(
    session: AsyncSession,
    local: Any,
    project_id: uuid.UUID,
    robot: GraphEntity,
    config: HardwareConfig,
) -> list[HardwareSuggestion]:
    """Devices on this machine against the new library robot, through the link-suggestion
    engine. No runner, an unreadable runner, or no bus evidence is honestly no suggestion —
    the import never fails because detection did, and nothing auto-links (ADR-012)."""
    if local is None:
        return []
    try:
        raw = await asyncio.to_thread(local.detect_devices)
        devices = [DetectedDeviceOut.model_validate(item) for item in raw]
    except Exception as exc:  # detection is best-effort here; the robot exists either way
        logger.warning("library import skipped reconciliation: %s", type(exc).__name__)
        return []
    candidate = RobotCandidate(robot_entity_id=robot.id, name=robot.name, config=config)
    suggestions = []
    for device in devices:
        if device.device_ref is None:
            continue
        observation = PartObservation(
            subject_ref=device.device_ref,
            subject_kind="device",
            device_ref=device.device_ref,
            evidence=list(device.evidence),
        )
        suggestions.extend(suggest_links(observation, [candidate]))
    return await persist_suggestions(session, project_id, suggestions)


@dataclass(frozen=True)
class PlatformImport:
    """A platform imported as a robot: the root, its parts, its config entry, and the link
    suggestions reconciliation raised against devices on this machine."""

    robot: GraphEntity
    part_ids: list[uuid.UUID]
    entry: SolusEntry
    suggestions: list[HardwareSuggestion]


async def import_platform(
    session: AsyncSession,
    local: Any,
    library: Library,
    platform: PlatformDefinition,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str | None,
    in_graph: bool = True,
    onboarded_by: uuid.UUID | None = None,
) -> PlatformImport:
    """A platform as a new robot named `name` (else the platform's): the parts it contains
    directly, a LIBRARY config layer, and a reconciliation pass so a detected machine and its
    library twin stay ONE robot. Its parts take the robot's visibility (SOLUSDEV-326)."""
    robot = await PhysicalRobotService(session).create(
        project_id,
        platform.name if name is None else name,
        in_graph=in_graph,
        onboarded_by=onboarded_by,
    )
    entity_ids: dict[str, uuid.UUID] = {}
    for slot in platform.parts:
        entity = await _attach_definition(
            session,
            project_id,
            robot,
            library.parts[slot.part],
            name=slot.role,
            extra={"role": slot.role, "gear_ratio": slot.gear_ratio},
        )
        entity_ids[slot.address] = entity.id
    layer = ConfigLayer(
        by=FieldProvenance.LIBRARY,
        source=f"platform:{platform.id}",
        document=library.platform_config_layer(platform, entity_ids),
    )
    config = merge_layers(robot.id, [layer])
    entry = await put_config(session, project_id, robot, config, created_by=user_id)
    suggestions = await _reconcile(session, local, project_id, robot, config)
    return PlatformImport(robot, list(entity_ids.values()), entry, suggestions)


async def import_part_into_robot(
    session: AsyncSession,
    part: PartDefinition,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    robot_id: uuid.UUID,
    name: str | None,
) -> tuple[GraphEntity, SolusEntry]:
    """A library part the robot contains directly, named `name` (else the definition's), with
    its config slot under LIBRARY provenance; the robot is one the reader may see, else 404."""
    robot = await robot_root(session, project_id, robot_id)
    entity = await _attach_definition(
        session, project_id, robot, part, name=name or part.name, extra={}
    )
    _, config = await ensure_config(session, project_id, robot, created_by=user_id)
    source = f"part:{part.id}"
    document = config.model_dump(mode="json")
    document["parts"][str(entity.id)] = Library.part_config(part, part.id, source=source)
    document["provenance"][f"parts.{entity.id}"] = {
        "by": FieldProvenance.LIBRARY.value,
        "source": source,
    }
    entry = await put_config(
        session,
        project_id,
        robot,
        HardwareConfig.model_validate(document),
        created_by=user_id,
    )
    return entity, entry


async def import_standalone_part(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    key: uuid.UUID,
    part: PartDefinition,
    *,
    name: str,
) -> tuple[dict[str, Any], bool]:
    operations = ReviewedHardwareOperations(session, project_id, user_id)
    # ponytail: the definition's own category still keys the replay digest — what P1 keyed it
    # on for a body naming none — so a key minted before the field went (SOLUSDEV-326 P2)
    # replays. Nothing stores it.
    previous, digest = await operations.replay(
        key,
        "library.part.import",
        {"definition_id": part.id, "name": name, "category": part.category},
    )
    if previous is not None:
        return dict(previous.response), True
    entity = GraphEntity(
        id=uuid7(),
        project_id=project_id,
        kind="part",
        name=name,
        domain=Domain.PROJECT,
        origin="manual",
        attrs={
            "definition_id": part.id,
            "model": part.name,
            "manufacturer": part.manufacturer,
            "specs": dict(part.specs),
            "provenance": "library",
        },
    )
    session.add(entity)
    await session.flush()
    source = f"part:{part.id}"
    config = EntityHardwareConfig.model_validate(
        {
            "entity_id": entity.id,
            "component": Library.part_config(part, part.id, source=source),
            "provenance": {"component": {"by": "library", "source": source}},
        }
    )
    entry = await put_entity_config(
        session, project_id, entity, config, expected_version=0, created_by=user_id
    )
    response = {"entity": serialize_entity(entity), "config_entry_id": entry.id}
    return operations.record(key, "library.part.import", digest, response), False
