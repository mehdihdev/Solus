"""Graph data plumbing for telemetry (SOLUS-LNK-06).

The bridge between Live Bench telemetry and the graph SOL reasons over. Three jobs:

1. `ingest` — map an incoming (LB-06) `TelemetryPacket` to its graph entity by device/topic id
   and append each signal value to the bounded recent-values buffer. An unresolved device is
   dropped, not raised, so a stray/hostile packet never crashes the stream (§7).
2. `get_recent_values` — the raw recent-values feed for one entity (Live Bench / Foxglove CON-03).
3. `get_telemetry` — the W0-07 `SolSystems.get_telemetry(project_id, window)` shape: a bounded,
   batch-summarized SEQUENCE of window-summaries computed DETERMINISTICALLY from the buffer
   (per-signal mean/min/max/last/count). No LLM narration, no S3 `raw_ref` — those are later SYS /
   Live Bench work; this method's signature matches the Protocol so it composes behind it.

The buffer is bounded per signal, so ingestion is backpressure/sub-sampling friendly by
construction. All reads are project-scoped.
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from solus_api.agent.interfaces import (
    TelemetrySummaryView,
    TelemetryWindow,
    TelemetryWindowSummary,
)
from solus_api.graph.buffer import TelemetryBuffer
from solus_api.graph.packet import (
    DeviceRecentView,
    RecentSample,
    RecentValuesView,
    SignalSeries,
    TelemetryPacket,
)
from solus_api.graph.resolver import EntityResolver

logger = logging.getLogger(__name__)

OBSERVED_DEVICE_TTL_SECONDS = 15.0
OBSERVED_DEVICE_CAP = 128
OBSERVED_PROJECT_CAP = 256

DEFAULT_SUMMARY_BUCKETS = 6  # sub-windows get_telemetry splits a window into (a progression)
#: SOLUSDEV-72 device ring bounds — drop-new at the cap so a hostile stream can
#: grow neither the per-project device-key space nor the per-device signal space.
#: Sized for a "watch the arm before it's in the graph" view, not an archive:
#: worst case ≈ 16×16×256 samples ≈ tens of MB per project, not the ~1 GB the
#: security review measured at 64×64×512. ponytail: drop-new; LRU if churn matters.
DEFAULT_UNRESOLVED_DEVICE_CAP = 16
DEFAULT_UNRESOLVED_SIGNALS_PER_DEVICE = 16
DEFAULT_UNRESOLVED_SAMPLES_CAP = 256


class IngestResult(BaseModel):
    """Outcome of ingesting one packet. `entity_id` is None when the device didn't resolve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: UUID | None
    accepted: int  # number of signal values buffered
    signals: list[str]


def _signal_stats(samples: list[RecentSample]) -> dict[str, float]:
    """Deterministic compact stats for one signal within a window (no LLM)."""
    values = [s.value for s in samples]
    last = max(samples, key=lambda s: s.timestamp).value
    return {
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "last": last,
        "count": float(len(values)),
    }


