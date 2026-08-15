"""LB-02: observers ride the stream — events out the side, packets pass through untouched."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from livebench.anomaly.observers import ObserverEvent, ThresholdObserver
from livebench.telemetry.observing_source import ObservingSource
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class ListSource:
    def __init__(self, packets: list[TelemetryPacket]) -> None:
        self._packets = packets
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        for p in self._packets:
            yield p

    async def aclose(self) -> None:
        self.closed = True


def packet(sec: float, temp: float) -> TelemetryPacket:
    return TelemetryPacket(
        device_id="dev", timestamp=T0 + timedelta(seconds=sec), values={"temp": temp}
    )


async def test_events_emit_and_packets_pass_through() -> None:
    packets = [packet(0.0, 40.0), packet(1.0, 95.0), packet(2.0, 41.0)]
    events: list[ObserverEvent] = []

    async def on_event(event: ObserverEvent) -> None:
        events.append(event)

    inner = ListSource(packets)
    source = ObservingSource(
        inner, observers=[ThresholdObserver(signal="temp", high=80.0)], on_event=on_event
    )

    passed = [p async for p in source]
    await source.aclose()

    assert passed == packets  # observation never mutates or drops the stream
    assert [e.kind for e in events] == ["threshold_breach"]
    assert events[0].value == 95.0
    assert inner.closed


async def test_broken_event_sink_does_not_kill_the_stream() -> None:
    async def explode(event: ObserverEvent) -> None:
        raise RuntimeError("sink bug")

    source = ObservingSource(
        ListSource([packet(0.0, 95.0), packet(1.0, 96.0)]),
        observers=[ThresholdObserver(signal="temp", high=80.0)],
        on_event=explode,
    )

    passed = [p async for p in source]

    assert len(passed) == 2
