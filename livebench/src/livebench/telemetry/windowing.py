"""Event-time window aggregation: LB-06 packets → W0-07 `TelemetryWindowSummary` (CON-03).

The LiveConnection contract emits batch-summarized windows, never raw samples. This is
the summarizer that sits between a packet stream and that contract: windows are anchored
at the first accepted packet's timestamp and closed by the first packet at or past the
boundary (event time, so replayed MCAP files and live streams window identically).

Stats per signal are the same five keys LNK-06's plumbing produces (`mean`/`min`/`max`/
`last`/`count`) so a consumer cannot tell which path summarized. Deterministic by
construction: no wall clock, no LLM.

Ordering rules (all driven by review findings — timestamps are attacker-supplied):

* A closed window is immutable: samples behind the watermark are dropped.
* A reorder ahead of the open window's anchor re-anchors it backward — but only if
  everything already folded still fits in the declared span; otherwise the straggler
  is dropped. A window's `[start, end)` always contains every sample it summarizes.
* Bounded state: distinct signal names per window are capped, and a window whose
  sample budget is spent force-flushes — a frozen timestamp cannot hold one open.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.graph.packet import MAX_SIGNALS_PER_PACKET, TelemetryPacket

#: Distinct signal names one open window will track; novel names beyond it are dropped.
MAX_SIGNALS_PER_WINDOW: Final = 4 * MAX_SIGNALS_PER_PACKET

#: Values folded into one window before it force-flushes regardless of timestamps.
MAX_SAMPLES_PER_WINDOW: Final = 100_000

#: A window is a live view, not an archive. Anything longer is a config error.
MAX_WINDOW_SECONDS: Final = 86_400.0


@dataclass
class _Accum:
    """Running stats for one signal within the open window."""

    total: float = 0.0
    minimum: float = float("inf")
    maximum: float = float("-inf")
    count: int = 0
    last_ts: datetime | None = None
    last: float = 0.0

    def add(self, ts: datetime, value: float) -> None:
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        self.count += 1
        if self.last_ts is None or ts >= self.last_ts:
            self.last_ts = ts
            self.last = value

    def stats(self) -> dict[str, float]:
        return {
            "mean": self.total / self.count,
            "min": self.minimum,
            "max": self.maximum,
            "last": self.last,
            "count": float(self.count),
        }


@dataclass
class WindowAggregator:
    """Accumulates packets into consecutive event-time windows for ONE subscription."""

    window: TelemetryWindow
    _wanted: frozenset[str] | None = None
    _anchor: datetime | None = None
    _max_ts: datetime | None = None
    _watermark: datetime | None = None  # end of the last CLOSED window; nothing goes behind it
    _signals: dict[str, _Accum] = field(default_factory=dict)
    _samples: int = 0

    def __post_init__(self) -> None:
        duration = self.window.duration_seconds
        if not math.isfinite(duration) or not 0 < duration <= MAX_WINDOW_SECONDS:
            raise ValueError(f"window duration out of range: {duration}")
        self._wanted = frozenset(self.window.signals) if self.window.signals else None

    def add(self, packet: TelemetryPacket) -> TelemetryWindowSummary | None:
        """Feed one packet; returns a completed window's summary when this packet
        crosses the boundary or spends the sample budget, else ``None``."""
        values = (
            packet.values
            if self._wanted is None
            else {k: v for k, v in packet.values.items() if k in self._wanted}
        )
        if not values:
            return None
        ts = packet.timestamp
        if self._watermark is not None and ts < self._watermark:
            return None  # late straggler from an already-closed window: closed is immutable

        closed: TelemetryWindowSummary | None = None
        if self._anchor is not None and ts >= self._window_end():
            closed = self.flush()

        if self._anchor is None:
            self._anchor = ts
        elif ts < self._anchor:
            if self._max_ts is not None and self._max_ts >= ts + self._duration():
                return closed  # cannot coexist in one window with what's already folded
            self._anchor = ts  # backward re-anchor of the OPEN window: span still holds all

        self._fold(ts, values)
        if closed is None and self._samples >= MAX_SAMPLES_PER_WINDOW:
            closed = self.flush()  # a frozen timestamp cannot hold a window open forever
        return closed

    def _fold(self, ts: datetime, values: dict[str, float]) -> None:
        for name, value in values.items():
            accum = self._signals.get(name)
            if accum is None:
                if len(self._signals) >= MAX_SIGNALS_PER_WINDOW:
                    continue  # bounded state: novel names beyond the cap are dropped
                accum = self._signals[name] = _Accum()
            accum.add(ts, value)
        self._samples += len(values)
        self._max_ts = ts if self._max_ts is None else max(self._max_ts, ts)

    def flush(self) -> TelemetryWindowSummary | None:
        """Close the open window early (disconnect/teardown); ``None`` when empty."""
        if self._anchor is None:
            return None
        window_end = self._window_end()
        summary = TelemetryWindowSummary(
            window_start=self._anchor,
            window_end=window_end,
            summary=(
                f"{len(self._signals)} signals, {self._samples} samples "
                f"in {self.window.duration_seconds}s window"
            ),
            signals={name: accum.stats() for name, accum in sorted(self._signals.items())},
        )
        self._watermark = window_end
        self._anchor = None
        self._max_ts = None
        self._signals = {}
        self._samples = 0
        return summary

    def _duration(self) -> timedelta:
        return timedelta(seconds=self.window.duration_seconds)

    def _window_end(self) -> datetime:
        if self._anchor is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("no open window")
        return self._anchor + self._duration()
