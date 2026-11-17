"""Validated, deterministic v1 extraction. Private paths are never read or retained."""

from __future__ import annotations

import uuid
from typing import Any

from solus_api.hardware.config import (
    EntityHardwareConfig,
    HardwareConfig,
    PortableTransportBinding,
    is_private_source,
    lookup,
    pin_rows,
)

_EMPTY_BRAIN = {"kind": "host", "binding": None, "via": None, "protocol": None}


def _source(source: str | None, subject: uuid.UUID) -> str | None:
    if source is None or not is_private_source(source):
        return source
    return f"source:{uuid.uuid5(subject, source)}"


def _ref(binding: dict[str, Any] | None) -> str | None:
    return PortableTransportBinding.model_validate(binding).device_ref if binding else None


def _brain_index(brains: list[dict[str, Any]], binding: dict[str, Any] | None) -> int:
    """The stored brain a v1 identity speaks for: the one with its device, else the first
    still waiting for a device, else a new one; a document without an identity speaks for
    the first brain (the aggregate's own)."""
    ref = _ref(binding)
    if ref is None and brains:
        return 0
    for index, brain in enumerate(brains):
        if ref is not None and _ref(brain["binding"]) == ref:
            return index
    unbound = [index for index, brain in enumerate(brains) if brain["binding"] is None]
    if ref is not None and unbound:
        return unbound[0]
    brains.append(dict(_EMPTY_BRAIN))
    return len(brains) - 1


def _rekeyed(records: dict[str, Any], index: int) -> dict[str, Any]:
    """v1 identity/protocol records under brain `index` (a prefix stays a prefix)."""
    rekeyed = {}
    for path, record in records.items():
        head, _, rest = path.partition(".")
        field = "binding" if head == "identity" else "protocol"
        rekeyed[f"identity.{index}.{field}" + (f".{rest}" if rest else "")] = record
    return rekeyed


def _merged_brains(
    current: EntityHardwareConfig | None,
    binding: dict[str, Any] | None,
    protocol: dict[str, Any] | None,
    own: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    """`current`'s brains with the v1 one merged in, their records, and its index (0 when the
    document names no brain). A lone brain left with nothing is no brain."""
    brains = [brain.model_dump(mode="json") for brain in current.identity] if current else []
    kept = {
        path: record.model_dump(mode="json")
        for path, record in (current.provenance.items() if current else ())
        if path.split(".")[0] == "identity"
    }
    if binding is None and protocol is None and not brains:
        return [], {}, 0
    index = _brain_index(brains, binding)
    new = current is None or index >= len(current.identity)
    brains[index] = {**brains[index], "binding": binding, "protocol": protocol}
    stale = (f"identity.{index}.binding", f"identity.{index}.protocol")
    kept = {path: record for path, record in kept.items() if not path.startswith(stale)}
    kept.update(_rekeyed(own, index))
    kind = lookup(own, "identity.kind") or lookup(own, "protocol.driver_id")
    if new and lookup(kept, f"identity.{index}.kind") is None and kind is not None:
        kept[f"identity.{index}.kind"] = kind
    if brains == [_EMPTY_BRAIN]:
        return [], {}, 0
    return brains, kept, index


def merge_brain(
    current: EntityHardwareConfig | None, portable: dict[str, Any], records: dict[str, Any]
) -> dict[str, Any]:
    """The owner's `identity`, `bus_map` and `provenance` once the v1 document's ONE brain
    (its identity and protocol) joins `current`'s brains, keyed by device ref; every other
    brain is kept. Rows the document leaves implicit sit on its brain and name it once there
    are several (ValueError when that brain is unbound and so cannot be named)."""
    binding = portable["identity"]
    if binding is not None:
        binding = {key: value for key, value in binding.items() if key != "last_seen_path"}
    heads = {"identity", "protocol"}
    own = {path: record for path, record in records.items() if path.split(".")[0] in heads}
    provenance = {path: record for path, record in records.items() if path not in own}
    brains, kept, index = _merged_brains(current, binding, portable["protocol"], own)
    rows = [dict(row) for row in portable["bus_map"]]
    if len(brains) > 1 and any(row.get("brain") is None for row in rows):
        ref = _ref(brains[index]["binding"])
        if ref is None:
            raise ValueError("rows on an unbound brain need it to be the robot's only brain")
        pin_rows({"bus_map": rows, "provenance": provenance}, ref)
    return {"identity": brains, "bus_map": rows, "provenance": {**provenance, **kept}}


def split_legacy_document(
    document: dict[str, Any],
    *,
    source_namespace: uuid.UUID | None = None,
    current: EntityHardwareConfig | None = None,
) -> dict[uuid.UUID, EntityHardwareConfig]:
    """Preserve every part UUID and valued field; paths become relinkable opaque references.
    The owner keeps `current`'s brains with the document's one brain merged in (`merge_brain`)."""
    legacy = HardwareConfig.model_validate(document)
    owner = legacy.robot_entity_id
    source_scope = source_namespace or owner
    portable = legacy.model_dump(mode="json")
    records = {
        path: {"by": record.by.value, "source": _source(record.source, source_scope)}
        for path, record in legacy.provenance.items()
        if not path.startswith(("parts", "firmware", "identity.last_seen_path"))
    }
    owner_document: dict[str, Any] = {
        "schema_version": 2,
        "entity_id": owner,
        "disambiguated_by": portable["disambiguated_by"],
        **merge_brain(current, portable, records),
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
