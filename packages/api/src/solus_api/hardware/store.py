"""The HardwareConfig store (R5, docs/api/hardware.md §2).

A robot's config is ONE `.solus` Hardware-configs entry of kind CONFIG whose payload is the
validated document; the robot root points at it through `attrs.hardware_config_ref`. Parts are
graph entities the robot contains directly; their calibration, limits, telemetry and
lifecycle live in the document keyed by entity id, so a promotion never touches the graph.
Callers own the commit (and publish the graph hint after it).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import config_requires, run_guarded
from solus_api.graph.read_scope import current_scope, flags_of
from solus_api.hardware.config import (
    EntityHardwareConfig,
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    PartConfig,
    _leaf_items,
    promote_part,
    with_brain,
    without_brain,
)
from solus_api.hardware.in_graph import admit_wired, put_on, refuse_onto
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
)
from solus_api.services.activity import record_project_activity
from solus_api.services.environment_divergence import recompute_divergences_guarded
from solus_api.services.physical_robots import ownership_edge
from solus_api.services.solus_graph import CONFIG_NODE_KIND, ORIGIN, SolusGraph, lock_project

ROBOT_KIND = "physical_robot"
PART_KIND = "part"
HARDWARE_SUBSECTION = "hardware"  # the environment/hardware cell (docs/api/solus.md §2.2)
CONFIGURES = "configures"
MAX_SPECS = 32

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
    if current_scope(project_id).hides(entity.attrs):  # SOLUSDEV-326: not the reader's to see
        raise APIError(404, "not_found", "Hardware entity not found")
    return entity


async def robot_root(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID
) -> GraphEntity:
    """Only a live, manual, source-less Physical Robot root in THIS project (else 404) that the
    bound reader may see — its onboarder's alone while it is out of the graph (SOLUSDEV-326)."""
    root = await session.get(GraphEntity, robot_id, populate_existing=True)
    if (
        root is None
        or root.project_id != project_id
        or root.deleted_at is not None
        or root.kind != ROBOT_KIND
        or root.origin != ORIGIN
        or root.source_id is not None
        or current_scope(project_id).hides(root.attrs)
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
            SolusEntry.section == SolusSection.ENVIRONMENT,
            SolusEntry.subsection == HARDWARE_SUBSECTION,
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


async def _refuse_held_devices(
    session: AsyncSession,
    project_id: uuid.UUID,
    subject_id: uuid.UUID,
    config: EntityHardwareConfig,
    entry: SolusEntry | None,
) -> None:
    """One config per device project-wide, on every writer (confirm, the PUTs, SOL's field tool, a
    hand-over): a device this write adds that another live robot's stored brains hold is 409 when
    that robot's config has no live binding edge — a backfilled one, which `synchronize_bindings`
    cannot see. A config with binding edges is judged by them there (a historical one frees its
    device)."""
    from solus_api.hardware.bindings import BINDING_RELATION
    from solus_api.hardware.detect import robot_candidates
    from solus_api.hardware.runtime import bound_refs

    previous = config_of(entry) if entry is not None else None
    if isinstance(previous, EntityHardwareConfig):
        had = {brain.device_ref for brain in previous.identity}
    else:
        had = {previous.identity.device_ref} if previous and previous.identity else set()
    added = {brain.device_ref for brain in config.identity if brain.device_ref} - had
    if not added:
        return
    for candidate in await robot_candidates(session, project_id):
        held = added & bound_refs(candidate.config)
        if candidate.robot_entity_id == subject_id or not held:
            continue
        edged = await session.scalar(
            select(GraphEdge.id)
            .join(SolusEntry, SolusEntry.entity_id == GraphEdge.src_id)
            .where(
                SolusEntry.project_id == project_id,
                SolusEntry.configured_entity_id == candidate.robot_entity_id,
                SolusEntry.deleted_at.is_(None),
                GraphEdge.relation_type == BINDING_RELATION,
                GraphEdge.attrs["device_ref"].astext.in_(held),
                GraphEdge.deleted_at.is_(None),
            )
            .limit(1)
        )
        if edged is None:
            raise APIError(
                409,
                "binding_conflict",
                f"{min(held)} is already bound to other hardware in this project; "
                "review its existing binding",
            )


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
        section=SolusSection.ENVIRONMENT,
        subsection=HARDWARE_SUBSECTION,
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
    # SOLUSDEV-326: a config node is seen by whoever sees what it configures.
    node.attrs = {**node.attrs, "configured_entity_id": str(subject.id), **flags_of(subject.attrs)}
    await graph.flush()
    await write_edge(
        session,
        project_id=project_id,
        src_id=node.id,
        dst_id=subject.id,
        relation_type=CONFIGURES,
        origin=ORIGIN,
        confidence=1.0,
        evidence=[],
        created_by=created_by,
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
    named: list[GraphEntity] = []
    if targets:
        scope = current_scope(project_id)
        named = [
            part
            for part in await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(targets),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.kind.in_(PART_KINDS),
                )
                .execution_options(populate_existing=True)
            )
            if not scope.hides(part.attrs)  # SOLUSDEV-326: another member's hidden part is unknown
        ]
        if {part.id for part in named} != targets:
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
    await _refuse_held_devices(session, project_id, subject.id, config, entry)
    await admit_wired(session, project_id, subject, named, created_by)
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
    # SOLUSDEV-320 P5-T7 (solus.md §9): every saved version is one history row.
    await record_project_activity(
        session,
        project_id,
        "config.bumped",
        actor_id=created_by,
        domain=subject.domain.value,
        payload={"entry_id": str(entry.id), "config_version": entry.config_version},
        entity_ids=[subject.id],
    )
    await _derive(session, project_id, subject, entry, config)
    return entry


