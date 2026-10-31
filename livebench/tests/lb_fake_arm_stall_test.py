"""SOLUSDEV-321 P2-T4 — the fake arm's stall, recorded (`serial_fake_arm_stall.json`).

Vendor-free by construction: one synthetic six-servo arm streaming LB-06 lines at 20 Hz for a
minute from a fixed epoch. These tests read the recording the way the `lb06` driver does and pin
the scenario's timeline; what the rules make of it is `packages/api/tests/test_stall_replay.py`.
"""

import functools
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import fmean

import pytest
from livebench.hardware.replay import load_recording
from livebench.telemetry.normalize import packet_from_json_payload
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import TransportBinding, TransportKind

RECORDING = Path(__file__).with_name("fixtures") / "serial_fake_arm_stall.json"
DEVICE_REF = "usb:FAKE-ARM-0001"
EPOCH = datetime(2026, 10, 25, tzinfo=UTC)
HZ = 20
TICKS = 60 * HZ
CHANNELS = {
    "position": "deg",
    "commanded_position": "deg",
    "current": "A",
    "temperature": "degC",
    "voltage": "V",
}
RAIL_V = 7.4
WARN_A = 1.6  # a 2.0 A rating's warn bound: where a stall starts to count
RATING_A = 2.0
NOMINAL_A = 1.0


@functools.cache
def _packets() -> tuple[TelemetryPacket, ...]:
    """Every line of the recording as the `lb06` driver decodes it: the link is the identity."""
    frames = load_recording(RECORDING).frames
    decoded = [
        packet_from_json_payload(DEVICE_REF, 0, frame.payload, trusted_identity=True)
        for frame in frames
    ]
    return tuple(packet for packet in decoded if packet is not None)


def _readings(servo: int, quantity: str, start: float = 0.0, end: float = 60.0) -> list[float]:
    """`servo<n>.<quantity>` from `start` seconds into the recording up to, not including, `end`."""
    name = f"servo{servo}.{quantity}"
    return [
        packet.values[name]
        for packet in _packets()
        if start <= (packet.timestamp - EPOCH).total_seconds() < end
    ]


def _near(values: list[float], expected: float, within: float) -> bool:
    return bool(values) and all(abs(value - expected) <= within for value in values)


def test_the_recording_is_a_minute_of_lines_at_twenty_hertz_from_a_fixed_epoch() -> None:
    recording = load_recording(RECORDING)
    packets = _packets()

    assert recording.identity == TransportBinding(
        kind=TransportKind.USB_SERIAL, binding="FAKE-ARM-0001"
    )
    assert [frame.at_s for frame in recording.frames] == pytest.approx(
        [index / HZ for index in range(TICKS)]
    )
    assert [packet.timestamp for packet in packets] == [
        EPOCH + timedelta(microseconds=index * 50_000) for index in range(TICKS)
    ]
    assert [packet.seq for packet in packets] == list(range(TICKS))


def test_every_line_is_the_devices_own_so_the_relabel_guard_keeps_it() -> None:
    frames = load_recording(RECORDING).frames

    guarded = [
        packet_from_json_payload(DEVICE_REF, 0, frame.payload, trusted_identity=False)
        for frame in frames
    ]
    foreign = packet_from_json_payload("usb:OTHER", 0, frames[0].payload, trusted_identity=False)

    assert all(packet is not None and packet.device_id == DEVICE_REF for packet in guarded)
    assert foreign is None


def test_every_line_carries_the_five_channels_of_each_of_the_six_servos() -> None:
    expected = {
        f"servo{servo}.{quantity}": unit
        for servo in range(1, 7)
        for quantity, unit in CHANNELS.items()
    }

    assert all(dict(packet.units) == expected for packet in _packets())
    assert all(set(packet.values) == set(expected) for packet in _packets())


def test_servo_3_holds_its_position_against_a_commanded_move_while_its_current_climbs() -> None:
    held = _readings(3, "position", 5.0, 10.0)
    commanded = _readings(3, "commanded_position", 5.0, 10.0)

    assert _near(held, 30.0, 0.2)  # never within 40 deg of where it is asked to be
    assert _near(commanded, 75.0, 0.0)
    assert min(_readings(3, "current", 5.0, 10.0)) >= WARN_A  # from the first stalled sample on
    assert max(_readings(3, "current", 5.0, 6.0)) < RATING_A  # the stall is judged first
    assert min(_readings(3, "current", 6.0, 6.1)) > RATING_A  # then the current peaks over it
    assert max(_readings(3, "current", 6.0, 6.5)) >= 2.5


