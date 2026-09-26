"""Capture accepted graph identity, never infer a part from a device's label."""

import json
import math
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import current_scope
from solus_api.hardware.config import PartConfig, is_private_source
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import configuration_entries, robot_root
from solus_api.livebench.focus_scope import focus_entity_ids
from solus_api.livebench.runs.models import PartEvidence, RevisionSnapshot, RunManifest
from solus_api.livebench.sessions import BenchSessionOut
from solus_api.models import GraphEntity, Source, SourceStatus, utcnow

_SENSITIVE = ("secret", "token", "password", "credential", "grant", "machine_id", "local_root")
_PATH = re.compile(r"(^|[\s\"'=])(?:/|~[/\\]|[A-Za-z]:[/\\]|file:)")


def _portable(value: Any, depth: int = 0) -> Any:
    if depth > 20:
        raise ValueError("snapshot nesting exceeds limit")
    if isinstance(value, dict):
        if len(value) > 2048:
            raise ValueError("snapshot object exceeds limit")
        return {
            str(key): _portable(item, depth + 1)
            for key, item in value.items()
            if not any(word in str(key).lower() for word in _SENSITIVE)
        }
    if isinstance(value, list):
        if len(value) > 256:
            raise ValueError("snapshot array exceeds limit")
        return [_portable(item, depth + 1) for item in value]
    if isinstance(value, str):
        if len(value) > 4096:
            raise ValueError("snapshot text exceeds limit")
        return "[local path omitted]" if is_private_source(value) or _PATH.search(value) else value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("invalid snapshot value")


def portable_json(value: Any) -> str:
    data = json.dumps(_portable(value), allow_nan=False)
    if len(data.encode()) > 65536:
        raise ValueError("snapshot exceeds size limit")
    return data


def _text(value: Any) -> str | None:
    return (
        value
        if isinstance(value, str)
        and 0 < len(value) <= 512
        and not is_private_source(value)
        and not _PATH.search(value)
        else None
    )


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except OverflowError:
            pass
    return None


def part_evidence(entity: GraphEntity, config: PartConfig | None) -> PartEvidence:
    attrs = entity.attrs or {}
    specs = attrs.get("specs", {})
    rating = _number(specs.get("stall_current_a")) if isinstance(specs, dict) else None
    evidence = PartEvidence(
        entity_id=entity.id,
        name=entity.name or "Unnamed part",
        device_id=entity.external_ref or str(entity.id),
        stall_current_a=rating if rating and rating > 0 else None,
        code_site=_text(attrs.get("code_site")),
        cad_revision=_text(attrs.get("cad_revision")),
    )
    if config is None:
        return evidence
    roles: dict[str, list[tuple[str, str | None]]] = {"position": [], "current": [], "command": []}
    for channel in config.telemetry:
        suffix = channel.name.rsplit(".", 1)[-1]
        role = "command" if suffix == "commanded_position" else suffix
        if role in roles:
            roles[role].append((channel.name, channel.unit))
    for role, channels in roles.items():
        if len(channels) != 1:
            continue
        name, unit = channels[0]
        setattr(evidence, f"{role}_signal", name)
        if role == "position":
            evidence.position_unit = unit
    if config.limits and evidence.position_unit:
        unit = evidence.position_unit
        evidence.position_min = _number(config.limits.values.get(f"position_min_{unit}"))
        evidence.position_max = _number(config.limits.values.get(f"position_max_{unit}"))
    return evidence