async def _derive(
    session: AsyncSession,
    project_id: uuid.UUID,
    subject: GraphEntity,
    entry: SolusEntry,
    config: EntityHardwareConfig,
) -> None:
    """What a saved config implies, in the same transaction."""
    # SOLUSDEV-320: each driver this config names (one per brain) → `requires` package nodes.
    node_id = entry.entity_id
    if node_id is not None:
        brains = config.identity
        for driver_id in dict.fromkeys(b.protocol.driver_id for b in brains if b.protocol):
            infer = partial(
                config_requires.infer,
                session,
                project_id,
                config_node_id=node_id,
                driver_id=driver_id,
            )
            await run_guarded(session, project_id, "config_requires", infer)
    # SOLUSDEV-320 P5: a config may add `requires` → the spec and divergences follow.
    await recompute_divergences_guarded(session, project_id)
    if subject.kind == ROBOT_KIND:
        # SOLUSDEV-326: every robot write (routes, SOL, sim changes, imports) keeps its
        # derived topology current — this is the one place that runs it.
        from solus_api.hardware.topology import sync_topology

        await sync_topology(session, project_id, subject.id)
    elif subject.origin == ORIGIN and subject.source_id is None and subject.external_ref is None:
        # SOLUSDEV-326: a part bound to its own board (a lone detected board) is keyed by the
        # board's device ref, so what the board streams under that key lands on the part.
        # ponytail: the first board's ref sticks; re-key here if a part ever trades boards.
        subject.external_ref = next((b.device_ref for b in config.identity if b.device_ref), None)


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
    The v1 document speaks for ONE brain: it merges into the robot's stored brains by device
    ref and never drops another (SOLUSDEV-326); a change v1 cannot express is 409.
    """
    from solus_api.hardware.migration import split_legacy_document

    if config.robot_entity_id != robot.id:
        raise APIError(422, "validation_error", "config.robot_entity_id must be this robot")
    await lock_project(session, project_id)
    _, current = await read_entity_config(session, project_id, robot.id)
    try:
        documents = split_legacy_document(
            config.model_dump(mode="json"), source_namespace=project_id, current=current
        )
    except ValueError:
        raise APIError(
            409,
            "config_upgrade_required",
            "This change to the robot's brains needs its per-entity configuration",
        ) from None
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
            current is not None
            and _same(current, document)
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
    return owner_entry


def _same(current: EntityHardwareConfig, document: EntityHardwareConfig) -> bool:
    """Equal values and the same record on every valued leaf, however the records are keyed —
    an upgraded or re-keyed round trip of an unchanged config is not a new version."""
    values = document.model_dump(mode="json", exclude={"provenance"})
    if current.model_dump(mode="json", exclude={"provenance"}) != values:
        return False
    leaves = [
        path for path, _ in _leaf_items(values) if path not in {"schema_version", "entity_id"}
    ]
    return all(current.provenance_of(path) == document.provenance_of(path) for path in leaves)


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
            if path.split(".")[0] in {"identity", "bus_map", "disambiguated_by"}
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


def brain_refusal(error: ValueError) -> APIError:
    """How an edit to a config's brain list is refused: a result that does not validate (a 17th
    brain, an unknown or circular `via`, an oversize document) says why, 422; `with_brain`'s own
    ValueError — the only brain is unbound, so its implicit rows cannot be named — is a 409."""
    if isinstance(error, ValidationError):
        return APIError(422, "validation_error", error.errors()[0]["msg"])
    return APIError(409, "config_conflict", "Bind this robot's brain before it takes another")


async def hand_over_brain(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    device_ref: str,
    source: GraphEntity,
    target: GraphEntity,
    created_by: uuid.UUID | None,
) -> None:
    """Move one brain, and the rows behind it, from `source`'s config to `target`'s in the
    caller's transaction. The source lets go before the target claims, so one config per
    device project-wide holds throughout — a lone part's board joining a robot."""
    await lock_project(session, project_id)
    given, giving = await read_entity_config(session, project_id, source.id)
    if given is None or giving is None or device_ref not in (b.device_ref for b in giving.identity):
        raise APIError(404, "not_found", "That device is not a brain of this configuration")
    taken, taking = await read_entity_config(session, project_id, target.id)
    try:
        claimed = with_brain(
            taking or EntityHardwareConfig(entity_id=target.id), giving, device_ref
        )
    except ValueError as error:
        raise brain_refusal(error) from None
    await put_entity_config(
        session,
        project_id,
        source,
        without_brain(giving, device_ref),
        expected_version=given.config_version,
        created_by=created_by,
    )
    await put_entity_config(
        session,
        project_id,
        target,
        claimed,
        expected_version=taken.config_version if taken else 0,
        created_by=created_by,
    )


