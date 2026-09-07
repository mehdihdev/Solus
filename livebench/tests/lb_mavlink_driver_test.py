"""MAVLink driver: a PacketSource over any channel that carries v2 frames — attitude in rad,
actuator outputs in us, heartbeat status — keyed by the channel identity, named by the config's
bus map, and never killed by bad bytes or another system's traffic."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from livebench.hardware.channel import Frame, TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.replay import ReplayChannel, load_recording
from livebench.plugins.mavlink import register
from livebench.plugins.mavlink.mavlink_codec import encode_mavlink
from livebench.plugins.mavlink.mavlink_definitions import ATTITUDE, HEARTBEAT, SERVO_OUTPUT_RAW
from livebench.plugins.mavlink.mavlink_driver import MavlinkDriver, MavlinkParams, MavlinkSource
from pydantic import ValidationError
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportBinding, TransportKind

FIXTURE = Path(__file__).parent / "fixtures" / "mavlink_px4_quadrotor.json"
AUTOPILOT = "019a0000-0000-7000-8000-00000000c101"
FRONT_LEFT = "019a0000-0000-7000-8000-00000000c102"
IDENTITY = TransportBinding(kind=TransportKind.WIFI, binding="aa:bb:cc:dd:ee:ff")
DEVICE = "ip:aa:bb:cc:dd:ee:ff"
HEARTBEAT_FIELDS = {"type": 2, "autopilot": 12, "system_status": 4, "mavlink_version": 3}


def _mav_config(
    bus_map: list[dict[str, Any]], parts: dict[str, Any], **params: Any
) -> HardwareConfig:
    return HardwareConfig.model_validate(
        {
            "robot_entity_id": str(uuid.uuid4()),
            "identity": IDENTITY.model_dump(mode="json"),
            "protocol": {"driver_id": "mavlink", "params": params},
            "bus_map": bus_map,
            "parts": parts,
            "provenance": {
                "identity": {"by": "detected"},
                "protocol": {"by": "user"},
                "bus_map": {"by": "detected"},
                "parts": {"by": "user"},
            },
        }
    )


def _named_config(mode: str | None = None) -> HardwareConfig:
    calibration = {"mode": mode} if mode else None
    return _mav_config(
        [
            {"protocol": "mavlink", "address": "1:1", "part_entity_id": AUTOPILOT, "model": "PX4"},
            {"protocol": "mavlink", "address": "servo:1", "part_entity_id": FRONT_LEFT},
            {"protocol": "mavlink", "address": "servo:2", "part_entity_id": str(uuid.uuid4())},
        ],
        {
            AUTOPILOT: {"calibration": calibration, "telemetry": [{"name": "attitude.roll"}]},
            FRONT_LEFT: {"telemetry": [{"name": "front_left.output", "unit": "us"}]},
        },
    )


def _replay() -> ReplayChannel:
    recording = load_recording(FIXTURE)
    return ReplayChannel(recording.identity.kind, IDENTITY, recording.frames)


class _FrameChan:
    """A channel that hands out the given frames then falls silent."""

    kind = TransportKind.USB_SERIAL

    def __init__(self, frames: list[bytes], params: dict[str, Any] | None = None) -> None:
        self.identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42")
        self.frames = list(frames)
        self.params = params or {}
        self.closed = False

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return Frame(payload=self.frames.pop(0)) if self.frames else None

    def flush_input(self) -> None: ...

    def close(self) -> None:
        self.closed = True


async def _take(source: MavlinkSource, count: int) -> list[TelemetryPacket]:
    packets: list[TelemetryPacket] = []
    async for packet in source:
        packets.append(packet)
        if len(packets) >= count:
            break
    await source.aclose()
    return packets


async def test_fixture_yields_attitude_in_rad_and_motor_outputs_in_us_keyed_by_identity() -> None:
    registry = DriverRegistry()
    registry.register(MavlinkDriver)
    source = registry.open_source(_named_config(), _replay())
    assert isinstance(source, MavlinkSource)
    heartbeat, attitude, servo, *_ = await _take(source, 6)
    assert {p.device_id for p in (heartbeat, attitude, servo)} == {DEVICE}
    assert heartbeat.values == {"attitude.system_status": 4.0} and heartbeat.units == {}
    assert attitude.values["attitude.roll"] == 0.0 and attitude.values["attitude.yaw"] == 1.5
    assert attitude.units["attitude.roll"] == "rad"
    assert attitude.units["attitude.rollspeed"] == "rad/s" and attitude.seq is None
    assert servo.values == {
        "front_left.output": 1100.0,  # servo:1 is a named part
        "motor_2.output": 1400.0,  # servo:2 maps to a part without telemetry → the default
        "motor_3.output": 1600.0,
        "motor_4.output": 1900.0,
    }
    assert set(servo.units.values()) == {"us"}
    assert attitude.timestamp.tzinfo is UTC or attitude.timestamp.utcoffset() is not None
    assert (datetime.now(UTC) - attitude.timestamp).total_seconds() < 5


async def test_unmapped_addresses_use_the_natural_prefixes() -> None:
    source = MavlinkDriver().open(_replay(), MavlinkParams(), _mav_config([], {}))
    heartbeat, attitude, servo = await _take(source, 3)
    assert heartbeat.values == {"heartbeat.system_status": 4.0}
    assert set(attitude.values) == {
        f"attitude.{q}" for q in ("roll", "pitch", "yaw", "rollspeed", "pitchspeed", "yawspeed")
    }
    assert list(servo.values) == [f"motor_{n}.output" for n in (1, 2, 3, 4)]


async def test_a_degrees_calibration_mode_converts_angles_and_relabels_units() -> None:
    source = MavlinkDriver().open(_replay(), MavlinkParams(), _named_config(mode="degrees"))
    second_attitude = (await _take(source, 4))[3]  # heartbeat, attitude, servo, attitude
    assert second_attitude.values["attitude.roll"] == pytest.approx(5.7296, abs=1e-3)  # 0.1 rad
    assert second_attitude.units["attitude.roll"] == "deg"
    assert second_attitude.units["attitude.rollspeed"] == "deg/s"


async def test_other_system_ids_junk_and_non_finite_values_cost_samples_not_the_stream() -> None:
    other = encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=0, system_id=2)
    nan = encode_mavlink(ATTITUDE, {"roll": float("nan"), "yaw": 1.0}, seq=1, system_id=1)
    good = encode_mavlink(SERVO_OUTPUT_RAW, {"servo3_raw": 1500}, seq=2, system_id=1)
    channel = _FrameChan([other, b"junk\x00", nan, good])
    params = MavlinkParams(system_id=1, heartbeat_timeout_s=0.2)
    source = MavlinkSource(channel, params, _mav_config([], {}))
    attitude, servo = await _take(source, 2)
    assert "attitude.roll" not in attitude.values and attitude.values["attitude.yaw"] == 1.0
    assert servo.values == {"motor_3.output": 1500.0}
    assert channel.closed


async def test_the_stream_ends_when_the_heartbeat_times_out() -> None:
    now = [100.0]
    channel = _FrameChan([encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=0, system_id=1)])
    source = MavlinkSource(
        channel, MavlinkParams(heartbeat_timeout_s=0.5), _mav_config([], {}), clock=lambda: now[0]
    )
    packets: list[TelemetryPacket] = []
    async for packet in source:
        packets.append(packet)
        now[0] += 1.0  # silence past the timeout after the one heartbeat
    assert len(packets) == 1


def test_params_are_bounded_and_carry_the_transport_keys_of_the_same_config_bag() -> None:
    assert MavlinkParams().model_dump(exclude_none=True) == {
        "system_id": 1,
        "component_id": 1,
        "protocol_version": 2,
        "heartbeat_timeout_s": 3.0,
    }
    assert MavlinkParams(baud=57600, listen_port=14550).baud == 57600
    for bad in (
        {"system_id": 0},
        {"system_id": 256},
        {"protocol_version": 1},
        {"bogus": 1},
        {"heartbeat_timeout_s": 0},
        {"baud": 1},
    ):
        with pytest.raises(ValidationError):
            MavlinkParams.model_validate(bad)
    assert MavlinkDriver.transports == frozenset(
        {TransportKind.WIFI, TransportKind.ETHERNET, TransportKind.USB_SERIAL}
    )


def test_plugin_registers_driver_interrogator_and_the_udp_transport_once() -> None:
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    register(registries)
    assert registries.drivers.get("mavlink").display_name == "MAVLink autopilot link"
    assert registries.interrogators.get("mavlink-heartbeat").safety == "listen"
    assert {TransportKind.WIFI, TransportKind.ETHERNET} <= set(registries.transports.kinds())
    again = Registries(registries.transports, DriverRegistry(), InterrogatorRegistry())
    register(again)  # a transport already registered by the host is left alone


def test_vendor_strings_stay_under_the_plugin_tree() -> None:
    shared = Path(__file__).parents[1] / "src" / "livebench" / "hardware"
    vendors = re.compile(r"\b(px4|ardupilot|pixhawk|mavlink)\b", re.IGNORECASE)
    hits = [p.name for p in shared.rglob("*.py") if vendors.search(p.read_text())]
    assert hits == []
