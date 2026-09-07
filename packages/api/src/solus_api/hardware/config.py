"""The HardwareConfig document (R5, docs/api/hardware.md §2; ADR-034 amendment 2026-09-06).

One document per Physical Robot, stored as the `.solus` Hardware-configs entry payload and
validated here on every write. Code is Solus's, specifics are the user's: which transport
identity is which robot, which driver with which parameters, which address is which part, this
robot's calibration — all live in the document, every valued leaf with a provenance record.

Shared code: no product or vendor is named here. A driver id is DATA in `protocol.driver_id`.
"""

from __future__ import annotations

import enum
import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, Field, model_validator

from solus_api.connectors.contracts import FrozenModel

MAX_DOCUMENT_BYTES: Final = 64 * 1024
MAX_BUS_ENTRIES: Final = 256
MAX_PARTS: Final = 256
MAX_PARAMS: Final = 32
MAX_VALUES: Final = 64
MAX_CHANNELS: Final = 64
PART_SEPARATOR: Final = "/"
_RESERVED_KEYS: Final = frozenset({"schema_version", "robot_entity_id", "provenance"})

Scalar = str | int | float | bool | None


class FieldProvenance(enum.StrEnum):
    """Who set a field. Layers apply library → repo → user → detected; SOL writes take the user
    slot; the record names who WON, never a merge of several."""

    LIBRARY = "library"
    REPO = "repo"
    USER = "user"
    SOL = "sol"
    DETECTED = "detected"


class ProvenanceRecord(FrozenModel):
    by: FieldProvenance
    source: str | None = Field(default=None, max_length=512)  # e.g. a calibration file path


class TransportKind(enum.StrEnum):
    USB_SERIAL = "usb_serial"
    USB_CAN = "usb_can"
    BLE = "ble"
    BT_CLASSIC = "bt_classic"
    WIFI = "wifi"
    ETHERNET = "ethernet"
    ROS2 = "ros2"


#: Device-ref prefixes are TRANSPORTS. A driver never appears in an identity.
TRANSPORT_PREFIX: Final[dict[TransportKind, str]] = {
    TransportKind.USB_SERIAL: "usb",
    TransportKind.USB_CAN: "can",
    TransportKind.BLE: "ble",
    TransportKind.BT_CLASSIC: "bt",
    TransportKind.WIFI: "ip",
    TransportKind.ETHERNET: "ip",
    TransportKind.ROS2: "ros2",
}


def part_ref(device_ref: str, address: str) -> str:
    """`<device ref>/<address>` — the graph `external_ref` of one part on a bus."""
    return f"{device_ref}{PART_SEPARATOR}{address}"


class TransportBinding(FrozenModel):
    """Binding identity: USB serial / BT address / MAC / IP. `last_seen_path` is informational
    only — a port path is never binding (tty numbering swaps on re-enumeration)."""

    kind: TransportKind
    binding: str = Field(min_length=1, max_length=128, pattern=r"^[^/\s]+$")
    vid: int | None = Field(default=None, ge=0, le=0xFFFF)
    pid: int | None = Field(default=None, ge=0, le=0xFFFF)
    last_seen_path: str | None = Field(default=None, max_length=512)

    @property
    def device_ref(self) -> str:
        return f"{TRANSPORT_PREFIX[self.kind]}:{self.binding}"

    def identity_key(self) -> tuple[str, str]:
        return (TRANSPORT_PREFIX[self.kind], self.binding)


class ProtocolBinding(FrozenModel):
    """The driver plugin by id plus its parameters — in config, not code."""

    driver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    params: dict[str, Scalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(self.params) > MAX_PARAMS:
            raise ValueError(f"at most {MAX_PARAMS} driver parameters")
        return self


class BusMapEntry(FrozenModel):
    """`{protocol, address, part, model}` — servo ids, CAN node ids, autopilot
    system:component ids all fit one shape. Never a `servo_id` field."""

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


_UNIT_FOR_MODE: Final[dict[CalibrationMode, str | None]] = {
    CalibrationMode.DEGREES: "deg",
    CalibrationMode.RANGE_0_100: "%",
    CalibrationMode.RANGE_M100_100: "%",
    CalibrationMode.LINEAR: "mm",
    CalibrationMode.RAW: None,
}


def unit_for_mode(mode: CalibrationMode | None) -> str | None:
    """Telemetry units follow the calibration mode: the same actuator model reports degrees on a
    joint and percent on a gripper."""
    return None if mode is None else _UNIT_FOR_MODE[mode]


class PartCalibration(FrozenModel):
    mode: CalibrationMode | None = None
    values: dict[str, float | int] = Field(default_factory=dict)
    source: str | None = Field(default=None, max_length=512)
    owner: Literal["repo", "solus"] = "solus"  # who is authoritative — never silently diverge

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


def _leaf_items(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Dotted paths of every VALUED leaf (None and empty containers carry no provenance)."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _leaf_items(item, f"{prefix}{key}." if prefix or key else f"{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaf_items(item, f"{prefix}{index}.")
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
    #: dotted path (a prefix covers everything beneath it; longest prefix wins) → who set it
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
        missing = [path for path in self.leaf_paths() if self._lookup(path) is None]
        if missing:
            raise ValueError("provenance missing for " + ", ".join(missing[:8]))
        return self

    def leaf_paths(self) -> list[str]:
        document = {
            key: value
            for key, value in self.model_dump(mode="json").items()
            if key not in _RESERVED_KEYS
        }
        return [path for path, _ in _leaf_items(document)]

    def _lookup(self, path: str) -> ProvenanceRecord | None:
        segments = path.split(".")
        for length in range(len(segments), 0, -1):
            record = self.provenance.get(".".join(segments[:length]))
            if record is not None:
                return record
        return None

    def provenance_of(self, path: str) -> ProvenanceRecord:
        record = self._lookup(path)
        if record is None:
            raise KeyError(path)
        return record


class ConfigLayer(BaseModel):
    """One source's contribution: a partial document plus who it came from."""

    by: FieldProvenance
    document: dict[str, Any]
    source: str | None = None


def _merge_into(target: dict[str, Any], layer: Mapping[str, Any]) -> None:
    for key, value in layer.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge_into(target[key], value)
        else:
            target[key] = json.loads(json.dumps(value))  # lists and scalars replace whole


def merge_layers(robot_entity_id: uuid.UUID, layers: Sequence[ConfigLayer]) -> HardwareConfig:
    """library → repo → user → detected, later overriding earlier; provenance records the
    winner per valued leaf (a replaced list forgets its stale indices)."""
    merged: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for layer in layers:
        document = {k: v for k, v in layer.document.items() if k not in _RESERVED_KEYS}
        _merge_into(merged, document)
        for path, _ in _leaf_items(document):
            provenance[path] = {"by": layer.by.value, "source": layer.source}
    live = {path for path, _ in _leaf_items(merged)}
    return HardwareConfig.model_validate(
        {
            **merged,
            "robot_entity_id": robot_entity_id,
            "provenance": {path: rec for path, rec in provenance.items() if path in live},
        }
    )


def promote_part(
    config: HardwareConfig, part_entity_id: str, state: LifecycleState
) -> HardwareConfig:
    """A new document with the part promoted (the entity id and its edges are untouched)."""
    if part_entity_id not in config.parts:
        raise KeyError(part_entity_id)
    document = config.model_dump(mode="json")
    document["parts"][part_entity_id]["lifecycle"] = state.value
    document["provenance"][f"parts.{part_entity_id}.lifecycle"] = {
        "by": FieldProvenance.USER.value,
        "source": None,
    }
    return HardwareConfig.model_validate(document)
