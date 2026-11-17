"""LB-02: robot LiveConnections — transports + reconnect + observers composed."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import serial
import websockets
from livebench.anomaly.observers import ObserverEvent, ThresholdObserver
from livebench.hardware.serial_owner import Claimant, PortListener, SerialOwner
from livebench.telemetry.robot import SerialRobotConnection, WsRobotConnection
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.graph.codec import encode
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.sessions import DeviceBusyError

T0 = datetime(2026, 1, 1, tzinfo=UTC)
REF = "usb:5B42135040"


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
    with pytest.raises(Exception):  # noqa: B017 - pyserial raises SerialException(OSError)
        SerialRobotConnection.open("/dev/does-not-exist-9999", owner=SerialOwner())


class _Opener:
    """pyserial's signature over `loop://`; each port it opens already holds `line`."""

    def __init__(self, line: bytes = b"") -> None:
        self.line = line
        self.calls: list[dict[str, Any]] = []

    def __call__(self, device: str, baud: int, **kwargs: Any) -> serial.Serial:
        self.calls.append({"device": device, "baud": baud, **kwargs})
        port = serial.serial_for_url("loop://", baud, timeout=0.05)
        port.write(self.line)
        return port


def _never() -> serial.Serial:
    raise AssertionError("a listener never opens the port")


def test_legacy_serial_opens_are_exclusive_through_the_serial_owner() -> None:
    """SOLUSDEV-326: the legacy opens were not exclusive, so a second reader stole bytes."""
    owner, opener = SerialOwner(), _Opener()
    SerialRobotConnection.open("/dev/fake0", 9600, device_ref=REF, opener=opener, owner=owner)
    assert opener.calls == [
        {"device": "/dev/fake0", "baud": 9600, "timeout": 1.0, "exclusive": True}
    ]
    project, member = uuid.uuid4(), uuid.uuid4()
    upload = Claimant("upload", str(project), str(member))
    with owner.holding(REF, upload):  # the fail-fast probe let go
        for user_id, holder in ((member, "upload"), (uuid.uuid4(), None)):
            with pytest.raises(DeviceBusyError) as busy:
                SerialRobotConnection.open(
                    "/dev/fake0",
                    device_ref=REF,
                    project_id=project,
                    user_id=user_id,
                    opener=opener,
                    owner=owner,
                )
            assert busy.value.holder == holder  # named to its own member, never to a teammate
    assert len(opener.calls) == 1
    with owner.holding("/dev/fake1", Claimant("upload")):  # no device ref: its path is the key
        with pytest.raises(DeviceBusyError) as busy:
            SerialRobotConnection.open("/dev/fake1", opener=opener, owner=owner)
    assert busy.value.holder is None  # an open for no project is never told the holder


async def test_a_legacy_session_holds_its_port_while_it_streams() -> None:
    owner, project, member = SerialOwner(), uuid.uuid4(), uuid.uuid4()
    opener = _Opener(b'{"imu": {"ax": 0.5}}\n')
    conn = SerialRobotConnection.open(
        "/dev/fake0",
        device_ref=REF,
        project_id=project,
        user_id=member,
        opener=opener,
        owner=owner,
    )
    seen: list[TelemetryPacket] = []

    async def tap(packet: TelemetryPacket) -> None:
        seen.append(packet)

    conn.tap = tap
    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    for _ in range(300):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen and seen[0].values == {"imu.ax": 0.5}
    mine = Claimant("session", str(project), str(member))
    assert pytest.raises(DeviceBusyError, owner.hold, REF, mine, _never).value.holder == "session"
    listener = owner.claim(REF, Claimant("interrogation", str(project), str(member)), _never)
    assert isinstance(listener, PortListener)  # its own member's inspection listens instead
    listener.close()
    teammate = Claimant("interrogation", str(project), str(uuid.uuid4()))
    assert pytest.raises(DeviceBusyError, owner.claim, REF, teammate, _never).value.holder is None
    await conn.unsubscribe(handle)
    await conn.aclose()
    owner.hold(REF, mine, lambda: opener("/dev/fake0", 9600)).close()  # the session let go
