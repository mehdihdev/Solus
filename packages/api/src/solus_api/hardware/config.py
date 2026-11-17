"""The HardwareConfig document (R5, docs/api/hardware.md §2; ADR-034 amendment 2026-09-06).

One document per Physical Robot, stored as the `.solus` Hardware-configs entry payload and
validated here on every write. Code is Solus's, specifics are the user's: which transport
identity is which robot, which driver with which parameters, which address is which part, this
robot's calibration — all live in the document, every valued leaf with a provenance record.

A stored (v2) config lists its brains (SOLUSDEV-326): `identity` is a list of `BrainIdentity`
and each bus row names the brain it sits behind. The driver input (v1 `HardwareConfig`) keeps
exactly one identity; the runtime projects one v1 document per brain.

Shared code: no product or vendor is named here. A driver id is DATA in `protocol.driver_id`.
"""

from __future__ import annotations

import enum
import json
import math
import re
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
MAX_BRAINS: Final = 16
PART_SEPARATOR: Final = "/"
_RESERVED_KEYS: Final = frozenset({"schema_version", "robot_entity_id", "provenance"})
#: A device ref: `<transport prefix>:<binding>` (a binding never holds `/` or whitespace).
DEVICE_REF_PATTERN: Final = r"^[a-z0-9]+:[^/\s]+$"

Scalar = str | int | float | bool | None
BrainKind = Literal["host", "mcu", "onboard"]


def lookup[R](provenance: Mapping[str, R], path: str) -> R | None:
    """The record covering `path`: the longest dotted prefix that has one."""
    segments = path.split(".")
    for length in range(len(segments), 0, -1):
        record = provenance.get(".".join(segments[:length]))
        if record is not None:
            return record
    return None


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
    system:component ids all fit one shape. Never a `servo_id` field.

    `brain` is the device ref of the brain the row sits behind (`None` = the config's only
    brain). A per-brain driver document never carries one, so its dump omits the key and the
    v1 driver input reads exactly as before."""

    protocol: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    part_entity_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=128)
    brain: str | None = Field(
        default=None,
        max_length=160,
        pattern=DEVICE_REF_PATTERN,
        exclude_if=lambda value: value is None,
    )


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


#: How the Live Bench draws a channel (SOLUSDEV-326); `plot`, the line chart, is the default.
ChannelDisplay = Literal["plot", "angle", "orientation", "video", "scan", "points", "state", "text"]


class ChannelRange(FrozenModel):
    """A channel's DISPLAY range, in its unit: what the chart spans at least. Never a motion
    bound — envelopes and limits keep their own precedence."""

    min: float = Field(allow_inf_nan=False)
    max: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min < self.max:
            raise ValueError("a display range needs min below max")
        return self


class TelemetryChannel(FrozenModel):
    """A declared signal. `range` and `display` are optional presentation (SOLUSDEV-326);
    `display` defaults to `plot` and is never null. An absent range and a `plot` display are left
    out of dumps, so a plain channel reads, digests and asks for provenance exactly as before."""

    name: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=32)
    range: ChannelRange | None = Field(default=None, exclude_if=lambda value: value is None)
    display: ChannelDisplay = Field(default="plot", exclude_if=lambda value: value == "plot")

    def presentation(self) -> dict[str, Any]:
        """What the Live Bench draws differently from a plain plot (`{}` for a default channel):
        the `channel_display` device fact (telemetry-packet.md §2a)."""
        return self.model_dump(mode="json", include={"range", "display"})


class PartConfig(FrozenModel):
    calibration: PartCalibration | None = None
    limits: PartLimits | None = None
    telemetry: list[TelemetryChannel] = Field(default_factory=list, max_length=MAX_CHANNELS)
    firmware: dict[str, Scalar] = Field(default_factory=dict)
    lifecycle: LifecycleState = LifecycleState.PLANNED


def is_private_source(value: str) -> bool:
    """Host-independent private source detection; never open paths during validation."""
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


class BrainIdentity(FrozenModel):
    """One brain of a stored config: what it is (`kind`), how this host reaches it (`binding`,
    absent until a device is bound), the brain of this config it is reached through (`via`, a
    device ref) and its driver (`protocol`)."""

    kind: BrainKind = "host"
    binding: PortableTransportBinding | None = None
    via: str | None = Field(default=None, max_length=160, pattern=DEVICE_REF_PATTERN)
    protocol: ProtocolBinding | None = None

    @property
    def device_ref(self) -> str | None:
        return self.binding.device_ref if self.binding is not None else None


def _brain_path(path: str) -> str:
    """A pre-SOLUSDEV-326 record path under the one brain it now describes."""
    head, _, rest = path.partition(".")
    if head == "protocol":
        return "identity.0.protocol" + (f".{rest}" if rest else "")
    return f"identity.0.binding.{rest}" if rest else "identity.0"


def upgrade_identity(document: Mapping[str, Any]) -> dict[str, Any]:
    """A v2 payload stored before SOLUSDEV-326 (one `identity`, a top-level `protocol`) as the
    brain list (`[]` when it named neither); a current document comes back as a copy.

    Records follow (`identity.<f>` → `identity.0.binding.<f>`, `identity` → `identity.0`,
    `protocol[.<f>]` → `identity.0.protocol[.<f>]`), and the brain's new `kind` leaf takes the
    record that covered the old identity (else the driver), so every longest-prefix lookup
    still finds the record it found before. Stale records of an absent identity are dropped.

    This runs on raw request bodies: records that are not a mapping of paths come back
    untouched, so field validation refuses them (a 422, never a TypeError, never coerced)."""
    upgraded = dict(document)
    old = upgraded.get("provenance", {})
    if (
        isinstance(upgraded.get("identity"), list)
        or not {"identity", "protocol"} & set(upgraded)
        or not isinstance(old, Mapping)
        or not all(isinstance(path, str) for path in old)
    ):
        return upgraded
    binding, protocol = upgraded.pop("identity", None), upgraded.pop("protocol", None)
    moved = {path for path in old if path.split(".")[0] in ("identity", "protocol")}
    records = {path: record for path, record in old.items() if path not in moved}
    upgraded["identity"] = []
    if binding is not None or protocol is not None:
        upgraded["identity"] = [
            {"kind": "host", "binding": binding, "via": None, "protocol": protocol}
        ]
        records.update({_brain_path(path): old[path] for path in moved})
        kind = lookup(old, "identity.kind" if binding is not None else "protocol.driver_id")
        if lookup(records, "identity.0.kind") is None and kind is not None:
            records["identity.0.kind"] = kind
    if "provenance" in upgraded or records:
        upgraded["provenance"] = records
    return upgraded


def pin_rows(document: dict[str, Any], ref: str) -> None:
    """Name `ref` on every row of a document dict that leaves its brain implicit — before a
    second brain joins, after which `None` no longer means this one. Each new `brain` leaf
    takes the record of its row's address."""
    provenance = document["provenance"]
    for index, row in enumerate(document["bus_map"]):
        if row.get("brain") is None:
            row["brain"] = ref
            if lookup(provenance, f"bus_map.{index}.brain") is None:
                provenance[f"bus_map.{index}.brain"] = lookup(
                    provenance, f"bus_map.{index}.address"
                )


