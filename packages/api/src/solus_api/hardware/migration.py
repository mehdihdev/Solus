"""Validated, deterministic v1 extraction. Private paths are never read or retained."""

from __future__ import annotations

import uuid
from typing import Any

from solus_api.hardware.config import EntityHardwareConfig, HardwareConfig, is_private_source


def _source(source: str | None, subject: uuid.UUID) -> str | None:
    if source is None or not is_private_source(source):
        return source
    return f"source:{uuid.uuid5(subject, source)}"


def split_legacy_document(
    document: dict[str, Any], *, source_namespace: uuid.UUID | None = None
) -> dict[uuid.UUID, EntityHardwareConfig]:
    """Preserve every part UUID and valued field; paths become relinkable opaque references."""
    legacy = HardwareConfig.model_validate(document)
    owner = legacy.robot_entity_id
    source_scope = source_namespace or owner
    portable = legacy.model_dump(mode="json")
    identity = portable["identity"]
    if identity is not None:
        identity.pop("last_seen_path", None)
    owner_document: dict[str, Any] = {
        "schema_version": 2,
        "entity_id": owner,
        "identity": identity,
        "protocol": portable["protocol"],
        "bus_map": portable["bus_map"],
        "disambiguated_by": portable["disambiguated_by"],
        "provenance": {
            path: {"by": record.by.value, "source": _source(record.source, source_scope)}
            for path, record in legacy.provenance.items()
            if not path.startswith(("parts", "firmware", "identity.last_seen_path"))
        },
    }
    if portable["firmware"]:
        owner_document["component"] = {"firmware": portable["firmware"]}
        owner_document["provenance"]["component.lifecycle"] = {
            "by": "user",
            "source": "migration:legacy",
        }
        for key, value in portable["firmware"].items():
            if value is None:
                continue
            record = legacy.provenance_of(f"firmware.{key}")
            owner_document["provenance"][f"component.firmware.{key}"] = {
                "by": record.by.value,
                "source": _source(record.source, source_scope),
            }
    output = {owner: EntityHardwareConfig.model_validate(owner_document)}
    for raw_id, component in portable["parts"].items():
        part_id = uuid.UUID(raw_id)
        provenance = {}
        prefix = f"parts.{raw_id}."
        for path in legacy.leaf_paths():
            if path.startswith(prefix):
                record = legacy.provenance_of(path)
                provenance[f"component.{path.removeprefix(prefix)}"] = {
                    "by": record.by.value,
                    "source": _source(record.source, source_scope),
                }
        if component.get("calibration"):
            component["calibration"]["source"] = _source(
                component["calibration"].get("source"), source_scope
            )
        if part_id == owner:
            _merge_owner_component(owner_document, component, provenance)
            output[owner] = EntityHardwareConfig.model_validate(owner_document)
        else:
            output[part_id] = EntityHardwareConfig.model_validate(
                {
                    "schema_version": 2,
                    "entity_id": part_id,
                    "component": component,
                    "provenance": provenance,
                }
            )
    return output


def _merge_owner_component(
    owner: dict[str, Any], component: dict[str, Any], provenance: dict[str, Any]
) -> None:
    """Keep connection context when old aggregates included the owner in parts.

    Equal firmware copies are harmless; top-level attribution remains the runtime
    firmware attribution. Contradictory values need review, never a silent winner.
    """
    top_firmware = owner.get("component", {}).get("firmware", {})
    part_firmware = component["firmware"]
    if any(
        key in part_firmware and part_firmware[key] != value for key, value in top_firmware.items()
    ):
        raise ValueError("Conflicting owner firmware copies require migration review")
    owner["component"] = {**component, "firmware": {**part_firmware, **top_firmware}}
    top_provenance = {
        path: record
        for path, record in owner["provenance"].items()
        if path.startswith("component.firmware.")
    }
    owner["provenance"].update(provenance)
    owner["provenance"].update(top_provenance)
