"""Dynamixel Protocol 2.0 driver: polls Present Position per configured bus-map address over
a recorded channel; names signals `<part>.position` from the config, converts ticks per the
part's calibration mode, and pays one sample — never the stream — for junk on the bus."""

import asyncio
import uuid
from typing import Any

import pytest
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.replay import RecordedFrame, ReplayChannel
from livebench.plugins.dynamixel.dynamixel_codec import dxl_read_request, dxl_status_packet
from livebench.plugins.dynamixel.dynamixel_definitions import DXL_REGISTERS
from livebench.plugins.dynamixel.dynamixel_driver import DynamixelDriver, DynamixelParams
from livebench.telemetry.stream_live import PacketSource
from pydantic import ValidationError
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportBinding, TransportKind

IDENTITY = TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42134331")
PRESENT_POSITION = DXL_REGISTERS["present_position"]


def _dxl_config(
    bus_map: list[dict[str, Any]], parts: dict[str, Any] | None = None, **params: Any
) -> HardwareConfig:
    return HardwareConfig.model_validate(
        {
            "robot_entity_id": str(uuid.uuid4()),
            "identity": IDENTITY.model_dump(mode="json"),
            "protocol": {
                "driver_id": "dynamixel-2",
                "params": {"poll_hz": 200, "timeout_s": 0.01, **params},
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


def _position_frame(servo_id: int, ticks: int) -> RecordedFrame:
    payload = dxl_status_packet(servo_id, ticks.to_bytes(4, "little", signed=True))
    return RecordedFrame(at_s=0.0, payload=payload)


def _open(config: HardwareConfig, frames: list[RecordedFrame]) -> tuple[Any, ReplayChannel]:
    channel = ReplayChannel(TransportKind.USB_SERIAL, IDENTITY, frames)
    registry = DriverRegistry()
    registry.register(DynamixelDriver)
    return registry.open_source(config, channel), channel


async def _first_packet(source: PacketSource) -> TelemetryPacket:
    packet = await asyncio.wait_for(anext(aiter(source)), timeout=2.0)
    await source.aclose()
    return packet


async def test_polls_each_configured_address_and_names_signals_from_the_config() -> None:
    shoulder = str(uuid.uuid4())
    config = _dxl_config(
        bus_map=[
            {
                "protocol": "dynamixel-2",
                "address": "1",
                "part_entity_id": shoulder,
                "model": "XM430-W350",
            },
            {"protocol": "dynamixel-2", "address": "6"},
        ],
        parts={
            shoulder: {
                "calibration": {"mode": "degrees"},
                "telemetry": [{"name": "shoulder_pan.position", "unit": "deg"}],
            }
        },
    )
    source, channel = _open(config, [_position_frame(1, 3072), _position_frame(6, 1000)])

    packet = await _first_packet(source)

    assert packet.device_id == "usb:5B42134331"
    assert packet.values == {
        "shoulder_pan.position": pytest.approx(90.0),
        "addr_6.position": 1000.0,
    }
    assert packet.units == {"shoulder_pan.position": "deg", "addr_6.position": "ticks"}
    assert packet.seq == 0
    assert [f.payload for f in channel.sent] == [
        dxl_read_request(1, PRESENT_POSITION),
        dxl_read_request(6, PRESENT_POSITION),
    ]
    assert channel.closed


async def test_range_modes_report_percent_from_the_calibration_range() -> None:
    gripper, wrist = str(uuid.uuid4()), str(uuid.uuid4())
    config = _dxl_config(
        bus_map=[
            {"protocol": "dynamixel-2", "address": "5", "part_entity_id": gripper},
            {"protocol": "dynamixel-2", "address": "4", "part_entity_id": wrist},
        ],
        parts={
            gripper: {
                "calibration": {
                    "mode": "range_0_100",
                    "values": {"range_min": 1000, "range_max": 3000},
                },
                "telemetry": [{"name": "gripper.position", "unit": "%"}],
            },
            wrist: {
                "calibration": {
                    "mode": "range_m100_100",
                    "values": {"range_min": 1000, "range_max": 3000},
                },
                "telemetry": [{"name": "wrist_roll.position", "unit": "%"}],
            },
        },
    )
    source, _ = _open(config, [_position_frame(5, 2500), _position_frame(4, 2500)])

    packet = await _first_packet(source)

    assert packet.values == {"gripper.position": 75.0, "wrist_roll.position": 50.0}
    assert packet.units == {"gripper.position": "%", "wrist_roll.position": "%"}


async def test_resolution_follows_the_bus_map_model() -> None:
    part = str(uuid.uuid4())
    config = _dxl_config(
        bus_map=[
            {"protocol": "dynamixel-2", "address": "2", "part_entity_id": part, "model": "XL320"}
        ],
        parts={
            part: {
                "calibration": {"mode": "degrees"},
                "telemetry": [{"name": "elbow.position", "unit": "deg"}],
            }
        },
    )
    source, _ = _open(config, [_position_frame(2, 768)])

    packet = await _first_packet(source)

    assert packet.values == {"elbow.position": pytest.approx(90.0)}  # (768 - 512) / 1024 rev


async def test_a_range_mode_without_a_range_falls_back_to_honest_ticks() -> None:
    part = str(uuid.uuid4())
    config = _dxl_config(
        bus_map=[{"protocol": "dynamixel-2", "address": "5", "part_entity_id": part}],
        parts={part: {"calibration": {"mode": "range_0_100"}}},
    )
    source, _ = _open(config, [_position_frame(5, 2500)])

    packet = await _first_packet(source)

    assert packet.values == {"addr_5.position": 2500.0}
    assert packet.units == {"addr_5.position": "ticks"}


async def test_junk_on_the_bus_costs_one_sample_not_the_stream() -> None:
    config = _dxl_config(bus_map=[{"protocol": "dynamixel-2", "address": "1"}])
    junk = RecordedFrame(at_s=0.0, payload=b"\xff\xff\xfd\x00\x01\x08\x00\x55" + b"\x00" * 7)
    source, channel = _open(config, [junk, _position_frame(1, 2048)])

    packet = await _first_packet(source)

    assert packet.values == {"addr_1.position": 2048.0}
    assert len(channel.sent) == 2  # the first sweep got junk back; the second answered


async def test_addresses_that_are_not_servo_ids_are_skipped() -> None:
    config = _dxl_config(
        bus_map=[
            {"protocol": "dynamixel-2", "address": "0x10"},
            {"protocol": "dynamixel-2", "address": "300"},
            {"protocol": "dynamixel-2", "address": "1"},
        ]
    )
    source, channel = _open(config, [_position_frame(1, 2048)])

    packet = await _first_packet(source)

    assert packet.values == {"addr_1.position": 2048.0}
    assert [f.payload for f in channel.sent] == [dxl_read_request(1, PRESENT_POSITION)]


def test_params_are_bounded_and_default_to_the_factory_baud() -> None:
    defaults = DynamixelParams()
    assert defaults.baud == 57600 and defaults.protocol_version == 2 and defaults.poll_hz <= 200
    registry = DriverRegistry()
    registry.register(DynamixelDriver)
    accepted = registry.validate_params(
        _dxl_config(bus_map=[], baud=1_000_000, protocol_version=2).protocol
    )
    assert isinstance(accepted, DynamixelParams) and accepted.baud == 1_000_000
    for bad in ({"poll_hz": 500}, {"baud": 9599}, {"baud": 4_000_001}, {"bogus": 1}):
        with pytest.raises(ValidationError):
            DynamixelParams.model_validate(bad)
    assert registry.catalog()[0]["driver_id"] == "dynamixel-2"
    assert registry.catalog()[0]["transports"] == ["usb_serial"]
