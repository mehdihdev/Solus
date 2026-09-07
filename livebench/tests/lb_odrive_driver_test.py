"""ODrive CAN driver over the recorded `can_odrive_base.json` fixture: a LISTEN source that
decodes CANSimple frames by node into `<part>.position|velocity|current|voltage` packets, named
from the config's bus map (`0x10` → left_wheel) or by address when unnamed."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from livebench.hardware.channel import Frame
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.replay import RecordedFrame, ReplayChannel, load_recording
from livebench.plugins.odrive.odrive_codec import odrive_arbitration_id, odrive_pack_pair
from livebench.plugins.odrive.odrive_definitions import (
    ODRIVE_CMD_BUS_VOLTAGE_CURRENT,
    ODRIVE_CMD_GET_ENCODER_ESTIMATES,
    ODRIVE_CMD_GET_IQ,
    ODRIVE_CMD_HEARTBEAT,
)
from livebench.plugins.odrive.odrive_driver import OdriveCanDriver, OdriveParams
from livebench.telemetry.stream_live import PacketSource
from pydantic import ValidationError
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportBinding, TransportKind

FIXTURE = Path(__file__).parent / "fixtures" / "can_odrive_base.json"
BINDING = "ODRV-3F2A-CAN0"
IDENTITY = TransportBinding(kind=TransportKind.USB_CAN, binding=BINDING)
NODES = (0x10, 0x11)
WHEEL_VELOCITY_REV_S = {0x10: 1.5, 0x11: 1.25}
DURATION_S = 2.0
#: axis_error 0, axis_state 8 (CLOSED_LOOP_CONTROL), procedure_result 0, trajectory_done 1.
HEARTBEAT_CLOSED_LOOP = bytes.fromhex("0000000008000100")


def _generate_frames() -> list[dict[str, object]]:
    """~2 s of a two-axis base: heartbeats 10 Hz, encoder estimates 50 Hz, Iq 10 Hz, bus
    voltage 1 Hz per node — the generator that produced the committed fixture."""
    rows: list[tuple[float, str, str]] = []

    def add(t: float, node: int, cmd: int, payload: bytes) -> None:
        rows.append((round(t, 3), f"0x{odrive_arbitration_id(node, cmd):03x}", payload.hex()))

    for index, node in enumerate(NODES):
        velocity = WHEEL_VELOCITY_REV_S[node]
        for k in range(int(DURATION_S * 50)):
            add(
                k / 50,
                node,
                ODRIVE_CMD_GET_ENCODER_ESTIMATES,
                odrive_pack_pair(velocity * k / 50, velocity),
            )
        for k in range(int(DURATION_S * 10)):
            add(k / 10, node, ODRIVE_CMD_HEARTBEAT, HEARTBEAT_CLOSED_LOOP)
            add(k / 10, node, ODRIVE_CMD_GET_IQ, odrive_pack_pair(2.0, 1.9 + 0.05 * index))
        for k in range(int(DURATION_S)):
            add(
                float(k),
                node,
                ODRIVE_CMD_BUS_VOLTAGE_CURRENT,
                odrive_pack_pair(24.1 - 0.01 * k, 1.2),
            )
    rows.sort()
    return [{"t": t, "hex": hex_, "address": address} for t, address, hex_ in rows]


def _odrive_config(
    bus_map: list[dict[str, Any]], parts: dict[str, Any] | None = None
) -> HardwareConfig:
    return HardwareConfig.model_validate(
        {
            "robot_entity_id": str(uuid.uuid4()),
            "identity": IDENTITY.model_dump(mode="json"),
            "protocol": {
                "driver_id": "odrive-can",
                "params": {"bitrate": 250_000, "timeout_s": 0.01},
            },
            "bus_map": bus_map,
            "parts": parts or {},
            "provenance": {
                "identity": {"by": "detected"},
                "protocol": {"by": "user"},
                "bus_map": {"by": "detected"},
                "parts": {"by": "user"},
            },
        }
    )


def _wheels_config() -> HardwareConfig:
    left, right = str(uuid.uuid4()), str(uuid.uuid4())
    return _odrive_config(
        bus_map=[
            {"protocol": "odrive-can", "address": "0x10", "part_entity_id": left},
            {"protocol": "odrive-can", "address": "0x11", "part_entity_id": right},
        ],
        parts={
            left: {"telemetry": [{"name": "left_wheel.velocity", "unit": "rev/s"}]},
            right: {"telemetry": [{"name": "right_wheel.velocity", "unit": "rev/s"}]},
        },
    )


def _open(
    config: HardwareConfig, frames: list[RecordedFrame]
) -> tuple[PacketSource, ReplayChannel]:
    channel = ReplayChannel(TransportKind.USB_CAN, IDENTITY, frames)
    registry = DriverRegistry()
    registry.register(OdriveCanDriver)
    return registry.open_source(config, channel), channel


async def _collect(source: PacketSource, count: int) -> list[TelemetryPacket]:
    async def take() -> list[TelemetryPacket]:
        packets: list[TelemetryPacket] = []
        async for packet in source:
            packets.append(packet)
            if len(packets) >= count:
                break
        return packets

    try:
        return await asyncio.wait_for(take(), timeout=5.0)
    finally:
        await source.aclose()


def test_fixture_is_the_generator_output_with_pinned_frames() -> None:
    recorded = json.loads(FIXTURE.read_text())

    assert recorded == {"transport": "usb_can", "binding": BINDING, "frames": _generate_frames()}
    frames = recorded["frames"]
    assert len(frames) == 284
    assert frames[0] == {"t": 0.0, "hex": "0000000008000100", "address": "0x201"}
    assert frames[1] == {"t": 0.0, "hex": "000000000000c03f", "address": "0x209"}
    assert frames[2] == {"t": 0.0, "hex": "000000403333f33f", "address": "0x214"}  # 2.0f, 1.9f
    assert frames[-1]["t"] == 1.98 and frames[-1]["address"] == "0x229"
    assert load_recording(FIXTURE).identity.device_ref == "can:ODRV-3F2A-CAN0"


async def test_driver_yields_part_named_signals_from_the_fixture() -> None:
    recording = load_recording(FIXTURE)
    source, channel = _open(_wheels_config(), recording.frames)

    packets = await _collect(source, 12)

    assert {p.device_id for p in packets} == {"can:ODRV-3F2A-CAN0"}
    assert packets[0].values == {"left_wheel.position": 0.0, "left_wheel.velocity": 1.5}
    assert packets[0].units == {"left_wheel.position": "rev", "left_wheel.velocity": "rev/s"}
    merged: dict[str, float] = {}
    for packet in packets:
        merged.update(packet.values)
    assert merged["right_wheel.velocity"] == 1.25
    assert merged["left_wheel.current"] == pytest.approx(1.9, rel=1e-6)
    assert merged["left_wheel.voltage"] == pytest.approx(24.1, rel=1e-6)
    assert [p.seq for p in packets] == list(range(12))
    assert channel.closed


async def test_unconfigured_nodes_are_named_by_address() -> None:
    recording = load_recording(FIXTURE)
    source, _ = _open(_odrive_config(bus_map=[]), recording.frames)

    packets = await _collect(source, 1)

    assert packets[0].values == {"addr_0x10.position": 0.0, "addr_0x10.velocity": 1.5}


async def test_junk_frames_cost_nothing_and_never_kill_the_stream() -> None:
    frames = [
        RecordedFrame(at_s=0.0, payload=b"\x00" * 8, address="zz"),  # not an arbitration id
        RecordedFrame(at_s=0.0, payload=b"\x00" * 8),  # no address at all
        RecordedFrame(at_s=0.0, payload=b"\x01\x02", address="0x209"),  # short encoder frame
        RecordedFrame(at_s=0.0, payload=HEARTBEAT_CLOSED_LOOP, address="0x201"),  # no signal
        RecordedFrame(at_s=0.0, payload=odrive_pack_pair(0.5, 1.5), address="0x209"),
    ]
    source, channel = _open(_wheels_config(), frames)

    packets = await _collect(source, 1)

    assert packets[0].values == {"left_wheel.position": 0.5, "left_wheel.velocity": 1.5}
    assert channel.sent == []  # a listener never transmits


def test_params_are_bounded_and_the_driver_rides_can_only() -> None:
    assert OdriveParams().bitrate == 250_000
    for bad in ({"bitrate": 5_000}, {"bitrate": 2_000_000}, {"timeout_s": 0}, {"baud": 9600}):
        with pytest.raises(ValidationError):
            OdriveParams.model_validate(bad)
    registry = DriverRegistry()
    registry.register(OdriveCanDriver)
    assert registry.catalog()[0]["driver_id"] == "odrive-can"
    assert registry.catalog()[0]["transports"] == ["usb_can"]
    serial_channel = ReplayChannel(TransportKind.USB_SERIAL, IDENTITY, [])
    with pytest.raises(ValueError):
        registry.open_source(_wheels_config(), serial_channel)
    assert Frame(payload=b"", address="0x201").address == "0x201"
