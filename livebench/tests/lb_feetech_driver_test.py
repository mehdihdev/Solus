"""Feetech STS driver (SOLUSDEV-248 R3): a polling PacketSource behind the ProtocolDriver seam.

Parameters come from the robot's config; register maps from the plugin's definitions; signal
names from the configured parts (`<part>.<quantity>`, units in the packet's `units` map).
"""

import asyncio
import uuid
from typing import Any

import pytest
from lb_feetech_codec_test import FeetechFakeChannel, _feetech_status
from livebench.hardware.driver import DriverRegistry
from livebench.plugins.feetech.feetech_driver import FeetechParams, FeetechStsDriver
from livebench.telemetry.stream_live import PacketSource
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    BusMapEntry,
    CalibrationMode,
    FieldProvenance,
    HardwareConfig,
    PartCalibration,
    PartConfig,
    ProtocolBinding,
    ProvenanceRecord,
    TelemetryChannel,
    TransportBinding,
    TransportKind,
)

DRIVER = "feetech-sts"
SHOULDER, GRIPPER = uuid.uuid4(), uuid.uuid4()
_USER = ProvenanceRecord(by=FieldProvenance.USER)
_FAST = {"poll_hz": 200}  # the bound; tests never sleep long


def _config(
    bus_map: list[BusMapEntry], parts: dict[str, PartConfig] | None = None, /, **params: Any
) -> HardwareConfig:
    return HardwareConfig(
        robot_entity_id=uuid.uuid4(),
        identity=TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42134331"),
        protocol=ProtocolBinding(driver_id=DRIVER, params={**_FAST, **params}),
        bus_map=bus_map,
        parts=parts or {},
        provenance={"identity": _USER, "protocol": _USER, "bus_map": _USER, "parts": _USER},
    )


def _arm(**params: Any) -> HardwareConfig:
    """Two named parts (degrees joint, percent gripper) and one unnamed address."""
    return _config(
        [
            BusMapEntry(protocol=DRIVER, address="1", part_entity_id=SHOULDER, model="STS3215"),
            BusMapEntry(protocol=DRIVER, address="2", part_entity_id=GRIPPER, model="STS3215"),
            BusMapEntry(protocol=DRIVER, address="3"),
        ],
        {
            str(SHOULDER): PartConfig(
                calibration=PartCalibration(mode=CalibrationMode.DEGREES),
                telemetry=[TelemetryChannel(name="shoulder_pan.position", unit="deg")],
            ),
            str(GRIPPER): PartConfig(
                calibration=PartCalibration(
                    mode=CalibrationMode.RANGE_0_100, values={"range_min": 2036, "range_max": 3486}
                ),
                telemetry=[TelemetryChannel(name="gripper.position", unit="%")],
            ),
        },
        **params,
    )


def _open(channel: FeetechFakeChannel, config: HardwareConfig) -> PacketSource:
    registry = DriverRegistry()
    registry.register(FeetechStsDriver)
    return registry.open_source(config, channel)


async def _packets(source: PacketSource, n: int) -> list[TelemetryPacket]:
    stream = source.__aiter__()
    packets = [await asyncio.wait_for(anext(stream), timeout=2) for _ in range(n)]
    await source.aclose()
    return packets


def test_catalog_and_params_are_bounded_and_default_from_definitions() -> None:
    registry = DriverRegistry()
    registry.register(FeetechStsDriver)
    (entry,) = registry.catalog()
    assert entry["driver_id"] == DRIVER and entry["transports"] == ["usb_serial"]
    defaults = FeetechParams()
    assert (defaults.baud, defaults.timeout_s, defaults.protocol_version) == (1_000_000, 0.05, 0)
    assert (defaults.poll_hz, defaults.ticks_per_rev, defaults.center) == (30, None, None)
    for bad in ({"bogus": 1}, {"poll_hz": 500}, {"baud": 9000}, {"protocol_version": 2}):
        with pytest.raises(ValueError):
            registry.validate_params(_config([], **bad).protocol)


