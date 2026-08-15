"""LB-02: reconnect-with-backoff wrapper around packet sources."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from livebench.telemetry.reconnect import ReconnectingSource
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def packet(sec: float) -> TelemetryPacket:
    return TelemetryPacket(
        device_id="dev", timestamp=T0 + timedelta(seconds=sec), values={"v": sec}
    )


class Burst:
    """One connection attempt: yields some packets, then ends or raises."""

    def __init__(self, packets: list[TelemetryPacket], *, then_raise: bool = False) -> None:
        self._packets = packets
        self._raise = then_raise
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        for p in self._packets:
            yield p
        if self._raise:
            raise ConnectionError("link dropped")

    async def aclose(self) -> None:
        self.closed = True


async def test_reconnects_across_source_ends_and_errors() -> None:
    bursts = [
        Burst([packet(0.0)], then_raise=True),
        Burst([]),  # a connection that yields nothing then drops
        Burst([packet(1.0), packet(2.0)]),
    ]
    made: list[Burst] = []
    naps: list[float] = []

    def factory() -> Burst:
        made.append(bursts[len(made)])
        return made[-1]

    async def nap(seconds: float) -> None:
        naps.append(seconds)

    source = ReconnectingSource(factory, backoff_start=0.5, backoff_cap=4.0, sleep=nap)
    received = []
    async for p in source:
        received.append(p)
        if len(received) == 3:
            await source.aclose()

    assert [p.values["v"] for p in received] == [0.0, 1.0, 2.0]
    assert all(b.closed for b in made[:2])  # every dead incarnation was cleaned up
    assert naps == [0.5, 1.0]  # doubling between attempts


async def test_backoff_resets_after_a_successful_packet() -> None:
    bursts = [
        Burst([], then_raise=True),
        Burst([], then_raise=True),
        Burst([packet(0.0)]),  # success resets the schedule
        Burst([], then_raise=True),
        Burst([packet(1.0)]),
    ]
    made: list[Burst] = []
    naps: list[float] = []

    def factory() -> Burst:
        made.append(bursts[len(made)])
        return made[-1]

    async def nap(seconds: float) -> None:
        naps.append(seconds)

    source = ReconnectingSource(factory, backoff_start=0.5, backoff_cap=30.0, sleep=nap)
    received = []
    async for p in source:
        received.append(p)
        if len(received) == 2:
            await source.aclose()

    # 3rd nap back at start (success reset it); 4th doubles again after the next failure.
    assert naps == [0.5, 1.0, 0.5, 1.0]


async def test_backoff_caps() -> None:
    naps: list[float] = []

    class AlwaysDead:
        async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
            return
            yield  # pragma: no cover

        async def aclose(self) -> None:
            return None

    attempts = 0

    def factory() -> AlwaysDead:
        nonlocal attempts
        attempts += 1
        return AlwaysDead()

    async def nap(seconds: float) -> None:
        naps.append(seconds)
        await asyncio.sleep(0)  # a fake sleep must still yield, or the loop starves

    source = ReconnectingSource(factory, backoff_start=1.0, backoff_cap=4.0, sleep=nap)

    async def drain() -> None:
        async for _ in source:  # pragma: no cover - nothing ever arrives
            raise AssertionError

    task = asyncio.create_task(drain())
    while len(naps) < 5:
        await asyncio.sleep(0)
    await source.aclose()
    task.cancel()

    assert naps[:5] == [1.0, 2.0, 4.0, 4.0, 4.0]  # capped, never unbounded


async def test_aclose_stops_promptly() -> None:
    source = ReconnectingSource(lambda: Burst([packet(0.0)]), sleep=asyncio.sleep)
    received = []
    async for p in source:
        received.append(p)
        await source.aclose()

    assert len(received) == 1
