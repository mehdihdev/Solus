"""Raw numeric lines driver: floats per line; channel names come from the robot's config
(bus_map column index → part → its first telemetry channel) or fall back to `ch<i>.value`."""

import math
import uuid
from pathlib import Path

import pytest
from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.replay import RecordedFrame, ReplayChannel, load_recording
from livebench.plugins import load_all
from livebench.plugins.raw.raw_driver import RawLinesDriver, RawLinesParams
from livebench.telemetry.stream_live import PacketSource
from pydantic import ValidationError
from solus_api.graph.packet import MAX_SIGNALS_PER_PACKET, TelemetryPacket
from solus_api.hardware.config import (
    HardwareConfig,
    ProtocolBinding,
    TransportBinding,
    TransportKind,
)

FIXTURES = Path(__file__).with_name("fixtures")
BINDING = "ARDUINO-NANO-7F31"
REF = f"usb:{BINDING}"
NAMES = [
    "left_wheel.velocity",
    "right_wheel.velocity",
    "heading.angle",
    "battery.voltage",
    "gyro.rate",
    "gripper.position",
]


def _identity() -> TransportBinding:
    return TransportBinding(kind=TransportKind.USB_SERIAL, binding=BINDING)


def _config(*, named: bool, **params: object) -> HardwareConfig:
    document: dict[str, object] = {
        "robot_entity_id": uuid.uuid4(),
        "identity": _identity(),
        "protocol": ProtocolBinding(driver_id="raw-lines", params=params),  # type: ignore[arg-type]
        "provenance": {
            "identity": {"by": "detected"},
            "protocol": {"by": "user"},
            "bus_map": {"by": "user"},
            "parts": {"by": "user"},
        },
    }
    if named:
        ids = [str(uuid.uuid4()) for _ in NAMES]
        document["bus_map"] = [
            {"protocol": "raw-lines", "address": str(i), "part_entity_id": ids[i]}
            for i in range(len(NAMES))
        ] + [{"protocol": "raw-lines", "address": "x", "part_entity_id": str(uuid.uuid4())}]
        parts: dict[str, object] = {
            ids[0]: {"telemetry": [{"name": NAMES[0], "unit": "m/s"}]},
            ids[1]: {"telemetry": [{"name": NAMES[1], "unit": "m/s"}]},
            # unit from the calibration mode when the channel names none
            ids[2]: {"telemetry": [{"name": NAMES[2]}], "calibration": {"mode": "degrees"}},
            ids[3]: {"telemetry": [{"name": NAMES[3], "unit": "V"}]},
            ids[4]: {"telemetry": [{"name": NAMES[4]}]},  # no unit at all
            ids[5]: {"telemetry": [{"name": NAMES[5]}], "calibration": {"mode": "range_0_100"}},
        }
        document["parts"] = parts
    return HardwareConfig.model_validate(document)


def _replay(*lines: bytes) -> ReplayChannel:
    frames = [RecordedFrame(at_s=i * 0.01, payload=line) for i, line in enumerate(lines)]
    return ReplayChannel(TransportKind.USB_SERIAL, _identity(), frames)


def _fixture_channel() -> ReplayChannel:
    recording = load_recording(FIXTURES / "serial_arduino_rover.json")
    return ReplayChannel(TransportKind.USB_SERIAL, recording.identity, recording.frames)


async def _take(source: PacketSource, count: int) -> list[TelemetryPacket]:
    out: list[TelemetryPacket] = []
    async for packet in source:
        out.append(packet)
        if len(out) == count:
            break
    await source.aclose()
    return out


def _open(channel: ReplayChannel, config: HardwareConfig) -> PacketSource:
    registry = DriverRegistry()
    registry.register(RawLinesDriver)
    return registry.open_source(config, channel)


def test_register_adds_the_driver_and_params_are_bounded() -> None:
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    load_all(registries, modules=("livebench.plugins.raw",))
    driver = registries.drivers.get("raw-lines")
    assert driver.display_name == "Raw numeric lines (user-named channels)"
    assert RawLinesParams().separator == "auto"
    assert RawLinesParams.model_validate({"separator": "\t", "baud": 9600}).separator == "\t"
    with pytest.raises(ValidationError):
        RawLinesParams.model_validate({"separator": ";"})
    with pytest.raises(ValidationError):
        RawLinesParams.model_validate({"columns": 6})


async def test_named_parts_give_names_and_units_from_the_config() -> None:
    packets = await _take(_open(_fixture_channel(), _config(named=True, baud=115200)), 100)
    assert {p.device_id for p in packets} == {REF}
    assert list(packets[0].values) == NAMES
    assert packets[0].units == {
        NAMES[0]: "m/s",
        NAMES[1]: "m/s",
        NAMES[2]: "deg",
        NAMES[3]: "V",
        NAMES[5]: "%",
    }
    assert packets[0].values[NAMES[3]] == pytest.approx(12.40)
    assert packets[99].values[NAMES[3]] == pytest.approx(12.20)


async def test_unnamed_columns_fall_back_to_ch_i_value_with_no_units() -> None:
    packets = await _take(_open(_fixture_channel(), _config(named=False)), 3)
    assert list(packets[0].values) == [f"ch{i}.value" for i in range(6)]
    assert packets[0].units == {} and packets[0].seq is None
    assert packets[0].timestamp.tzinfo is not None


@pytest.mark.parametrize(
    ("separator", "line"),
    [
        ("auto", b"1, 2,3\t4 5\n"),
        ("auto", b"1,2,3,4,5,\n"),
        (",", b"1,2,3,4,5\n"),
        (" ", b"1  2 3 4 5\n"),
        ("\t", b"1\t2\t3\t4\t5\n"),
    ],
)
async def test_separators(separator: str, line: bytes) -> None:
    config = _config(named=False, separator=separator)
    (packet,) = await _take(_open(_replay(line), config), 1)
    assert list(packet.values.values()) == [1.0, 2.0, 3.0, 4.0, 5.0]


async def test_non_numeric_non_finite_and_binary_lines_are_skipped() -> None:
    channel = _replay(
        b"abc,1\n", b"nan,1\n", b"inf,1\n", b"\xff\xfe\n", b"1e999,1\n", b",\n", b"7,8\n"
    )
    (packet,) = await _take(_open(channel, _config(named=False)), 1)
    assert packet.values == {"ch0.value": 7.0, "ch1.value": 8.0}
    assert all(math.isfinite(v) for v in packet.values.values())


async def test_columns_are_bounded_to_the_packet_signal_cap() -> None:
    line = ",".join(str(i) for i in range(MAX_SIGNALS_PER_PACKET + 40)).encode() + b"\n"
    (packet,) = await _take(_open(_replay(line), _config(named=False)), 1)
    assert len(packet.values) == MAX_SIGNALS_PER_PACKET
    assert packet.values[f"ch{MAX_SIGNALS_PER_PACKET - 1}.value"] == MAX_SIGNALS_PER_PACKET - 1