class TelemetryPlumbing:
    """Attaches telemetry streams to graph entities and serves bounded reads over them."""

    def __init__(
        self,
        buffer: TelemetryBuffer,
        resolver: EntityResolver,
        *,
        clock: Callable[[], float] = time.monotonic,
        summary_buckets: int = DEFAULT_SUMMARY_BUCKETS,
        unresolved_device_cap: int = DEFAULT_UNRESOLVED_DEVICE_CAP,
        unresolved_samples_cap: int = DEFAULT_UNRESOLVED_SAMPLES_CAP,
    ) -> None:
        if summary_buckets <= 0:
            raise ValueError("summary_buckets must be positive")
        self.capture_sink: Callable[[UUID, UUID | None, TelemetryPacket], None] | None = None
        self._observed_entities: dict[tuple[UUID, str], UUID | None] = {}
        self._next_observed_sweep = 0.0
        self._clock = clock
        self._observed_devices: dict[UUID, dict[str, float]] = {}
        self._buffer = buffer
        self._resolver = resolver
        self._buckets = summary_buckets
        self._device_cap = unresolved_device_cap
        self._device_samples_cap = unresolved_samples_cap
        #: SOLUSDEV-72: project → device_id → signal → bounded samples. Holds the
        #: stream for devices with NO graph entity yet, so Live Bench can show a
        #: connected arm before RBT-05 reconciles it. Ephemeral, like the buffer.
        self._device_rings: dict[UUID, dict[str, dict[str, deque[RecentSample]]]] = {}

    def _expire_observed_devices(self, now: float) -> None:
        for project_id, devices in list(self._observed_devices.items()):
            for device_id, last_seen in list(devices.items()):
                if now - last_seen >= OBSERVED_DEVICE_TTL_SECONDS:
                    del devices[device_id]
                    self._observed_entities.pop((project_id, device_id), None)
            if not devices:
                del self._observed_devices[project_id]

    def observed_device_ids(self, project_id: UUID) -> list[str]:
        """Recent arrival evidence only; this never opens or owns a device."""
        self._expire_observed_devices(self._clock())
        return sorted(self._observed_devices.get(project_id, {}))

    def _observe_device(self, project_id: UUID, device_id: str) -> None:
        now = self._clock()
        if now >= self._next_observed_sweep:
            self._expire_observed_devices(now)
            self._next_observed_sweep = now + 1.0
        devices = self._observed_devices.get(project_id)
        if devices is None:
            if len(self._observed_devices) >= OBSERVED_PROJECT_CAP:
                return
            devices = self._observed_devices[project_id] = {}
        if device_id in devices or len(devices) < OBSERVED_DEVICE_CAP:
            devices[device_id] = now

    async def ingest(
        self, project_id: UUID, packet: TelemetryPacket, *, session_id: UUID | None = None
    ) -> IngestResult:
        if self.capture_sink is not None:
            try:
                self.capture_sink(project_id, session_id, packet)
            except Exception as exc:
                logger.warning(
                    "run capture sink failed: project=%s error=%s", project_id, type(exc).__name__
                )
        entity_id = await self._resolver.resolve(project_id, packet.device_id)
        self._observe_device(project_id, packet.device_id)
        if packet.device_id in self._observed_devices.get(project_id, {}):
            self._observed_entities[(project_id, packet.device_id)] = entity_id
        if entity_id is None:
            self._buffer_unresolved(project_id, packet)
            return IngestResult(entity_id=None, accepted=0, signals=[])
        # A device that just resolved (RBT-05 confirmed it) drops its unresolved
        # ring: the entity feed is the home now — stale pre-link samples must not
        # keep serving from the device view.
        devices = self._device_rings.get(project_id)
        if devices is not None:
            devices.pop(packet.device_id, None)
        for signal, value in packet.values.items():
            await self._buffer.append(
                project_id,
                entity_id,
                signal,
                packet.timestamp,
                value,
                unit=packet.units.get(signal),
            )
        return IngestResult(
            entity_id=entity_id, accepted=len(packet.values), signals=sorted(packet.values)
        )

    def _buffer_unresolved(self, project_id: UUID, packet: TelemetryPacket) -> None:
        devices = self._device_rings.setdefault(project_id, {})
        ring = devices.get(packet.device_id)
        if ring is None:
            if len(devices) >= self._device_cap:
                logger.debug(
                    "unresolved device dropped at cap: project=%s device_id=%r",
                    project_id,
                    packet.device_id[:64],
                )
                return
            ring = devices[packet.device_id] = {}
        for signal, value in packet.values.items():
            samples = ring.get(signal)
            if samples is None:
                if len(ring) >= DEFAULT_UNRESOLVED_SIGNALS_PER_DEVICE:
                    continue  # drop-new: bounded signal-name space per device
                samples = ring[signal] = deque(maxlen=self._device_samples_cap)
            samples.append(
                RecentSample(timestamp=packet.timestamp, value=value, unit=packet.units.get(signal))
            )

    def observed_entity_ids(self, project_id: UUID, device_ids: list[str]) -> set[UUID]:
        self._expire_observed_devices(self._clock())
        return {
            entity
            for device_id in device_ids[:64]
            if (entity := self._observed_entities.get((project_id, device_id))) is not None
        }

    async def snapshot_device(self, project_id: UUID, device_id: str) -> DeviceRecentView:
        """Memory-only latest ingest resolution; callers authorize visible resolved entities."""
        entity_id = self._observed_entities.get((project_id, device_id))
        if entity_id is not None:
            names = (await self._buffer.signal_names(project_id, entity_id))[:64]
            recent = await self.get_recent_values(project_id, entity_id, signals=names, limit=512)
            return DeviceRecentView(
                device_id=device_id, resolved_entity_id=entity_id, signals=recent.signals
            )
        ring = self._device_rings.get(project_id, {}).get(device_id, {})
        return DeviceRecentView(
            device_id=device_id,
            resolved_entity_id=None,
            signals=[
                SignalSeries(signal=name, points=list(samples)[-512:])
                for name, samples in sorted(ring.items())
            ],
        )

    async def get_device_recent(
        self, project_id: UUID, device_id: str, *, limit: int | None = None
    ) -> DeviceRecentView:
        """Read the unresolved ring or the resolved entity's project-scoped feed."""
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        entity_id = await self._resolver.resolve(project_id, device_id)
        if entity_id is not None:
            recent = await self.get_recent_values(project_id, entity_id, limit=limit)
            return DeviceRecentView(
                device_id=device_id, resolved_entity_id=entity_id, signals=recent.signals
            )
        ring = self._device_rings.get(project_id, {}).get(device_id, {})
        series = [
            SignalSeries(
                signal=name,
                points=[] if limit == 0 else list(samples)[-limit:] if limit else list(samples),
            )
            for name, samples in sorted(ring.items())
        ]
        return DeviceRecentView(device_id=device_id, resolved_entity_id=entity_id, signals=series)

    async def get_recent_values(
        self,
        project_id: UUID,
        entity_id: UUID,
        *,
        signals: list[str] | None = None,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> RecentValuesView:
        names = (
            signals
            if signals is not None
            else await self._buffer.signal_names(project_id, entity_id)
        )
        series = [
            SignalSeries(
                signal=name,
                points=await self._buffer.recent(
                    project_id, entity_id, name, limit=limit, since=since
                ),
            )
            for name in names
        ]
        return RecentValuesView(entity_id=entity_id, signals=series)

    async def _collect(
        self, project_id: UUID, wanted: set[str] | None
    ) -> dict[str, list[RecentSample]]:
        """Gather buffered samples across the project, grouped by signal name (aggregated across
        entities). `wanted` narrows to specific signals when provided."""
        grouped: dict[str, list[RecentSample]] = {}
        for entity_id in await self._buffer.entity_ids(project_id):
            for signal in await self._buffer.signal_names(project_id, entity_id):
                if wanted is not None and signal not in wanted:
                    continue
                samples = await self._buffer.recent(project_id, entity_id, signal)
                if samples:
                    grouped.setdefault(signal, []).extend(samples)
        return grouped

    async def get_telemetry(
        self, project_id: UUID, window: TelemetryWindow
    ) -> TelemetrySummaryView:
        wanted = set(window.signals) if window.signals is not None else None
        grouped = await self._collect(project_id, wanted)
        if not grouped:
            return TelemetrySummaryView(windows=[])

        now = max(s.timestamp for samples in grouped.values() for s in samples)
        start = now - timedelta(seconds=window.duration_seconds)
        width = window.duration_seconds / self._buckets

        # Bucket every sample into one of `self._buckets` equal sub-windows over [start, now].
        buckets: list[dict[str, list[RecentSample]]] = [{} for _ in range(self._buckets)]
        for signal, samples in grouped.items():
            for sample in samples:
                if sample.timestamp < start:
                    continue
                offset = (sample.timestamp - start).total_seconds()
                idx = min(self._buckets - 1, int(offset / width)) if width > 0 else 0
                buckets[idx].setdefault(signal, []).append(sample)

        windows: list[TelemetryWindowSummary] = []
        for idx, bucket in enumerate(buckets):
            if not bucket:
                continue
            signals = {signal: _signal_stats(samples) for signal, samples in bucket.items()}
            total = sum(int(stats["count"]) for stats in signals.values())
            windows.append(
                TelemetryWindowSummary(
                    window_start=start + timedelta(seconds=idx * width),
                    window_end=start + timedelta(seconds=(idx + 1) * width),
                    summary=f"{len(signals)} signal(s), {total} sample(s)",
                    signals=signals,
                )
            )
        return TelemetrySummaryView(windows=windows)
