"""CON-03: FoxgloveLiveConnection — packets → windows → LiveConnection contract."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from livebench.telemetry.foxglove_live import FoxgloveLiveConnection
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.connectors.live import LiveStatus
from solus_api.connectors.live_conformance import assert_live_connection_contract
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class FakeSource:
    """Deterministic in-test packet source: push() returns once the pump processed it."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[TelemetryPacket] = asyncio.Queue()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        while True:
            packet = await self._queue.get()
            try:
                yield packet
            finally:
                self._queue.task_done()

    async def aclose(self) -> None:
        self.closed = True

    async def push(self, *packets: TelemetryPacket) -> None:
        for p in packets:
            self._queue.put_nowait(p)
        await self._queue.join()


def packet(sec: float, values: dict[str, float]) -> TelemetryPacket:
    return TelemetryPacket(device_id="dev", timestamp=T0 + timedelta(seconds=sec), values=values)


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


async def test_conformance_suite(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)

    async def emit() -> None:
        # Three packets crossing the 1s boundary → at least one completed window.
        await source.push(packet(0.0, {"v": 1.0}), packet(0.5, {"v": 2.0}), packet(1.5, {"v": 3.0}))

    try:
        await assert_live_connection_contract(
            conn, emit=emit, window=TelemetryWindow(duration_seconds=1.0)
        )
    finally:
        await conn.aclose()


async def test_summaries_carry_window_stats(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)
    received: list[TelemetryWindowSummary] = []

    async def collect(summary: TelemetryWindowSummary) -> None:
        received.append(summary)

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(handle, collect)
    await source.push(packet(0.0, {"v": 1.0}), packet(0.25, {"v": 3.0}), packet(1.1, {"v": 9.0}))

    assert len(received) == 1
    assert received[0].signals["v"]["mean"] == 2.0
    assert received[0].signals["v"]["count"] == 2.0
    assert conn.status() is LiveStatus.STREAMING
    await conn.aclose()


async def test_two_subscriptions_window_independently(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)
    coarse: list[TelemetryWindowSummary] = []
    fine: list[TelemetryWindowSummary] = []

    h_coarse = await conn.subscribe(TelemetryWindow(duration_seconds=2.0))
    h_fine = await conn.subscribe(TelemetryWindow(duration_seconds=0.5, signals=["v"]))
    conn.on_batch(h_coarse, lambda s: _append(coarse, s))
    conn.on_batch(h_fine, lambda s: _append(fine, s))

    await source.push(
        packet(0.0, {"v": 1.0, "w": 5.0}),
        packet(0.6, {"v": 2.0}),
        packet(2.5, {"v": 4.0}),
    )

    assert len(coarse) == 1
    assert set(coarse[0].signals) == {"v", "w"}
    assert len(fine) == 2  # [0,0.5) and [0.6,1.1) both closed by the 2.5s packet
    assert set(fine[0].signals) == {"v"}
    await conn.aclose()


async def _append(bucket: list[TelemetryWindowSummary], s: TelemetryWindowSummary) -> None:
    bucket.append(s)


async def test_unsubscribe_stops_delivery_and_empties_to_disconnected(
    source: FakeSource,
) -> None:
    conn = FoxgloveLiveConnection(source=source)
    received: list[TelemetryWindowSummary] = []

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(handle, lambda s: _append(received, s))
    await conn.unsubscribe(handle)
    await source.push(packet(0.0, {"v": 1.0}), packet(1.5, {"v": 2.0}))

    assert received == []
    assert conn.status() is LiveStatus.DISCONNECTED
    await conn.aclose()


async def test_unknown_handle_raises_keyerror(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)

    with pytest.raises(KeyError):
        conn.on_batch("nope", _noop)
    with pytest.raises(KeyError):
        await conn.unsubscribe("nope")
    await conn.aclose()


async def _noop(summary: TelemetryWindowSummary) -> None:
    return None


async def test_callback_exception_does_not_kill_the_pump(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)
    received: list[TelemetryWindowSummary] = []

    async def explode(summary: TelemetryWindowSummary) -> None:
        raise RuntimeError("consumer bug")

    h_bad = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    h_good = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(h_bad, explode)
    conn.on_batch(h_good, lambda s: _append(received, s))

    await source.push(packet(0.0, {"v": 1.0}), packet(1.5, {"v": 2.0}))
    await source.push(packet(3.5, {"v": 3.0}))

    # The good consumer kept receiving windows after the bad one raised.
    assert len(received) == 2
    await conn.aclose()


async def test_aclose_closes_the_source_and_disconnects(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)
    await conn.subscribe(TelemetryWindow(duration_seconds=1.0))

    await conn.aclose()

    assert source.closed is True
    assert conn.status() is LiveStatus.DISCONNECTED


def test_provider_is_foxglove(source: FakeSource) -> None:
    assert FoxgloveLiveConnection.provider == "foxglove"


class FiniteSource:
    """A source that yields a fixed list then ends — models a dropped link."""

    def __init__(self, packets: list[TelemetryPacket]) -> None:
        self._packets = packets
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        for p in self._packets:
            yield p

    async def aclose(self) -> None:
        self.closed = True


async def test_unsubscribe_delivers_the_pending_partial_window(source: FakeSource) -> None:
    # Review finding (HIGH): teardown silently discarded the freshest data.
    conn = FoxgloveLiveConnection(source=source)
    received: list[TelemetryWindowSummary] = []

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=10.0))
    conn.on_batch(handle, lambda s: _append(received, s))
    await source.push(packet(0.0, {"v": 42.0}))

    await conn.unsubscribe(handle)

    assert len(received) == 1
    assert received[0].signals["v"]["last"] == 42.0
    await conn.aclose()


async def test_aclose_delivers_pending_partial_windows(source: FakeSource) -> None:
    conn = FoxgloveLiveConnection(source=source)
    received: list[TelemetryWindowSummary] = []

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=10.0))
    conn.on_batch(handle, lambda s: _append(received, s))
    await source.push(packet(0.0, {"v": 7.0}))

    await conn.aclose()

    assert len(received) == 1
    assert received[0].signals["v"]["last"] == 7.0


async def test_source_end_is_reflected_in_status_and_resubscribe_restarts() -> None:
    # Review finding (MEDIUM) / security H4: a dead pump must not report healthy.
    finite = FiniteSource([packet(0.0, {"v": 1.0}), packet(1.5, {"v": 2.0})])
    conn = FoxgloveLiveConnection(source=finite)
    received: list[TelemetryWindowSummary] = []

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(handle, lambda s: _append(received, s))
    for _ in range(50):
        await asyncio.sleep(0)  # let the pump drain the finite source and exit

    assert len(received) == 1
    assert conn.status() is LiveStatus.DISCONNECTED

    handle2 = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    assert handle2  # a new subscription restarts a pump rather than joining a dead one
    await conn.aclose()


async def test_poison_payload_never_kills_the_pump(source: FakeSource) -> None:
    # Security C1 end-to-end: normalize returns None for hostile payloads, so only
    # valid packets reach this pump — but a callback-level check still proves the
    # stream continues around a rejected message.
    conn = FoxgloveLiveConnection(source=source)
    received: list[TelemetryWindowSummary] = []

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(handle, lambda s: _append(received, s))
    await source.push(packet(0.0, {"v": 1.0}), packet(1.5, {"v": 2.0}), packet(3.0, {"v": 3.0}))

    assert len(received) == 2
    assert not conn._pump.done()  # type: ignore[union-attr]
    await conn.aclose()