def _check_via(identity: Sequence[BrainIdentity], refs: Sequence[str]) -> None:
    """`via` names another brain of this config, and no brain is reached through itself."""
    reached = {item.device_ref: item.via for item in identity if item.device_ref is not None}
    for item in identity:
        if item.via is not None and (item.via == item.device_ref or item.via not in refs):
            raise ValueError(f"via must name another brain of this config, not {item.via!r}")
    for start in reached:
        seen: set[str] = set()
        ref: str | None = start
        while ref is not None:
            if ref in seen:
                raise ValueError("brains cannot be reached through each other")
            seen.add(ref)
            ref = reached.get(ref)


class ConfigDraft(FrozenModel):
    """Portable creation fields. The server supplies the new subject's UUID."""

    schema_version: Literal[2] = 2
    component: PartConfig | None = None
    identity: list[BrainIdentity] = Field(default_factory=list, max_length=MAX_BRAINS)
    bus_map: list[BusMapEntry] = Field(default_factory=list, max_length=MAX_BUS_ENTRIES)
    disambiguated_by: Literal["user"] | None = None
    provenance: dict[str, ProvenanceRecord] = Field(default_factory=dict, max_length=2048)

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data: Any) -> Any:
        """Every read of a pre-SOLUSDEV-326 payload sees the brain list."""
        return upgrade_identity(data) if isinstance(data, Mapping) else data

    def provenance_of(self, path: str) -> ProvenanceRecord:
        record = lookup(self.provenance, path)
        if record is None:
            raise KeyError(path)
        return record

    def brain_of(self, entry: BusMapEntry) -> str | None:
        """The device ref of the brain a row sits behind (`None`: no brain, or an unbound one)."""
        if entry.brain is not None or len(self.identity) != 1:
            return entry.brain
        return self.identity[0].device_ref

    @model_validator(mode="after")
    def _brains_consistent(self) -> Self:
        refs = [item.device_ref for item in self.identity if item.device_ref is not None]
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate brain")
        _check_via(self.identity, refs)
        for entry in self.bus_map:
            if entry.brain is None and len(self.identity) > 1:
                raise ValueError("a bus row names its brain when the config has several")
            if entry.brain is not None and entry.brain not in refs:
                raise ValueError(f"a bus row names an unknown brain {entry.brain!r}")
        endpoints = [
            (self.brain_of(entry), entry.protocol, entry.address) for entry in self.bus_map
        ]
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("duplicate bus endpoint")
        return self

    @model_validator(mode="after")
    def _portable_complete(self) -> Self:
        document = self.model_dump(mode="json")
        if len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
        leaves = list(
            _leaf_items(
                {
                    key: value
                    for key, value in document.items()
                    if key not in {"schema_version", "entity_id", "provenance"}
                }
            )
        )
        missing = [path for path, _ in leaves if lookup(self.provenance, path) is None]
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
        return self