async def _contains(
    session: AsyncSession, project_id: uuid.UUID, parent_id: uuid.UUID, child_id: uuid.UUID
) -> None:
    await write_edge(
        session,
        project_id=project_id,
        src_id=parent_id,
        dst_id=child_id,
        relation_type="contains",
        origin=ORIGIN,
        confidence=1.0,
        evidence=[],
        created_by=None,
    )


async def attach_part(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    name: str,
    attrs: Mapping[str, Any],
    provenance: FieldProvenance,
    external_ref: str | None = None,
) -> GraphEntity:
    """A manual `part` entity the robot contains directly, seen by whoever sees the robot.
    `external_ref` is the telemetry identity (`<device ref>/<address>`) for detected parts;
    authored parts have none."""
    label = " ".join(name.split())
    if not label or len(label) > 512:
        raise APIError(422, "validation_error", "name must be 1-512 characters")
    await lock_project(session, project_id)
    robot = await robot_root(session, project_id, robot.id)  # its keys as they are now
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
            **flags_of(robot.attrs),
            "robot_id": str(robot.id),
            "provenance": provenance.value,
        },
    )
    session.add(part)
    await session.flush()
    await _contains(session, project_id, robot.id, part.id)
    return part


async def create_part(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    *,
    name: str,
    specs: Mapping[str, Any],
    lifecycle: LifecycleState,
    created_by: uuid.UUID | None,
) -> tuple[GraphEntity, SolusEntry]:
    """Author a part: a manual `part` entity the robot contains, plus its config slot."""
    if len(specs) > MAX_SPECS:
        raise APIError(422, "validation_error", f"at most {MAX_SPECS} specs")
    part = await attach_part(
        session,
        project_id,
        robot,
        name=name,
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
    """Parts any live robot owns (`ownership_edge`)."""
    return select(GraphEdge.dst_id).where(ownership_edge(project_id))


async def _own(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    part: GraphEntity,
    actor_id: uuid.UUID | None,
) -> None:
    """The robot contains the part; a manual, source-less part also records its robot and
    takes its visibility (`put_on`; the caller ran `refuse_onto`)."""
    await _contains(session, project_id, robot.id, part.id)
    if part.origin == ORIGIN and part.source_id is None:
        part.attrs = {**part.attrs, "robot_id": str(robot.id)}
        await put_on(session, project_id, robot, part, actor_id)


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
    created_by: uuid.UUID | None,
) -> tuple[list[uuid.UUID], list[uuid.UUID], SolusEntry]:
    """Attach parts already in the graph (From a file) to the robot. A part THIS robot owns
    is skipped; a part another robot owns is a conflict; anything else is 404. A manual,
    source-less part records its robot in `attrs.robot_id`; provider facts are not touched."""
    await lock_project(session, project_id)
    robot = await robot_root(session, project_id, robot.id)  # read fresh under the lock
    wanted = list(dict.fromkeys(entity_ids))
    scope = current_scope(project_id)
    rows = {
        row.id: row
        for row in await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_(wanted),
                GraphEntity.kind.in_(PART_KINDS),
                GraphEntity.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        # SOLUSDEV-326: another member's hidden part is unknown here, never "another robot's".
        if not scope.hides(row.attrs)
    }
    missing = [e for e in wanted if e not in rows]
    if missing:
        raise APIError(404, "not_found", f"{len(missing)} part(s) not found in this project")
    owners = {
        part_id: robot_id
        for robot_id, part_id in await session.execute(
            select(GraphEdge.src_id, GraphEdge.dst_id).where(
                ownership_edge(project_id), GraphEdge.dst_id.in_(wanted)
            )
        )
    }
    for entity_id in wanted:
        if owners.get(entity_id) not in (None, robot.id):
            raise APIError(
                409, "conflict", f"{rows[entity_id].name} already belongs to another robot"
            )
    skipped = [entity_id for entity_id in wanted if owners.get(entity_id) == robot.id]
    attached = [entity_id for entity_id in wanted if entity_id not in skipped]
    manual = [rows[e] for e in attached if rows[e].origin == ORIGIN and rows[e].source_id is None]
    await refuse_onto(session, project_id, robot, manual)
    for entity_id in attached:
        await _own(session, project_id, robot, rows[entity_id], created_by)
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
