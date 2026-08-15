"""LB-02: robot LiveConnections — transports + reconnect + observers composed."""

import asyncio
from datetime import UTC, datetime, timedelta

import websockets
from livebench.anomaly.observers import ObserverEvent, ThresholdObserver
from livebench.telemetry.robot import SerialRobotConnection, WsRobotConnection
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.graph.codec import encode
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_providers() -> None:
    assert SerialRobotConnection.provider == "serial"
    assert WsRobotConnection.provider == "robot-ws"


async def test_ws_robot_streams_windows_and_observer_events() -> None:
    events: list[ObserverEvent] = []
    received: list[TelemetryWindowSummary] = []

    async def robot(ws: websockets.ServerConnection) -> None:
        for i in range(4):
            packet = TelemetryPacket(
                device_id="motor-1",
                timestamp=T0 + timedelta(seconds=0.6 * i),
                values={"temp": 40.0 + 30.0 * i},  # 40, 70, 100 (breach), 130
            )
            await ws.send(encode(packet))
        await asyncio.sleep(3)

    async def on_event(event: ObserverEvent) -> None:
        events.append(event)

    async with websockets.serve(robot, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        conn = WsRobotConnection.open(
            f"ws://127.0.0.1:{port}",
            observers=[ThresholdObserver(signal="temp", high=90.0)],
            on_event=on_event,
        )
        handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))

        async def collect(summary: TelemetryWindowSummary) -> None:
            received.append(summary)

        conn.on_batch(handle, collect)
        for _ in range(3000):
            await asyncio.sleep(0.001)
            if received and events:
                break
        await conn.aclose()

    assert received, "windows must flow through the composed connection"
    assert events and events[0].kind == "threshold_breach"
    assert events[0].device_id == "motor-1"


def test_serial_open_requires_an_existing_device() -> None:
    import pytest

    with pytest.raises(Exception):  # noqa: B017 - pyserial raises SerialException(OSError)
        SerialRobotConnection.open("/dev/does-not-exist-9999")
