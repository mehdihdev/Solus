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


async def test_factory_runs_off_the_event_loop_thread() -> None:
    # The serial factory blocks (pyserial open can wedge for seconds); a reconnect
    # must never stall the event loop while re-opening the device (SOLUSDEV-72).
    import threading

    loop_thread = threading.get_ident()
    factory_threads: list[int] = []

    def factory() -> Burst:
        factory_threads.append(threading.get_ident())
        return Burst([packet(float(len(factory_threads)))])

    source = ReconnectingSource(factory, sleep=asyncio.sleep)
    received = []
    async for p in source:
        received.append(p)
        if len(received) == 2:  # second packet proves the RE-open also ran off-loop
            await source.aclose()

    assert len(factory_threads) >= 2
    assert all(t != loop_thread for t in factory_threads)


async def test_factory_failures_retry_with_capped_backoff_and_recover() -> None:
    attempts = 0
    naps: list[float] = []
    recovered = Burst([packet(1)])

    def factory() -> Burst:
        nonlocal attempts
        attempts += 1
        if attempts <= 4:
            raise OSError("device is still unplugged")
        return recovered

    async def nap(seconds: float) -> None:
        naps.append(seconds)

    source = ReconnectingSource(factory, backoff_start=0.5, backoff_cap=1, sleep=nap)
    received = []
    async for value in source:
        received.append(value)
        await source.aclose()
    assert received == [packet(1)]
    assert naps == [0.5, 1, 1, 1]
    assert recovered.closed


async def test_close_during_factory_discards_and_closes_late_source() -> None:
    import threading

    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    opened = Burst([packet(1)])

    def factory() -> Burst:
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=2)
        return opened

    source = ReconnectingSource(factory)
    iterator = source.__aiter__()
    pending = asyncio.create_task(anext(iterator, None))
    await asyncio.wait_for(started.wait(), 1)
    try:
        await source.aclose()
    finally:
        release.set()
    assert await asyncio.wait_for(pending, 1) is None
    assert opened.closed


async def test_cancellation_during_factory_closes_late_source() -> None:
    import threading

    import pytest

    started = asyncio.Event()
    closed = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class TrackedBurst(Burst):
        async def aclose(self) -> None:
            await super().aclose()
            closed.set()

    opened = TrackedBurst([packet(1)])

    def factory() -> Burst:
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=2)
        return opened

    source = ReconnectingSource(factory)
    pending = asyncio.create_task(anext(source.__aiter__()))
    await asyncio.wait_for(started.wait(), 1)
    pending.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await pending
    finally:
        release.set()
    await asyncio.wait_for(closed.wait(), 1)
    assert opened.closed


async def test_close_interrupts_backoff_without_another_open() -> None:
    sleeping = asyncio.Event()
    attempts = 0

    def factory() -> Burst:
        nonlocal attempts
        attempts += 1
        return Burst([])

    async def nap(seconds: float) -> None:
        sleeping.set()
        await asyncio.sleep(30)

    source = ReconnectingSource(factory, sleep=nap)
    pending = asyncio.create_task(anext(source.__aiter__(), None))
    await asyncio.wait_for(sleeping.wait(), 1)
    await source.aclose()
    assert await asyncio.wait_for(pending, 1) is None
    assert attempts == 1