class EntityHardwareConfig(ConfigDraft):
    """One physical graph subject's configuration; driver aggregates are resolved at runtime."""

    entity_id: uuid.UUID


def _moved_records(
    config: EntityHardwareConfig | HardwareConfig, field: str, moves: Mapping[int, int]
) -> dict[str, Any]:
    """Each valued leaf of `field[old]` re-keyed to `field[new]`, with the record covering it."""
    dumped = config.model_dump(mode="json")[field]
    records: dict[str, Any] = {}
    for old, new in moves.items():
        for path, _ in _leaf_items(dumped[old], f"{field}.{old}."):
            key = f"{field}.{new}" + path.removeprefix(f"{field}.{old}")
            records[key] = config.provenance_of(path).model_dump(mode="json")
    return records


def _brain_rows(config: EntityHardwareConfig, device_ref: str) -> tuple[int, list[int]]:
    index = [brain.device_ref for brain in config.identity].index(device_ref)
    rows = [i for i, row in enumerate(config.bus_map) if config.brain_of(row) == device_ref]
    return index, rows


def without_brain(config: EntityHardwareConfig, device_ref: str) -> EntityHardwareConfig:
    """`config` without the brain bound to `device_ref` and the rows behind it."""
    index, rows = _brain_rows(config, device_ref)
    document = config.model_dump(mode="json")
    brains = [i for i in range(len(config.identity)) if i != index]
    kept = [i for i in range(len(config.bus_map)) if i not in rows]
    document["identity"] = [document["identity"][i] for i in brains]
    document["bus_map"] = [document["bus_map"][i] for i in kept]
    document["provenance"] = {
        **{
            path: record
            for path, record in document["provenance"].items()
            if path.split(".")[0] not in ("identity", "bus_map")
        },
        **_moved_records(config, "identity", {old: new for new, old in enumerate(brains)}),
        **_moved_records(config, "bus_map", {old: new for new, old in enumerate(kept)}),
    }
    return EntityHardwareConfig.model_validate(document)


def with_brain(
    taking: EntityHardwareConfig, giving: EntityHardwareConfig, device_ref: str
) -> EntityHardwareConfig:
    """`taking` with `giving`'s brain `device_ref` appended, its rows and records included.
    Rows `taking` leaves implicit name its one brain first (ValueError when it is unbound)."""
    index, rows = _brain_rows(giving, device_ref)
    document = taking.model_dump(mode="json")
    several = bool(taking.identity)
    if len(taking.identity) == 1 and any(row.brain is None for row in taking.bus_map):
        only = taking.identity[0].device_ref
        if only is None:
            raise ValueError("an unbound brain's rows cannot be named")
        pin_rows(document, only)
    source = giving.model_dump(mode="json")
    base, slot = len(taking.bus_map), len(taking.identity)
    document["identity"].append(source["identity"][index])
    document["bus_map"].extend(
        {**source["bus_map"][old], **({"brain": device_ref} if several else {})} for old in rows
    )
    moves = {old: base + offset for offset, old in enumerate(rows)}
    document["provenance"].update(_moved_records(giving, "identity", {index: slot}))
    document["provenance"].update(_moved_records(giving, "bus_map", moves))
    for old, new in moves.items() if several else ():
        address = giving.provenance_of(f"bus_map.{old}.address").model_dump(mode="json")
        document["provenance"].setdefault(f"bus_map.{new}.brain", address)
    return EntityHardwareConfig.model_validate(document)


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
        missing = [path for path in self.leaf_paths() if lookup(self.provenance, path) is None]
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

    def provenance_of(self, path: str) -> ProvenanceRecord:
        record = lookup(self.provenance, path)
        if record is None:
            raise KeyError(path)
        return record


class ConfigLayer(BaseModel):
    """One source's contribution: a partial document plus who it came from."""

    by: FieldProvenance
    document: dict[str, Any]
    source: str | None = None


def _same_brain(key: str, current: Mapping[str, Any], incoming: Mapping[str, Any]) -> bool:
    """An identity merges field by field only into the same device (keyed by device ref): a
    later layer naming another device replaces it whole, so no id leaks across devices."""
    return key != "identity" or all(
        incoming.get(field, current.get(field)) == current.get(field)
        for field in ("kind", "binding")
    )


def _merge_into(target: dict[str, Any], layer: Mapping[str, Any]) -> None:
    for key, value in layer.items():
        current = target.get(key)
        if (
            isinstance(value, Mapping)
            and isinstance(current, dict)
            and _same_brain(key, current, value)
        ):
            _merge_into(current, value)
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