async def snapshot(
    session: AsyncSession, project_id: UUID, robot_id: UUID, bench: BenchSessionOut
) -> RunManifest:
    await robot_root(session, project_id, robot_id)
    ids = await focus_entity_ids(session, project_id, robot_id)
    if len(ids) > 256:
        raise APIError(422, "snapshot_too_large", "Robot topology exceeds the run snapshot limit")
    entities = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_(ids),
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    configs = await configuration_entries(session, project_id, list(ids))
    accepted_devices = {entity.external_ref for entity in entities if entity.external_ref}
    # Runtime config supplies confirmed bus-part associations even when the
    # additive visual topology has not yet been populated for an old robot.
    runtime = await resolve_runtime_config(session, project_id, robot_id)
    if runtime.identity is not None:
        accepted_devices.add(runtime.identity.device_ref)
    components = dict(runtime.parts)
    for target in entities:
        config = await resolve_runtime_config(session, project_id, target.id)
        components.update(config.parts)
        if config.identity is not None:
            accepted_devices.add(config.identity.device_ref)
    selected = str((bench.device or {}).get("device_ref") or "")
    if not selected:
        serial = (bench.device or {}).get("serial_number")
        selected = f"usb:{serial}" if serial else ""
    if selected not in accepted_devices and not (set(bench.device_ids) & accepted_devices):
        raise APIError(404, "not_found", "Session does not match this robot's accepted identity")
    parts = [
        part_evidence(entity, components.get(str(entity.id)))
        for entity in entities
        if entity.kind == "part" and entity.external_ref
    ]
    snapshots = [
        RevisionSnapshot(
            entity_id=entity.id,
            kind=entity.kind,
            name=entity.name or "Unnamed",
            source_id=entity.source_id,
            revision=str(entity.version),
            data=portable_json(
                {
                    key: value
                    for key, value in (entity.attrs or {}).items()
                    if key
                    in {"specs", "code_site", "cad_revision", "microversion", "model_id", "units"}
                }
            ),
        )
        for entity in entities
    ]
    for entry in configs:
        if entry.configured_entity_id is None:
            continue
        snapshots.append(
            RevisionSnapshot(
                entity_id=entry.configured_entity_id,
                kind="hardware_config",
                name="Accepted hardware configuration",
                revision=str(entry.config_version),
                data=portable_json(entry.payload),
            )
        )
    return RunManifest(robot_id=robot_id, started_at=utcnow(), parts=parts, snapshots=snapshots)


async def validate_references(session: AsyncSession, project_id: UUID, run: RunManifest) -> None:
    """Imported metadata cannot reference another project's identities."""
    await robot_root(session, project_id, run.robot_id)
    accepted = await focus_entity_ids(session, project_id, run.robot_id)
    runtime = await resolve_runtime_config(session, project_id, run.robot_id)
    accepted.update(UUID(key) for key in runtime.parts)
    part_ids = {part.entity_id for part in run.parts}
    actual_parts = set(
        await session.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_(part_ids),
                GraphEntity.kind == "part",
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    if not part_ids <= accepted or actual_parts != part_ids:
        raise APIError(404, "not_found", "Part does not belong to this robot")
    source_ids = {item.source_id for item in run.snapshots if item.source_id is not None}
    if source_ids:
        allowed_sources = set(
            await session.scalars(
                select(Source.id).where(
                    Source.project_id == project_id,
                    Source.id.in_(source_ids),
                    Source.status != SourceStatus.DISCONNECTED,
                )
            )
        )
        if source_ids != allowed_sources:
            raise APIError(404, "not_found", "Run source reference not found")
    ids = part_ids | {item.entity_id for item in run.snapshots}
    if ids:
        available = set(
            await session.scalars(
                select(GraphEntity.id).where(
                    current_scope(project_id).entity_predicate(),
                    GraphEntity.id.in_(ids),
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
        if available != ids:
            raise APIError(404, "not_found", "Run graph reference not found")


def portable_manifest(run: RunManifest) -> RunManifest:
    """Drop private local paths from imported metadata before project filing."""
    result = run.model_copy(deep=True)
    for item in result.snapshots:
        if item.data is not None:
            try:
                item.data = portable_json(json.loads(item.data))
            except (ValueError, RecursionError):
                raise ValueError("invalid snapshot metadata") from None
    for part in result.parts:
        part.code_site = _text(part.code_site)
        part.cad_revision = _text(part.cad_revision)
    return result
