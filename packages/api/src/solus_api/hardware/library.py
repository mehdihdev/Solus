"""The Solus-curated parts and platform library (R4, docs/api/hardware.md §5).

Definitions are YAML files loaded ONCE into memory: Solus-authored, identical for every tenant,
with no table and no runtime write path (ADR-033's containment rules, applied to files). A
platform composes part ids and never restates a part's specs. Vendor and product names live in
the definition files only; this module knows ids, kinds and shapes.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from solus_api.connectors.contracts import FrozenModel
from solus_api.hardware.config import (
    MAX_PARAMS,
    MAX_VALUES,
    CalibrationMode,
    LifecycleState,
    Scalar,
    TransportKind,
    unit_for_mode,
)
from solus_api.services.physical_robots import ROBOT_CATEGORIES

DEFINITIONS_DIR: Final = Path(__file__).parent / "definitions"
ID_PATTERN: Final = r"^[a-z0-9][a-z0-9.-]{0,63}$"
DRIVER_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9._-]{0,63}$"
ROLE_PATTERN: Final = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
QUANTITY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"
MAX_TEXT: Final = 512
MAX_KEYWORDS: Final = 32
MAX_SPECS: Final = 32
MAX_REGISTERS: Final = 64
MAX_TELEMETRY: Final = 32
MAX_PLATFORM_PARTS: Final = 64
DEFAULT_LIMIT: Final = 50

DefinitionKind = Literal["part", "platform"]
MachineClass = Literal["arm", "quadrotor", "mobile_base", "quadruped", "humanoid", "rover", "other"]
Text = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
DriverId = Annotated[str, Field(pattern=DRIVER_ID_PATTERN)]
HttpsUrl = Annotated[str, Field(max_length=MAX_TEXT, pattern=r"^https://")]


class DefinitionError(ValueError):
    """A definition file is wrong; the library refuses to load (loud beats half-loaded)."""


def _known_category(value: str) -> str:
    if value not in ROBOT_CATEGORIES:
        raise ValueError(f"unknown category {value!r}")
    return value


def _bounded_scalars(values: Mapping[str, Scalar], limit: int, label: str) -> None:
    if len(values) > limit:
        raise ValueError(f"at most {limit} {label}")
    for key, value in values.items():
        if len(key) > 64 or (isinstance(value, str) and len(value) > MAX_TEXT):
            raise ValueError(f"{label} entry {key!r} is too long")


class _Definition(FrozenModel):
    id: str = Field(pattern=ID_PATTERN)
    name: Text
    manufacturer: Text | None = None
    keywords: list[Text] = Field(default_factory=list, max_length=MAX_KEYWORDS)
    notes: Text | None = None


class RegisterSpec(FrozenModel):
    address: int = Field(ge=0, le=0xFFFF)
    size: int = Field(ge=1, le=8)


class TelemetrySpec(FrozenModel):
    quantity: str = Field(pattern=QUANTITY_PATTERN)
    unit: str | None = Field(default=None, max_length=32)


class PartDefinition(_Definition):
    category: str
    specs: dict[str, Scalar] = Field(default_factory=dict)
    driver_id: DriverId | None = None
    protocol_version: int | None = Field(default=None, ge=0)
    resolution: int | None = Field(default=None, ge=1)
    register_map: dict[str, RegisterSpec] = Field(default_factory=dict)
    telemetry: list[TelemetrySpec] = Field(default_factory=list, max_length=MAX_TELEMETRY)
    calibration_mode: CalibrationMode | None = None
    datasheet_url: HttpsUrl | None = None

    _category = field_validator("category")(_known_category)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        _bounded_scalars(self.specs, MAX_SPECS, "specs")
        if len(self.register_map) > MAX_REGISTERS:
            raise ValueError(f"at most {MAX_REGISTERS} registers")
        return self


class PlatformPart(FrozenModel):
    """One slot of a platform: WHICH part sits at WHICH address playing WHICH role."""

    part: str = Field(pattern=ID_PATTERN)
    address: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    role: str = Field(pattern=ROLE_PATTERN)
    category: str | None = None  # defaults to the part's
    gear_ratio: str | None = Field(default=None, max_length=32)
    calibration_mode: CalibrationMode | None = None  # overrides the part's
    calibration: dict[str, float | int] = Field(default_factory=dict)

    @field_validator("category")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        return None if value is None else _known_category(value)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(self.calibration) > MAX_VALUES:
            raise ValueError(f"at most {MAX_VALUES} calibration values")
        return self


class PlatformDefinition(_Definition):
    machine_class: MachineClass
    transport: TransportKind
    driver_id: DriverId | None  # explicit null: an SDK-only machine has no Solus driver yet
    params: dict[str, Scalar] = Field(default_factory=dict)
    parts: list[PlatformPart] = Field(min_length=1, max_length=MAX_PLATFORM_PARTS)
    urdf: Text | None = None
    mjcf: Text | None = None

    @model_validator(mode="after")
    def _unique_slots(self) -> Self:
        _bounded_scalars(self.params, MAX_PARAMS, "params")
        for field in ("address", "role"):
            seen: set[str] = set()
            for slot in self.parts:
                value: str = getattr(slot, field)
                if value in seen:
                    raise ValueError(f"repeated {field} {value!r}")
                seen.add(value)
        return self


class Hit(FrozenModel):
    kind: DefinitionKind
    id: str
    name: str
    manufacturer: str | None
    category: str | None = None
    machine_class: str | None = None
    summary: str


def _part_hit(part: PartDefinition) -> tuple[Hit, str]:
    driver = f"driver {part.driver_id}" if part.driver_id else "no driver"
    hit = Hit(
        kind="part",
        id=part.id,
        name=part.name,
        manufacturer=part.manufacturer,
        category=part.category,
        summary=f"{part.category} · {driver}",
    )
    return hit, " ".join([part.id, part.name, part.manufacturer or "", *part.keywords]).lower()


def _platform_hit(platform: PlatformDefinition) -> tuple[Hit, str]:
    transport = platform.transport.value
    hit = Hit(
        kind="platform",
        id=platform.id,
        name=platform.name,
        manufacturer=platform.manufacturer,
        machine_class=platform.machine_class,
        summary=f"{platform.machine_class} · {transport} · {len(platform.parts)} parts",
    )
    words = [platform.id, platform.name, platform.manufacturer or "", *platform.keywords]
    return hit, " ".join([*words, platform.machine_class]).lower()


@dataclass(frozen=True)
class Library:
    parts: dict[str, PartDefinition]
    platforms: dict[str, PlatformDefinition]

    def get(
        self, kind: DefinitionKind, definition_id: str
    ) -> PartDefinition | PlatformDefinition | None:
        if kind == "part":
            return self.parts.get(definition_id)
        return self.platforms.get(definition_id)

    def search(
        self, q: str = "", kind: DefinitionKind | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Hit]:
        """Lexical: case-insensitive query tokens over id, name, manufacturer, keywords and
        machine class; ranked by matched-token count then id. An empty query lists all."""
        tokens = q.lower().split()
        index = [
            *(_part_hit(p) for p in self.parts.values() if kind in (None, "part")),
            *(_platform_hit(p) for p in self.platforms.values() if kind in (None, "platform")),
        ]
        ranked: list[tuple[int, str, Hit]] = []
        for hit, haystack in index:
            matched = sum(1 for token in tokens if token in haystack)
            if tokens and matched == 0:
                continue
            ranked.append((-matched, hit.id, hit))
        ranked.sort(key=lambda row: (row[0], row[1]))
        return [hit for _, _, hit in ranked[:limit]]

    @staticmethod
    def part_config(
        part: PartDefinition,
        role: str,
        *,
        source: str,
        mode: CalibrationMode | None = None,
        values: Mapping[str, float | int] | None = None,
    ) -> dict[str, Any]:
        """A part's config slot: `<role>.<quantity>` channels (the calibration mode's unit
        governs position; other quantities keep the definition's unit), a solus-owned
        calibration when a mode applies, lifecycle planned."""
        mode = mode or part.calibration_mode
        entry: dict[str, Any] = {
            "telemetry": [
                {
                    "name": f"{role}.{t.quantity}",
                    "unit": (unit_for_mode(mode) if t.quantity == "position" else None) or t.unit,
                }
                for t in part.telemetry
            ],
            "lifecycle": LifecycleState.PLANNED.value,
        }
        if mode is not None:
            entry["calibration"] = {
                "mode": mode.value,
                "values": dict(values or {}),
                "owner": "solus",
                "source": source,
            }
        return entry

    def platform_config_layer(
        self, platform: PlatformDefinition, part_entity_ids: Mapping[str, uuid.UUID]
    ) -> dict[str, Any]:
        """The LIBRARY layer document for an imported platform (`merge_layers` stamps the
        provenance). Bus-map entries name the driver, or the transport when there is none."""
        source = f"platform:{platform.id}"
        document: dict[str, Any] = {"bus_map": [], "parts": {}}
        if platform.driver_id is not None:
            document["protocol"] = {
                "driver_id": platform.driver_id,
                "params": dict(platform.params),
            }
        for slot in platform.parts:
            entity_id = part_entity_ids.get(slot.address)
            if entity_id is None:
                raise DefinitionError(f"{platform.id}: no part entity for address {slot.address!r}")
            part = self.parts[slot.part]
            document["bus_map"].append(
                {
                    "protocol": platform.driver_id or platform.transport.value,
                    "address": slot.address,
                    "part_entity_id": str(entity_id),
                    "model": part.name,
                }
            )
            document["parts"][str(entity_id)] = self.part_config(
                part, slot.role, source=source, mode=slot.calibration_mode, values=slot.calibration
            )
        return document


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise DefinitionError(f"{path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DefinitionError(f"{path.name}: expected a mapping")
    return raw


def _load_kind[T: _Definition](root: Path, folder: str, model: type[T]) -> dict[str, T]:
    loaded: dict[str, T] = {}
    for path in sorted((root / folder).glob("*.yaml")):
        try:
            definition = model.model_validate(_read_yaml(path))
        except ValidationError as exc:
            raise DefinitionError(f"{path.name}: {' '.join(str(exc).split())}") from exc
        if definition.id != path.stem:
            raise DefinitionError(f"{path.name}: id {definition.id!r} must equal the file stem")
        loaded[definition.id] = definition
    return loaded


@functools.cache
def load_library(root: Path = DEFINITIONS_DIR) -> Library:
    """Load a definitions root once. One id namespace across kinds; a platform naming an
    unknown part, a duplicate id or an id that is not its file stem fails loudly."""
    parts = _load_kind(root, "parts", PartDefinition)
    platforms = _load_kind(root, "platforms", PlatformDefinition)
    shared = sorted(parts.keys() & platforms.keys())
    if shared:
        raise DefinitionError(f"duplicate definition id(s): {', '.join(shared)}")
    for platform in platforms.values():
        for slot in platform.parts:
            if slot.part not in parts:
                raise DefinitionError(f"{platform.id}: unknown part {slot.part!r}")
    return Library(parts=parts, platforms=platforms)


def vendor_definitions_root() -> Path:
    """The vendor-shipped tier's ingest seam — the same schemas, a separate root, empty today
    and never written at runtime."""
    return DEFINITIONS_DIR / "vendor"


__all__ = [
    "DEFINITIONS_DIR",
    "DefinitionError",
    "DefinitionKind",
    "Hit",
    "Library",
    "PartDefinition",
    "PlatformDefinition",
    "PlatformPart",
    "load_library",
    "vendor_definitions_root",
]
