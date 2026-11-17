"""SOLUSDEV-326 frozen copy of the v2 hardware schema and its legacy splitter.

`hardware_config_backfill.py` (revision a26000000002) validates and splits stored payloads
with exactly these models: one `identity`, one top-level `protocol`, bus rows without a brain.
The live `solus_api.hardware.config` moved on (an identity list keyed by brain), so this copy
pins what the revision meant when it shipped. Loaded by path, never imported from live code;
it imports nothing from `solus_api`. Do not edit to follow the live schema.
"""

from __future__ import annotations

import enum
import json
import math
import re
import uuid
from collections.abc import Iterator, Mapping
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_DOCUMENT_BYTES: Final = 64 * 1024
MAX_BUS_ENTRIES: Final = 256
MAX_PARTS: Final = 256
MAX_PARAMS: Final = 32
MAX_VALUES: Final = 64
MAX_CHANNELS: Final = 64
_RESERVED_KEYS: Final = frozenset({"schema_version", "robot_entity_id", "provenance"})

Scalar = str | int | float | bool | None


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldProvenance(enum.StrEnum):
    LIBRARY = "library"
    REPO = "repo"
    USER = "user"
    SOL = "sol"
    DETECTED = "detected"


class ProvenanceRecord(FrozenModel):
    by: FieldProvenance
    source: str | None = Field(default=None, max_length=512)


class TransportKind(enum.StrEnum):
    USB_SERIAL = "usb_serial"
    USB_CAN = "usb_can"
    BLE = "ble"
    BT_CLASSIC = "bt_classic"
    WIFI = "wifi"
    ETHERNET = "ethernet"
    ROS2 = "ros2"


TRANSPORT_PREFIX: Final[dict[TransportKind, str]] = {
    TransportKind.USB_SERIAL: "usb",
    TransportKind.USB_CAN: "can",
    TransportKind.BLE: "ble",
    TransportKind.BT_CLASSIC: "bt",
    TransportKind.WIFI: "ip",
    TransportKind.ETHERNET: "ip",
    TransportKind.ROS2: "ros2",
}


class TransportBinding(FrozenModel):
    kind: TransportKind
    binding: str = Field(min_length=1, max_length=128, pattern=r"^[^/\s]+$")
    vid: int | None = Field(default=None, ge=0, le=0xFFFF)
    pid: int | None = Field(default=None, ge=0, le=0xFFFF)
    last_seen_path: str | None = Field(default=None, max_length=512)

    @property
    def device_ref(self) -> str:
        return f"{TRANSPORT_PREFIX[self.kind]}:{self.binding}"


class ProtocolBinding(FrozenModel):
    driver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    params: dict[str, Scalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(self.params) > MAX_PARAMS:
            raise ValueError(f"at most {MAX_PARAMS} driver parameters")
        return self


class BusMapEntry(FrozenModel):
    protocol: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    part_entity_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=128)


class LifecycleState(enum.StrEnum):
    PLANNED = "planned"
    ORDERED = "ordered"
    RECEIVED = "received"
    INSTALLED = "installed"
    LIVE = "live"


class CalibrationMode(enum.StrEnum):
    DEGREES = "degrees"
    RANGE_0_100 = "range_0_100"
    RANGE_M100_100 = "range_m100_100"
    LINEAR = "linear"
    RAW = "raw"


class PartCalibration(FrozenModel):
    mode: CalibrationMode | None = None
    values: dict[str, float | int] = Field(default_factory=dict)
    source: str | None = Field(default=None, max_length=512)
    owner: Literal["repo", "solus"] = "solus"

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(self.values) > MAX_VALUES:
            raise ValueError(f"at most {MAX_VALUES} calibration values")
        return self


class PartLimits(FrozenModel):
    values: dict[str, float | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(self.values) > MAX_VALUES:
            raise ValueError(f"at most {MAX_VALUES} limit values")
        return self


class TelemetryChannel(FrozenModel):
    name: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=32)


class PartConfig(FrozenModel):
    calibration: PartCalibration | None = None
    limits: PartLimits | None = None
    telemetry: list[TelemetryChannel] = Field(default_factory=list, max_length=MAX_CHANNELS)
    firmware: dict[str, Scalar] = Field(default_factory=dict)
    lifecycle: LifecycleState = LifecycleState.PLANNED


def is_private_source(value: str) -> bool:
    return value.startswith(("/", "\\", "~/", "~\\", "file:")) or bool(
        re.match(r"^[a-zA-Z]:[\\/]", value)
    )


