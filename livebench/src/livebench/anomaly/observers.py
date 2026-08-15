"""Edge observers over LB-06 packets (LB-02).

These run close to the data — before windowing, before the graph — so anomalies are
caught as they happen, not a window later. All pure Python over bounded state (a few
floats and a small deque per signal): at 512-sample ring scale numpy would buy
nothing but a dependency.

Every event carries the offending signal AND its context (`device_id`, timestamp,
observed value, detector detail), because an anomaly without attribution is noise to
the error path. State machines fire on ENTERING a condition, not per sample — a
breach that lasts 500 samples is one event, and detectors re-arm on recovery.
"""

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from solus_api.graph.packet import TelemetryPacket

ObserverKind = Literal["threshold_breach", "change_point", "stream_gap"]


class ObserverEvent(BaseModel):
    """One detected anomaly, with enough context to route into the telemetry/error path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObserverKind
    device_id: str
    signal: str
    at: datetime
    value: float | None = None
    detail: dict[str, Any] = {}


@dataclass
class ThresholdObserver:
    """Fires when a signal (optionally smoothed over the last `smoothing` samples)
    leaves [low, high]. One event per excursion; re-arms when back in bounds."""

    signal: str
    low: float | None = None
    high: float | None = None
    smoothing: int = 1
    _recent: deque[float] = field(default_factory=deque)
    _in_breach: bool = False

    def __post_init__(self) -> None:
        if self.low is None and self.high is None:
            raise ValueError("at least one of low/high required")
        if self.smoothing < 1:
            raise ValueError("smoothing must be >= 1")
        self._recent = deque(maxlen=self.smoothing)

    def add(self, packet: TelemetryPacket) -> list[ObserverEvent]:
        value = packet.values.get(self.signal)
        if value is None:
            return []
        self._recent.append(value)
        if len(self._recent) < self.smoothing:
            return []  # don't judge a partial window
        # Median, not mean: one wild sample must not drag the whole window over a bound.
        smoothed = statistics.median(self._recent)
        breached = (self.high is not None and smoothed > self.high) or (
            self.low is not None and smoothed < self.low
        )
        if not breached:
            self._in_breach = False
            return []
        if self._in_breach:
            return []  # still inside the same excursion
        self._in_breach = True
        return [
            ObserverEvent(
                kind="threshold_breach",
                device_id=packet.device_id,
                signal=self.signal,
                at=packet.timestamp,
                value=value,
                detail={
                    "smoothed": smoothed,
                    "low": self.low,
                    "high": self.high,
                    "smoothing": self.smoothing,
                },
            )
        ]


@dataclass
class CusumObserver:
    """Two-sided CUSUM change-point detector.

    Learns mean/std from the first `baseline_samples` values, then accumulates
    standardized deviations beyond `slack` (k, in σ units); when either side's sum
    exceeds `decision` (h, in σ units) it fires and RESTARTS baseline learning from
    the post-change stream — so the next shift is detected against the new regime.
    """

    signal: str
    baseline_samples: int = 50
    slack: float = 0.5
    decision: float = 5.0
    _baseline: list[float] = field(default_factory=list)
    _mean: float = 0.0
    _std: float = 1.0
    _pos: float = 0.0
    _neg: float = 0.0

    def __post_init__(self) -> None:
        if self.baseline_samples < 2:
            raise ValueError("baseline_samples must be >= 2")

    def add(self, packet: TelemetryPacket) -> list[ObserverEvent]:
        value = packet.values.get(self.signal)
        if value is None:
            return []
        if len(self._baseline) < self.baseline_samples:
            self._baseline.append(value)
            if len(self._baseline) == self.baseline_samples:
                self._mean = statistics.fmean(self._baseline)
                spread = statistics.pstdev(self._baseline)
                # ponytail: zero-variance floor keeps a constant baseline from
                # dividing by zero; any real sensor has noise above 1e-9.
                self._std = max(spread, 1e-9)
            return []

        z = (value - self._mean) / self._std
        self._pos = max(0.0, self._pos + z - self.slack)
        self._neg = max(0.0, self._neg - z - self.slack)
        if self._pos < self.decision and self._neg < self.decision:
            return []

        direction = "up" if self._pos >= self.decision else "down"
        event = ObserverEvent(
            kind="change_point",
            device_id=packet.device_id,
            signal=self.signal,
            at=packet.timestamp,
            value=value,
            detail={
                "direction": direction,
                "baseline_mean": self._mean,
                "baseline_std": self._std,
                "decision": self.decision,
            },
        )
        # Re-learn from the new regime so a later shift is judged against it.
        self._baseline = []
        self._pos = 0.0
        self._neg = 0.0
        return [event]


class GapWatchdog:
    """Fires when a (device, signal) that HAS streamed goes silent past `timeout_seconds`.

    Event-time driven: `add` records arrivals, `tick(now)` is the caller's clock —
    injectable, so fault-induction tests and real deployments share the code path.
    One event per gap; a resumed stream re-arms the watchdog.
    """

    def __init__(self, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout = timeout_seconds
        self._last_seen: dict[tuple[str, str], datetime] = {}
        self._gapped: set[tuple[str, str]] = set()

    def add(self, packet: TelemetryPacket) -> None:
        for signal in packet.values:
            key = (packet.device_id, signal)
            self._last_seen[key] = packet.timestamp
            self._gapped.discard(key)  # stream resumed → watchdog re-arms

    def tick(self, *, now: datetime) -> list[ObserverEvent]:
        events: list[ObserverEvent] = []
        for (device_id, signal), last in self._last_seen.items():
            key = (device_id, signal)
            silent_for = (now - last).total_seconds()
            if silent_for < self._timeout or key in self._gapped:
                continue
            self._gapped.add(key)
            events.append(
                ObserverEvent(
                    kind="stream_gap",
                    device_id=device_id,
                    signal=signal,
                    at=now,
                    detail={"last_seen_seconds": silent_for, "timeout": self._timeout},
                )
            )
        return events
