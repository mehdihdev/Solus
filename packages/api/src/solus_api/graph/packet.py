"""Telemetry packet + read shapes — THE LB-06 telemetry packet format (SOLUSDEV-126).

`TelemetryPacket` is the ratified LB-06 wire shape every telemetry producer speaks: the sim
(LB-01), a real robot (LB-02), the Foxglove/MCAP ingest (CON-03), and the graph plumbing that
maps it onto entities (LNK-06). Encode/decode live in `codec.py`; the normative description is
`docs/contracts/telemetry-packet.md`.

It stays in this package rather than `packages/contracts/` by decision at the SOLUSDEV-126
Phase 0 gate — that package is human-owned (ADR-028/032) and currently import-broken.

Two clocks, deliberately: `timestamp` is the wall-clock instant (what windows bucket by, and what
correlates telemetry with commits and CAD edits), while `seq` is the producer's MONOTONIC
per-device counter. Real robot clocks drift and get NTP-corrected backwards; `seq` is what
survives that, so consumers detect drops and reordering from `seq`, never from `timestamp` deltas.

Everything a device sends is UNTRUSTED input (CLAUDE.md §7): sizes and counts are bounded and
numeric values must be finite, so a malformed or hostile packet is rejected at the boundary and
never crashes ingestion. `device_id`/signal names are DATA, never instructions.

`RecentValuesView` is the raw recent-values read the same feed exposes to a Foxglove bridge
(CON-03) — a plain, JSON-serializable per-signal series, no summarization.
"""

import math
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Wire-format version. Bump ONLY for an additive change; decoders tolerate unknown fields and a
#: HIGHER version than they were built against (see `codec.from_wire`), which is what lets a new
#: producer talk to an old consumer without breaking it.
SCHEMA_VERSION = 1

# Bounds on untrusted device input (§7) — reject rather than truncate.
MAX_DEVICE_ID_LEN = 512  # matches graph_entity.external_ref width
MAX_SIGNALS_PER_PACKET = 256
MAX_SIGNAL_NAME_LEN = 128
MAX_UNIT_LEN = 32  # "rev/min", "m/s^2", "degC" — a unit symbol, not a description
#: The format's integer ceiling is the INTERSECTION of its runtimes, not Python's. A Python int is
#: arbitrary-precision and the wire is int64, but one of the two mandated decoders is JavaScript,
#: where integers are only exact to 2^53 — so anything larger would decode there with silent
#: precision loss. 2^53 microseconds still reaches the year 2255; nothing real is given up.
MAX_SAFE_INT = 2**53 - 1
MAX_SEQ = MAX_SAFE_INT
MAX_SCHEMA_VERSION = 1_000_000  # a version, not a payload — nothing legitimate approaches this


class TelemetryPacket(BaseModel):
    """One reading from a device/topic: a set of named numeric signals at an instant.

    `device_id` is the identity key ingestion resolves to a graph entity (it matches the entity's
    `external_ref`). It carries the device-OR-topic identity: deliberately ONE identity key, so
    nothing downstream has to decide which of two fields resolves.

    `values` maps signal name → finite float; `units` optionally labels those same signals.
    `seq` is the monotonic per-device counter (see the module docstring) — optional, because not
    every source sequences its stream, and `None` says so honestly instead of faking a 0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(min_length=1, max_length=MAX_DEVICE_ID_LEN)
    timestamp: datetime
    values: dict[str, float]
    # Upper bounds as well as lower: a Python int is arbitrary-precision, so without `le` a
    # hostile producer could park a 4000-digit `seq` in the model that no int64 wire — and no
    # other runtime — can represent.
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1, le=MAX_SCHEMA_VERSION)
    seq: int | None = Field(default=None, ge=0, le=MAX_SEQ)
    units: dict[str, str] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, ts: datetime) -> datetime:
        # Reject naive timestamps at the boundary (§7 reject-don't-truncate): a naive/aware mix
        # would otherwise raise TypeError deep in get_telemetry's window comparisons, crashing the
        # whole project's summary on one bad packet.
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return ts

    @field_validator("values")
    @classmethod
    def _validate_values(cls, values: dict[str, float]) -> dict[str, float]:
        if not values:
            raise ValueError("packet carries no signal values")
        if len(values) > MAX_SIGNALS_PER_PACKET:
            raise ValueError(f"too many signals (max {MAX_SIGNALS_PER_PACKET})")
        for name, value in values.items():
            if not name or len(name) > MAX_SIGNAL_NAME_LEN:
                raise ValueError(f"signal name length out of range: {name[:32]!r}")
            if not math.isfinite(value):
                raise ValueError(f"signal {name!r} is not a finite number")
        return values

    @field_validator("units")
    @classmethod
    def _validate_units(cls, units: dict[str, str]) -> dict[str, str]:
        for name, unit in units.items():
            if not name or len(name) > MAX_SIGNAL_NAME_LEN:
                raise ValueError(f"unit signal name length out of range: {name[:32]!r}")
            if not unit or len(unit) > MAX_UNIT_LEN:
                raise ValueError(f"unit for {name[:32]!r} length out of range (max {MAX_UNIT_LEN})")
        return units

    @model_validator(mode="after")
    def _units_describe_carried_signals(self) -> Self:
        # A unit for a signal this packet doesn't carry describes nothing — it means the producer
        # and the packet disagree, so reject at the boundary rather than store dead metadata.
        unknown = sorted(set(self.units) - set(self.values))
        if unknown:
            raise ValueError(f"units reference signals not in this packet: {unknown[:5]}")
        return self


class RecentSample(BaseModel):
    """One buffered reading with its original unit, if the producer supplied one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    value: float
    unit: str | None = Field(default=None, min_length=1, max_length=MAX_UNIT_LEN)


class SignalSeries(BaseModel):
    """The recent points for one signal on one entity, oldest→newest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: str
    points: list[RecentSample]


class RecentValuesView(BaseModel):
    """The raw recent-values feed for one entity — the Foxglove-consumable (CON-03) read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: UUID
    signals: list[SignalSeries]


class DeviceRecentView(BaseModel):
    """Recent values keyed by device, reading its entity feed after graph resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    resolved_entity_id: UUID | None
    signals: list[SignalSeries]