async def test_polls_named_parts_in_their_calibrated_units() -> None:
    channel = FeetechFakeChannel(
        {1: 2047, 2: 2761, 3: 1000}, loads={1: 300, 2: 0x400 | 500}, temps={1: 41}
    )
    first, second = await _packets(_open(channel, _arm()), 2)

    assert first.device_id == "usb:5B42134331" and first.timestamp.tzinfo is not None
    assert first.values == {
        "shoulder_pan.position": 0.0,  # centre 2047, lerobot's homing convention
        "shoulder_pan.load": 30.0,
        "shoulder_pan.temperature": 41.0,
        "gripper.position": 50.0,  # 2761 within 2036..3486
        "gripper.load": -50.0,  # bit 10 is direction
        "addr_3.position": 1000.0,  # unnamed address: raw ticks
    }
    assert first.units == {
        "shoulder_pan.position": "deg",
        "shoulder_pan.load": "%",
        "shoulder_pan.temperature": "degC",
        "gripper.position": "%",
        "gripper.load": "%",
        "addr_3.position": "tick",
    }
    # Health rides every 10th sweep only; the next sweep is positions alone.
    assert set(second.values) == {"shoulder_pan.position", "gripper.position", "addr_3.position"}
    assert (first.seq, second.seq) == (0, 1)
    assert channel.closed


async def test_a_calibrated_range_owns_the_conversion_like_the_repo_does() -> None:
    """With range_min/range_max present the repo's convention wins: degrees from the range
    midpoint over resolution - 1, percent clamped into the range — never 138 %."""
    config = _config(
        [
            BusMapEntry(protocol=DRIVER, address="1", part_entity_id=SHOULDER, model="STS3215"),
            BusMapEntry(protocol=DRIVER, address="2", part_entity_id=GRIPPER, model="STS3215"),
        ],
        {
            str(SHOULDER): PartConfig(
                calibration=PartCalibration(
                    mode=CalibrationMode.DEGREES, values={"range_min": 719, "range_max": 3441}
                ),
                telemetry=[TelemetryChannel(name="shoulder_pan.position", unit="deg")],
            ),
            str(GRIPPER): PartConfig(
                calibration=PartCalibration(
                    mode=CalibrationMode.RANGE_0_100, values={"range_min": 2036, "range_max": 3486}
                ),
                telemetry=[TelemetryChannel(name="gripper.position", unit="%")],
            ),
        },
    )
    (packet,) = await _packets(_open(FeetechFakeChannel({1: 2080, 2: 4000}), config), 1)
    assert packet.values["shoulder_pan.position"] == 0.0  # the range midpoint is zero
    assert packet.values["gripper.position"] == 100.0  # clamped, as lerobot clamps
    (packet,) = await _packets(_open(FeetechFakeChannel({1: 2047, 2: 1000}), config), 1)
    assert packet.values["shoulder_pan.position"] == pytest.approx((2047 - 2080) * 360 / 4095)
    assert packet.values["gripper.position"] == 0.0


async def test_center_and_ticks_per_rev_come_from_params() -> None:
    (packet,) = await _packets(_open(FeetechFakeChannel({1: 2048}), _arm(center=2048)), 1)
    assert packet.values["shoulder_pan.position"] == 0.0
    (packet,) = await _packets(_open(FeetechFakeChannel({1: 1536}), _arm(ticks_per_rev=2048)), 1)
    assert packet.values["shoulder_pan.position"] == (1536 - 1023) * 360.0 / 2048


async def test_scs_protocol_reads_big_endian_words() -> None:
    channel = FeetechFakeChannel({1: 3071}, byteorder="big")
    (packet,) = await _packets(_open(channel, _arm(protocol_version=1)), 1)
    assert packet.values["shoulder_pan.position"] == 90.0


async def test_missing_servo_costs_its_sample_only() -> None:
    channel = FeetechFakeChannel({1: 3071})  # ids 2 and 3 never answer
    packets = await _packets(_open(channel, _arm()), 3)
    assert [p.values for p in packets] == [{"shoulder_pan.position": 90.0}] * 3


async def test_gripper_without_a_range_falls_back_to_ticks() -> None:
    config = _arm()
    parts = dict(config.parts)
    parts[str(GRIPPER)] = PartConfig(
        calibration=PartCalibration(mode=CalibrationMode.RANGE_0_100),
        telemetry=[TelemetryChannel(name="gripper.position")],
    )
    config = config.model_copy(update={"parts": parts})
    (packet,) = await _packets(_open(FeetechFakeChannel({2: 2761}), config), 1)
    assert packet.values == {"gripper.position": 2761.0} and packet.units == {
        "gripper.position": "tick"
    }