class PortableTransportBinding(FrozenModel):
    kind: TransportKind
    binding: str = Field(min_length=1, max_length=128, pattern=r"^[^/\s]+$")
    vid: int | None = Field(default=None, ge=0, le=0xFFFF)
    pid: int | None = Field(default=None, ge=0, le=0xFFFF)

    @property
    def device_ref(self) -> str:
        return f"{TRANSPORT_PREFIX[self.kind]}:{self.binding}"


def _lookup(provenance: Mapping[str, ProvenanceRecord], path: str) -> ProvenanceRecord | None:
    segments = path.split(".")
    for length in range(len(segments), 0, -1):
        record = provenance.get(".".join(segments[:length]))
        if record is not None:
            return record
    return None


class ConfigDraft(FrozenModel):
    schema_version: Literal[2] = 2
    component: PartConfig | None = None
    identity: PortableTransportBinding | None = None
    protocol: ProtocolBinding | None = None
    bus_map: list[BusMapEntry] = Field(default_factory=list, max_length=MAX_BUS_ENTRIES)
    disambiguated_by: Literal["user"] | None = None
    provenance: dict[str, ProvenanceRecord] = Field(default_factory=dict, max_length=2048)

    def provenance_of(self, path: str) -> ProvenanceRecord:
        record = _lookup(self.provenance, path)
        if record is None:
            raise KeyError(path)
        return record

    @model_validator(mode="after")
    def _portable_complete(self) -> Self:
        document = self.model_dump(mode="json")
        if len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
        leaves = list(
            leaf_items(
                {
                    key: value
                    for key, value in document.items()
                    if key not in {"schema_version", "entity_id", "provenance"}
                }
            )
        )
        missing = [path for path, _ in leaves if _lookup(self.provenance, path) is None]
        if missing:
            raise ValueError("provenance missing for " + ", ".join(missing[:8]))
        if any(isinstance(value, float) and not math.isfinite(value) for _, value in leaves):
            raise ValueError("configuration numbers must be finite")
        sources = [record.source for record in self.provenance.values()]
        if self.component and self.component.calibration:
            sources.append(self.component.calibration.source)
        if any(
            source is not None
            and (is_private_source(source) or any(ord(ch) < 32 or ord(ch) == 127 for ch in source))
            for source in sources
        ):
            raise ValueError("source must be a portable reference, never a private path")
        endpoints = [(entry.protocol, entry.address) for entry in self.bus_map]
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("duplicate bus endpoint")
        return self


class EntityHardwareConfig(ConfigDraft):
    entity_id: uuid.UUID


def leaf_items(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Dotted paths of every VALUED leaf (None and empty containers carry no provenance)."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from leaf_items(item, f"{prefix}{key}." if prefix or key else f"{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaf_items(item, f"{prefix}{index}.")
    elif value is not None:
        yield prefix.rstrip("."), value


class HardwareConfig(FrozenModel):
    schema_version: Literal[1] = 1
    robot_entity_id: uuid.UUID
    identity: TransportBinding | None = None
    protocol: ProtocolBinding | None = None
    bus_map: list[BusMapEntry] = Field(default_factory=list, max_length=MAX_BUS_ENTRIES)
    parts: dict[str, PartConfig] = Field(default_factory=dict)
    firmware: dict[str, Scalar] = Field(default_factory=dict)
    disambiguated_by: Literal["user"] | None = None
    provenance: dict[str, ProvenanceRecord] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if len(self.parts) > MAX_PARTS:
            raise ValueError(f"at most {MAX_PARTS} parts")
        for key in self.parts:
            try:
                uuid.UUID(key)
            except ValueError:
                raise ValueError(f"part key {key!r} is not an entity id") from None
        if len(json.dumps(self.model_dump(mode="json"))) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
        missing = [path for path in self.leaf_paths() if _lookup(self.provenance, path) is None]
        if missing:
            raise ValueError("provenance missing for " + ", ".join(missing[:8]))
        return self

    def leaf_paths(self) -> list[str]:
        document = {
            key: value
            for key, value in self.model_dump(mode="json").items()
            if key not in _RESERVED_KEYS
        }
        return [path for path, _ in leaf_items(document)]

    def provenance_of(self, path: str) -> ProvenanceRecord:
        record = _lookup(self.provenance, path)
        if record is None:
            raise KeyError(path)
        return record


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
    """Keep connection context when old aggregates included the owner in parts; contradictory
    firmware copies need review, never a silent winner."""
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
