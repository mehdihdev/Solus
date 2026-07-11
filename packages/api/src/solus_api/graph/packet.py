"""Telemetry packet + read shapes for the graph data plumbing (SOLUS-LNK-06).

`TelemetryPacket` is the PROPOSED LB-06 packet format — defined locally here (not in the
frozen `packages/contracts/`) pending human ratification/extraction into the shared contract
(see the completion report). It is the wire shape ingestion maps onto graph entities.

Everything a device sends is UNTRUSTED input (CLAUDE.md §7): sizes and counts are bounded and
numeric values must be finite, so a malformed or hostile packet is rejected at the boundary and
never crashes ingestion. `device_id`/signal names are DATA, never instructions.

`RecentValuesView` is the raw recent-values read the same feed exposes to a Foxglove bridge
(CON-03) — a plain, JSON-serializable per-signal series, no summarization.
"""

import math
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bounds on untrusted device input (§7) — reject rather than truncate.
MAX_DEVICE_ID_LEN = 512  # matches graph_entity.external_ref width
MAX_SIGNALS_PER_PACKET = 256
MAX_SIGNAL_NAME_LEN = 128


class TelemetryPacket(BaseModel):
    """One reading from a device/topic: a set of named numeric signals at an instant.

    `device_id` is the identity key ingestion resolves to a graph entity (it matches the
    entity's `external_ref`). `values` maps signal name → finite float."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(min_length=1, max_length=MAX_DEVICE_ID_LEN)
    timestamp: datetime
    values: dict[str, float]

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


class RecentSample(BaseModel):
    """A single buffered (timestamp, value) point for one signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    value: float


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