async def test_empty_bus_map_discovers_the_bus_once() -> None:
    channel = FeetechFakeChannel({1: 100, 2: 200})
    (packet,) = await _packets(_open(channel, _config([])), 1)
    assert packet.values == {"addr_1.position": 100.0, "addr_2.position": 200.0}
    assert packet.units == {"addr_1.position": "tick", "addr_2.position": "tick"}
    assert sum(frame[4] == 0x01 for frame in channel.sent) == 12  # one ping sweep, ids 1..12


def test_no_servos_anywhere_fails_open_honestly() -> None:
    with pytest.raises(LookupError, match="no Feetech servos answered"):
        _open(FeetechFakeChannel({}), _config([]))


def test_a_non_numeric_address_is_a_config_error() -> None:
    bad = _config([BusMapEntry(protocol=DRIVER, address="left")])
    with pytest.raises(ValueError, match="left"):
        _open(FeetechFakeChannel({1: 0}), bad)
    with pytest.raises(ValueError, match="300"):
        _open(FeetechFakeChannel({1: 0}), _config([BusMapEntry(protocol=DRIVER, address="300")]))


async def test_other_protocols_entries_are_ignored() -> None:
    config = _config(
        [BusMapEntry(protocol="other-bus", address="9"), BusMapEntry(protocol=DRIVER, address="1")]
    )
    (packet,) = await _packets(_open(FeetechFakeChannel({1: 5, 9: 6}), config), 1)
    assert packet.values == {"addr_1.position": 5.0}


async def test_link_loss_ends_iteration_for_reconnect() -> None:
    channel = FeetechFakeChannel({1: 2047})
    source = _open(channel, _arm())
    stream = source.__aiter__()
    await asyncio.wait_for(anext(stream), timeout=2)
    channel.fail = True
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=2)


async def test_stale_queued_reply_is_never_read_as_fresh() -> None:
    # A stale-but-valid frame (ticks 1024 = -90°) queued ahead of the request must not be
    # accepted as the answer to THIS request. Half-duplex: flush before asking.
    channel = FeetechFakeChannel({1: 2047}, preload=_feetech_status(1, bytes([0x00, 0x04])))
    (packet,) = await _packets(_open(channel, _arm()), 1)
    assert packet.values["shoulder_pan.position"] == 0.0


async def test_seq_continues_across_incarnations_of_one_device() -> None:
    # `seq` is the MONOTONIC per-device counter (packet.py contract); a reconnect re-opens the
    # source through the same driver instance and must not restart at 0.
    registry = DriverRegistry()
    registry.register(FeetechStsDriver)
    seqs = []
    for _ in range(2):
        (packet,) = await _packets(registry.open_source(_arm(), FeetechFakeChannel({1: 0})), 1)
        seqs.append(packet.seq)
    assert seqs == [0, 1]


async def test_polling_never_leaves_two_requests_outstanding() -> None:
    channel = FeetechFakeChannel({1: 0, 2: 0, 3: 0})
    await _packets(_open(channel, _arm()), 2)
    # Every request drained the input first (flush count ≥ send count): one in flight, ever.
    assert channel.flushes >= len(channel.sent)


def test_driver_declares_exact_channel_presentation_roles() -> None:
    registry = DriverRegistry()
    registry.register(FeetechStsDriver)
    roles = registry.channel_roles(_arm())
    assert roles == {
        f"{prefix}.{quantity}": role
        for prefix in ("shoulder_pan", "gripper", "addr_3")
        for quantity, role in (
            ("position", "primary"),
            ("load", "diagnostic"),
            ("temperature", "diagnostic"),
        )
    }


def test_channel_roles_follow_the_same_part_routes_as_packets() -> None:
    from livebench.hardware.channel import TransportRegistry
    from livebench.hardware.connection import open_robot_connection

    transports = TransportRegistry()
    transports.register(TransportKind.USB_SERIAL, lambda binding, params: FeetechFakeChannel({}))
    drivers = DriverRegistry()
    drivers.register(FeetechStsDriver)
    connection = open_robot_connection(
        _arm(), project_id=None, transports=transports, drivers=drivers
    )
    roles = connection.device_facts["channel_roles"]
    assert roles["usb:5B42134331/1"] == {
        "shoulder_pan.position": "primary",
        "shoulder_pan.load": "diagnostic",
        "shoulder_pan.temperature": "diagnostic",
    }
    assert "gripper.load" not in roles["usb:5B42134331/1"]
    assert roles["usb:5B42134331"]["addr_3.load"] == "diagnostic"