def test_servo_3_is_idle_before_the_stall_and_again_after_it() -> None:
    for start, end in ((0.0, 5.0), (10.0, 60.0)):
        assert _near(_readings(3, "commanded_position", start, end), 30.0, 0.0)
        assert _near(_readings(3, "position", start, end), 30.0, 0.2)
        assert max(_readings(3, "current", start, end)) < NOMINAL_A


def test_every_servos_voltage_dips_as_servo_3_current_peaks() -> None:
    peak = max(_readings(3, "current", 5.0, 10.0))
    at = next(
        index
        for index, packet in enumerate(_packets())
        if packet.values["servo3.current"] == peak and 5 * HZ <= index < 10 * HZ
    )

    assert at / HZ == pytest.approx(6.0, abs=0.5)
    for servo in range(1, 7):
        volts = _packets()[at].values[f"servo{servo}.voltage"]
        assert 6.0 <= volts <= RAIL_V * 0.97, servo  # a sag of at least 3 %, above the minimum
        assert _near(_readings(servo, "voltage", 0.0, 5.5), RAIL_V, 0.05), servo


def test_servo_3_temperature_ramps_toward_its_limit_from_ten_to_thirty_five_seconds() -> None:
    before = _readings(3, "temperature", 0.0, 10.0)
    ramp = _readings(3, "temperature", 10.0, 35.05)
    seconds = [fmean(ramp[at : at + HZ]) for at in range(0, 25 * HZ, HZ)]  # noise-proof

    assert max(before) - min(before) < 0.2
    assert seconds == sorted(seconds) and len(set(seconds)) == len(seconds)
    assert 60.0 <= ramp[-1] < 70.0
    assert max(_readings(3, "temperature")) < 70.0  # toward the limit, never past it
    assert _near(_readings(3, "temperature", 35.05, 60.0), ramp[-1], 0.5)
    assert all(max(_readings(servo, "temperature")) < 40.0 for servo in (1, 2, 4, 5, 6))


def test_servo_5_position_freezes_at_thirty_seconds_while_its_command_moves() -> None:
    frozen = _readings(5, "position", 30.0, 60.0)
    moving = _readings(5, "position", 0.0, 30.0)
    asked = _readings(5, "commanded_position", 0.0, 30.0)
    command = _readings(5, "commanded_position", 30.0, 31.0)

    assert len(frozen) == 30 * HZ and len(set(frozen)) == 1  # bit-identical to the end
    assert max(command) - min(command) > 1.0  # the command keeps moving
    assert all(a != b for a, b in zip(moving, moving[1:], strict=False))  # alive before
    assert max(asked) - min(asked) > 10.0
    assert max(abs(c - p) for c, p in zip(asked, moving, strict=True)) < 0.5


def test_servo_2_stalls_at_forty_seconds_the_way_servo_3_did_at_five() -> None:
    first, again = _readings(3, "current", 5.0, 10.0), _readings(2, "current", 40.0, 45.0)

    assert len(again) == len(first)
    assert all(abs(a - b) < 0.1 for a, b in zip(first, again, strict=True))
    assert _near(_readings(2, "position", 40.0, 45.0), 20.0, 0.2)
    assert _near(_readings(2, "commanded_position", 40.0, 45.0), 65.0, 0.0)
    assert _near(_readings(2, "commanded_position", 0.0, 40.0), 20.0, 0.0)
    assert max(_readings(2, "current", 0.0, 40.0)) < NOMINAL_A
    assert max(_readings(2, "current", 45.0, 60.0)) < NOMINAL_A


def test_the_rest_of_the_arm_never_leaves_idle() -> None:
    for servo in (1, 4, 6):
        rest = 10.0 * servo
        assert _near(_readings(servo, "commanded_position"), rest, 0.0), servo
        assert _near(_readings(servo, "position"), rest, 0.2), servo
        assert max(_readings(servo, "current")) < NOMINAL_A, servo
    assert max(_readings(5, "current")) < NOMINAL_A
