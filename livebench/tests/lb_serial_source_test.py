"""LB-02: serial packet source — LB-06 JSON lines over a REAL pyserial link (pty pair)."""

import asyncio
import os
from datetime import UTC, datetime

import serial as pyserial
from livebench.telemetry.serial_source import SerialPacketSource
from solus_api.graph.codec import encode_json
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def clock() -> datetime:
    return T0


async def test_lb06_wire_lines_over_a_real_pty_serial_link() -> None:
    # A firmware that speaks the LB-06 wire: its own device_id is trusted (one wire,
    # one claimant), consistent across the stream; a garbage line drops itself.
    master, slave = os.openpty()
    p1 = TelemetryPacket(device_id="motor-3", timestamp=T0, values={"rpm": 1200.0}, seq=1)
    p2 = TelemetryPacket(device_id="motor-3", timestamp=T0, values={"rpm": 1210.0}, seq=2)
    # Open the port BEFORE writing: opening the slave reconfigures termios and
    # discards anything buffered ahead of it.
    port = pyserial.Serial(os.ttyname(slave), baudrate=115200, timeout=0.2)
    os.write(master, encode_json(p1).encode() + b"\n")
    os.write(master, b"garbage not json\n")
    os.write(master, encode_json(p2).encode() + b"\n")

    source = SerialPacketSource(port, clock=clock)
    received = []
    async for p in source:
        received.append(p)
        if len(received) == 2:
            await source.aclose()
    os.close(master)
    os.close(slave)

    assert received == [p1, p2]  # firmware identity + seq preserved; garbage dropped


async def test_generic_json_lines_get_the_port_identity() -> None:
    # A firmware that speaks plain JSON (not the LB-06 wire): every line is pinned to
    # the port identity and stamped with the arrival clock.
    master, slave = os.openpty()
    slave_name = os.ttyname(slave)
    port = pyserial.Serial(slave_name, baudrate=115200, timeout=0.2)
    os.write(master, b'{"imu": {"ax": 0.5}}\n')
    os.write(master, b"garbage not json\n")
    os.write(master, b'{"volt": 12.1}\n')

    source = SerialPacketSource(port, clock=clock)
    received = []
    async for p in source:
        received.append(p)
        if len(received) == 2:
            await source.aclose()
    os.close(master)
    os.close(slave)

    assert received[0].device_id == f"serial:{slave_name}"
    assert received[0].values == {"imu.ax": 0.5}
    assert received[0].timestamp == T0
    assert received[1].values == {"volt": 12.1}


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


async def test_oversized_line_is_dropped_stream_survives() -> None:
    master, slave = os.openpty()
    port = pyserial.Serial(os.ttyname(slave), baudrate=115200, timeout=0.2)
    source = SerialPacketSource(port, clock=clock, max_line_bytes=4096)
    # An over-long line (no valid JSON) followed by a good one. A pty's input
    # queue is small on macOS — a 6000-byte write blocks until the reader drains
    # it — so the bytes are fed from a thread WHILE the source reads; on Linux
    # the whole write lands at once with the same outcome.
    payload = b"x" * 6000 + b"\n" + b'{"ok": 1.0}\n'
    writer = asyncio.get_running_loop().run_in_executor(None, _write_all, master, payload)
    received = []
    async for p in source:
        received.append(p)
        await source.aclose()
    await writer
    os.close(master)
    os.close(slave)

    assert len(received) == 1
    assert received[0].values == {"ok": 1.0}


async def test_identity_change_mid_stream_is_dropped() -> None:
    # Security M3: the serial link is unauthenticated; a device that relabels itself
    # mid-stream must not attach telemetry to a different graph entity.
    from solus_api.graph.codec import encode_json

    master, slave = os.openpty()
    slave_name = os.ttyname(slave)
    port = pyserial.Serial(slave_name, baudrate=115200, timeout=0.2)

    first = TelemetryPacket(device_id="motor-1", timestamp=T0, values={"rpm": 1.0}, seq=1)
    impostor = TelemetryPacket(device_id="bms-main", timestamp=T0, values={"volts": 48.0}, seq=2)
    third = TelemetryPacket(device_id="motor-1", timestamp=T0, values={"rpm": 2.0}, seq=3)
    for pkt in (first, impostor, third):
        os.write(master, encode_json(pkt).encode() + b"\n")

    source = SerialPacketSource(port, clock=clock)
    received = []
    async for p in source:
        received.append(p)
        if len(received) == 2:
            await source.aclose()
    os.close(master)
    os.close(slave)

    # The impostor identity is dropped; only the pinned device's packets survive.
    assert [p.device_id for p in received] == ["motor-1", "motor-1"]
    assert [p.values["rpm"] for p in received] == [1.0, 2.0]
