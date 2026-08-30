"""The generic packet-stream LiveConnection base passes the MCP-02 conformance suite."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from livebench.telemetry.stream_live import PacketStreamLiveConnection
from solus_api.agent.interfaces import TelemetryWindow
from solus_api.connectors.live_conformance import assert_live_connection_contract
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class QueueSource:
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


class DemoConnection(PacketStreamLiveConnection):
    provider: ClassVar[str] = "demo"


def packet(sec: float) -> TelemetryPacket:
    return TelemetryPacket(
        device_id="dev", timestamp=T0 + timedelta(seconds=sec), values={"v": sec}
    )


async def test_base_class_passes_the_conformance_suite() -> None:
    source = QueueSource()
    conn = DemoConnection(source=source)

    async def emit() -> None:
        await source.push(packet(0.0), packet(0.5), packet(1.5))

    try:
        await assert_live_connection_contract(
            conn, emit=emit, window=TelemetryWindow(duration_seconds=1.0)
        )
    finally:
        await conn.aclose()
    assert source.closed


async def test_tap_sees_every_pumped_packet_in_order() -> None:
    source = QueueSource()
    conn = DemoConnection(source=source)
    tapped: list[TelemetryPacket] = []

    async def tap(p: TelemetryPacket) -> None:
        tapped.append(p)

    conn.tap = tap
    await conn.subscribe(TelemetryWindow(duration_seconds=10.0))
    try:
        await source.push(packet(0.0), packet(0.5), packet(1.5))
    finally:
        await conn.aclose()
    assert [p.timestamp for p in tapped] == [
        p.timestamp for p in (packet(0.0), packet(0.5), packet(1.5))
    ]


async def test_raising_tap_never_kills_the_pump_or_starves_subscribers() -> None:
    source = QueueSource()
    conn = DemoConnection(source=source)

    async def bad_tap(p: TelemetryPacket) -> None:
        raise RuntimeError("tap exploded")

    conn.tap = bad_tap
    received: list[object] = []

    async def collect(summary: object) -> None:
        received.append(summary)

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(handle, collect)
    try:
        await source.push(packet(0.0), packet(0.5), packet(1.5))  # 1.5 closes the first window
    finally:
        await conn.aclose()
    assert received, "windows must still deliver when the tap raises"


async def test_conformance_suite_passes_with_a_tap_installed() -> None:
    source = QueueSource()
    conn = DemoConnection(source=source)
    tapped: list[TelemetryPacket] = []

    async def tap(p: TelemetryPacket) -> None:
        tapped.append(p)

    conn.tap = tap

    async def emit() -> None:
        await source.push(packet(0.0), packet(0.5), packet(1.5))

    try:
        await assert_live_connection_contract(
            conn, emit=emit, window=TelemetryWindow(duration_seconds=1.0)
        )
    finally:
        await conn.aclose()
    assert tapped, "the tap must observe the conformance run's packets"
