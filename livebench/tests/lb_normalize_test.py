"""CON-03: normalization of Foxglove/MCAP JSON message payloads into LB-06 packets."""

import json
from datetime import UTC, datetime

import pytest
from livebench.telemetry.normalize import packet_from_json_payload, timestamp_from_ns
from solus_api.graph.codec import MAX_PACKET_BYTES, encode_json
from solus_api.graph.packet import MAX_SIGNALS_PER_PACKET, TelemetryPacket

NS = 1_000_000_000  # ns per second
T0_NS = 1_767_225_600 * NS  # 2026-01-01T00:00:00Z


def test_timestamp_from_ns_is_exact_to_the_microsecond() -> None:
    moment = timestamp_from_ns(1_700_000_000_123_456_789)
    assert moment == datetime(2023, 11, 14, 22, 13, 20, 123_456, tzinfo=UTC)


def test_flattens_nested_numeric_leaves_with_dot_paths() -> None:
    payload = json.dumps(
        {"position": {"x": 1.5, "y": -2.0}, "velocity": 3, "name": "arm", "frame": None}
    ).encode()

    packet = packet_from_json_payload("/joint_states", T0_NS, payload)

    assert packet is not None
    assert packet.device_id == "/joint_states"
    assert packet.values == {"position.x": 1.5, "position.y": -2.0, "velocity": 3.0}
    assert packet.timestamp == timestamp_from_ns(T0_NS)


def test_booleans_are_not_measurements() -> None:
    packet = packet_from_json_payload("/t", T0_NS, b'{"ok": true, "v": 1.0}')
    assert packet is not None
    assert packet.values == {"v": 1.0}


def test_payload_with_no_numeric_content_returns_none() -> None:
    assert packet_from_json_payload("/t", T0_NS, b'{"name": "arm", "ok": true}') is None


def test_malformed_json_returns_none_never_raises() -> None:
    assert packet_from_json_payload("/t", T0_NS, b"{not json") is None


def test_non_object_json_returns_none() -> None:
    assert packet_from_json_payload("/t", T0_NS, b"[1, 2, 3]") is None


def test_oversized_payload_returns_none() -> None:
    blob = json.dumps({"v": "x" * MAX_PACKET_BYTES}).encode()
    assert packet_from_json_payload("/t", T0_NS, blob) is None


def test_empty_topic_returns_none() -> None:
    assert packet_from_json_payload("", T0_NS, b'{"v": 1.0}') is None


def test_non_finite_values_are_dropped() -> None:
    packet = packet_from_json_payload("/t", T0_NS, b'{"a": 1.0, "b": NaN, "c": Infinity}')
    assert packet is not None
    assert packet.values == {"a": 1.0}


def test_signal_count_is_bounded_deterministically() -> None:
    fields = {f"s{i:04d}": float(i) for i in range(MAX_SIGNALS_PER_PACKET + 40)}
    packet = packet_from_json_payload("/t", T0_NS, json.dumps(fields).encode())

    assert packet is not None
    assert len(packet.values) == MAX_SIGNALS_PER_PACKET
    # Sorted-key truncation: the KEPT names are the lexicographically first N, every run.
    assert sorted(packet.values) == sorted(fields)[:MAX_SIGNALS_PER_PACKET]


def test_overlong_signal_names_are_dropped_not_fatal() -> None:
    payload = json.dumps({"x" * 300: 1.0, "ok": 2.0}).encode()
    packet = packet_from_json_payload("/t", T0_NS, payload)
    assert packet is not None
    assert packet.values == {"ok": 2.0}


def test_lb06_wire_payload_passes_through_losslessly() -> None:
    original = TelemetryPacket(
        device_id="motor-3",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        values={"rpm": 1200.5},
        seq=42,
        units={"rpm": "1/min"},
    )
    packet = packet_from_json_payload("motor-3", T0_NS, encode_json(original).encode())

    # A native LB-06 producer keeps its own sequencing and units — on its OWN topic.
    assert packet == original


def test_invalid_lb06_wire_payload_is_rejected_not_flattened() -> None:
    # `ts_us` marks the payload as LB-06 wire; a broken one must NOT fall back to
    # generic flattening (which would turn ts_us itself into a fake signal).
    payload = json.dumps({"ts_us": 10, "device_id": "", "values": {"v": 1.0}}).encode()
    assert packet_from_json_payload("/t", T0_NS, payload) is None


def test_empty_signal_name_is_dropped_never_crashes() -> None:
    # Review finding (CRITICAL): {"": 1.5} passed the length guard and blew up
    # TelemetryPacket validation, killing the stream. It must drop the leaf only.
    packet = packet_from_json_payload("/t", T0_NS, b'{"": 1.5, "ok": 2.0}')
    assert packet is not None
    assert packet.values == {"ok": 2.0}


def test_payload_of_only_invalid_names_returns_none() -> None:
    assert packet_from_json_payload("/t", T0_NS, b'{"": 1.5}') is None


def test_oversized_integer_leaf_is_dropped_never_raises() -> None:
    # Security C1: a 400-digit int parses as JSON, then float() raises OverflowError.
    payload = ("{" + '"a": 1' + "0" * 400 + ', "ok": 2.0}').encode()
    packet = packet_from_json_payload("/t", T0_NS, payload)
    assert packet is not None
    assert packet.values == {"ok": 2.0}


@pytest.mark.parametrize(
    "payload",
    [
        b'{"": 1.0}',
        ("{" + '"a": 1' + "0" * 400 + "}").encode(),
        b"[" * 20_000,  # deep nesting → RecursionError inside json
        b'\xff\xfe{"v": 1.0}',  # invalid UTF-8
        b'{"ts_us": "garbage", "device_id": 5, "values": []}',
        json.dumps({f"n{i}": i for i in range(400)}).encode(),
    ],
)
def test_hostile_payload_corpus_never_raises(payload: bytes) -> None:
    result = packet_from_json_payload("/t", T0_NS, payload)
    assert result is None or result.values


def test_lb06_payload_cannot_impersonate_another_topic() -> None:
    # Security H2: device_id is graph identity; a payload publishing on topic A
    # must not assert itself as entity B.
    original = TelemetryPacket(
        device_id="bms-main", timestamp=datetime(2026, 1, 1, tzinfo=UTC), values={"volts": 48.0}
    )
    assert (
        packet_from_json_payload("/attacker_topic", T0_NS, encode_json(original).encode()) is None
    )


def test_trusted_identity_accepts_the_payloads_own_device_id() -> None:
    # Direct links (serial, robot WS): one wire, one claimant — the firmware's own
    # device_id is the identity claim. Bridged transports (Foxglove/MCAP) never set this.
    original = TelemetryPacket(
        device_id="motor-7", timestamp=datetime(2026, 1, 1, tzinfo=UTC), values={"rpm": 10.0}
    )
    packet = packet_from_json_payload(
        "serial:/dev/ttyACM0", T0_NS, encode_json(original).encode(), trusted_identity=True
    )
    assert packet == original
