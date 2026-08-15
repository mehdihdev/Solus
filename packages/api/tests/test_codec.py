"""LB-06 telemetry packet codec — round-trip, forward-compatibility and throughput (SOLUSDEV-126).

The load-bearing property is FORWARD COMPATIBILITY: a decoder built against schema_version N must
read a packet produced at N+1 without breaking. Adding a field is what evolution looks like, and
five consumers (LB-01 sim, LB-02 robot, LNK-06 plumbing, CON-03 Foxglove, LB-05 UI) upgrade at
different times, so `test_old_decoder_reads_a_newer_packet` is the test this format exists for.

Decoding is a trust boundary (CLAUDE.md §7): the bytes come off a wire from a device nobody
controls, so oversize/malformed/hostile input must raise `PacketDecodeError`, never propagate a
raw codec exception and never exhaust memory.
"""

import json
import math
import time
from datetime import UTC, datetime, timedelta, timezone

import msgpack
import pytest
from solus_api.graph.codec import (
    MAX_PACKET_BYTES,
    PacketDecodeError,
    decode,
    decode_json,
    encode,
    encode_json,
    from_wire,
    to_wire,
)
from solus_api.graph.packet import MAX_SAFE_INT, SCHEMA_VERSION, TelemetryPacket

# A deliberately awkward instant: microsecond resolution must survive the round trip exactly.
_T0 = datetime(2026, 7, 5, 12, 0, 0, 123456, tzinfo=UTC)

_FULL = TelemetryPacket(
    device_id="/robot/imu0",
    timestamp=_T0,
    seq=42,
    values={"accel_x": 0.125, "temp_c": 31.5, "rpm": 1200.0},
    units={"accel_x": "m/s^2", "temp_c": "degC", "rpm": "rev/min"},
)


# ------------------------------------------------------------------ round trips


def test_msgpack_round_trip_preserves_every_field() -> None:
    assert decode(encode(_FULL)) == _FULL


def test_json_round_trip_preserves_every_field() -> None:
    assert decode_json(encode_json(_FULL)) == _FULL


def test_round_trip_preserves_microsecond_resolution() -> None:
    """Epoch-microsecond integers, not float seconds — a float would silently drift."""
    assert decode(encode(_FULL)).timestamp == _T0
    assert decode(encode(_FULL)).timestamp.microsecond == 123456


def test_non_utc_producers_round_trip_to_the_same_instant() -> None:
    """The wire carries an instant, not a local time. A non-UTC producer decodes to UTC — the
    same moment, a different tzinfo — so consumers must compare INSTANTS."""
    tokyo = datetime(2026, 7, 5, 21, 0, 0, 123456, tzinfo=timezone(timedelta(hours=9)))
    decoded = decode(encode(TelemetryPacket(device_id="imu0", timestamp=tokyo, values={"x": 1.0})))
    assert decoded.timestamp == tokyo  # same instant
    assert decoded.timestamp.tzinfo is UTC  # normalized


def test_dst_ambiguous_timestamp_keeps_its_instant() -> None:
    """PEP 495: a local wall-clock stamp inside a DST fold compares unequal to the same instant
    expressed in another zone, even though nothing was lost. Pin the guarantee we actually make —
    the INSTANT survives — so this narrow case is a documented property, not a latent surprise."""
    ambiguous = datetime(2026, 11, 1, 1, 30, 0, tzinfo=timezone(timedelta(hours=-4)), fold=1)
    packet = TelemetryPacket(device_id="imu0", timestamp=ambiguous, values={"x": 1.0})
    decoded = decode(encode(packet))
    assert decoded.timestamp.timestamp() == ambiguous.timestamp()


def test_round_trip_preserves_an_unsequenced_packet() -> None:
    pkt = TelemetryPacket(device_id="imu0", timestamp=_T0, values={"x": 1.0})
    decoded = decode(encode(pkt))
    assert decoded.seq is None
    assert decoded.units == {}


def test_both_encodings_share_one_wire_shape() -> None:
    """One mapping, two transports — the JSON debug form is the msgpack shape, JSON-encoded.
    If these ever diverge the TS decoder would need two implementations."""
    assert json.loads(encode_json(_FULL)) == msgpack.unpackb(encode(_FULL), strict_map_key=True)


def test_msgpack_is_more_compact_than_json() -> None:
    assert len(encode(_FULL)) < len(encode_json(_FULL).encode())


def test_msgpack_size_is_constant_regardless_of_value_precision() -> None:
    """The real reason this format is binary. A float64 is 9 bytes in msgpack whatever it holds,
    while its JSON text grows with precision — so JSON's packet size swings ~2x with the DATA,
    and msgpack's does not. Bounded worst-case size is what lets a streaming reader size buffers
    and apply backpressure. (On artificially round values like 1.5, JSON's text can be shorter;
    real sensor readings are not round, and the measured numbers are in the completion report.)"""
    round_numbers = TelemetryPacket(
        device_id="/robot/bus", timestamp=_T0, values={f"s{i}": i * 1.5 for i in range(64)}
    )
    full_precision = TelemetryPacket(
        device_id="/robot/bus",
        timestamp=_T0,
        values={f"s{i}": i * 1.5 + 0.123456789012345 for i in range(64)},
    )

    # msgpack: identical size for both. JSON: balloons on the very same data.
    assert len(encode(round_numbers)) == len(encode(full_precision))
    assert len(encode_json(full_precision).encode()) > len(encode_json(round_numbers).encode())

    # And on realistic (non-round) readings msgpack is comfortably the smaller of the two.
    assert len(encode(full_precision)) < len(encode_json(full_precision).encode()) * 0.6


# ------------------------------------------------- forward compatibility (the point)


def test_old_decoder_reads_a_newer_packet() -> None:
    """THE versioning-safety proof. A future producer bumps schema_version and adds fields; this
    decoder — built against SCHEMA_VERSION — must still read it, ignoring what it doesn't know."""
    future = to_wire(_FULL) | {
        "schema_version": SCHEMA_VERSION + 1,
        "quality": "degraded",  # a scalar field added later
        "calibration": {"offset": 0.01, "gain": 1.02},  # a nested field added later
    }
    decoded = decode(msgpack.packb(future))

    assert decoded.device_id == _FULL.device_id
    assert decoded.timestamp == _FULL.timestamp
    assert decoded.seq == _FULL.seq
    assert decoded.values == _FULL.values
    assert decoded.units == _FULL.units
    assert decoded.schema_version == SCHEMA_VERSION + 1  # reported, not rewritten
    assert not hasattr(decoded, "quality")


def test_newer_json_packet_also_decodes() -> None:
    future = to_wire(_FULL) | {"schema_version": SCHEMA_VERSION + 1, "quality": "degraded"}
    assert decode_json(json.dumps(future)).values == _FULL.values


def test_unknown_fields_are_dropped_not_smuggled_in() -> None:
    """`TelemetryPacket` keeps extra='forbid', so tolerance lives in the DECODER, not the model:
    code still cannot construct a packet with a stray field."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        TelemetryPacket.model_validate({**_FULL.model_dump(), "quality": "degraded"})
    assert from_wire(to_wire(_FULL) | {"quality": "degraded"}) == _FULL


# ----------------------------------------------------- untrusted input (CLAUDE.md §7)


def test_oversized_payload_is_rejected_before_unpacking() -> None:
    with pytest.raises(PacketDecodeError):
        decode(b"\x00" * (MAX_PACKET_BYTES + 1))


def test_truncated_bytes_raise_packet_decode_error() -> None:
    """Never leak a raw msgpack exception — ingestion catches exactly one type."""
    with pytest.raises(PacketDecodeError):
        decode(encode(_FULL)[:12])


def test_non_map_payload_is_rejected() -> None:
    with pytest.raises(PacketDecodeError):
        decode(msgpack.packb([1, 2, 3]))


def test_empty_payload_is_rejected() -> None:
    with pytest.raises(PacketDecodeError):
        decode(b"")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_wire_value_is_rejected(bad: float) -> None:
    """msgpack can carry NaN/Inf; the packet boundary is what refuses them."""
    hostile = to_wire(_FULL) | {"values": {"x": bad}, "units": {}}
    with pytest.raises(PacketDecodeError):
        decode(msgpack.packb(hostile))


def test_missing_timestamp_is_rejected() -> None:
    wire = to_wire(_FULL)
    del wire["ts_us"]
    with pytest.raises(PacketDecodeError):
        decode(msgpack.packb(wire))


def test_non_integer_timestamp_is_rejected() -> None:
    with pytest.raises(PacketDecodeError):
        decode(msgpack.packb(to_wire(_FULL) | {"ts_us": "yesterday"}))


def test_oversized_signal_map_is_rejected() -> None:
    hostile = to_wire(_FULL) | {"values": {f"s{i}": 1.0 for i in range(5000)}, "units": {}}
    with pytest.raises(PacketDecodeError):
        decode(msgpack.packb(hostile))


def test_malformed_json_raises_packet_decode_error() -> None:
    with pytest.raises(PacketDecodeError):
        decode_json("{not json")


def test_deeply_nested_json_raises_packet_decode_error() -> None:
    """Regression: `json` raises RecursionError on deep nesting, which is not a JSONDecodeError.
    A 5 KB payload — far under the size cap — used to escape and kill the reader task."""
    hostile = (
        '{"device_id":"d","ts_us":1,"values":{"x":1},"junk":' + "[" * 20_000 + "]" * 20_000 + "}"
    )
    with pytest.raises(PacketDecodeError):
        decode_json(hostile)


def test_absurdly_long_integer_literal_raises_packet_decode_error() -> None:
    """Regression, and the subtle one: CPython's int_max_str_digits guard raises a BARE ValueError
    from inside json's scanner. `PacketDecodeError` SUBCLASSES ValueError, so that bare error
    would sail straight through a caller's `except PacketDecodeError`."""
    with pytest.raises(PacketDecodeError):
        decode_json('{"device_id":"d","ts_us":' + "1" * 5_000 + ',"values":{"x":1}}')


def test_json_size_cap_counts_bytes_not_characters() -> None:
    """A str's len() counts code points; multi-byte characters would slip ~3x past a byte cap."""
    padding = "あ" * (MAX_PACKET_BYTES - 100)  # ~3 bytes each: well over the cap, under it in chars
    with pytest.raises(PacketDecodeError):
        decode_json('{"device_id":"' + padding + '","ts_us":1,"values":{"x":1}}')


@pytest.mark.parametrize("field", ["seq", "ts_us"])
def test_integers_beyond_the_javascript_safe_range_are_rejected(field: str) -> None:
    """The format's integer domain is the INTERSECTION of its runtimes. A value Python accepts but
    the TypeScript decoder silently rounds is a packet that cannot survive the trip to the UI."""
    with pytest.raises(PacketDecodeError):
        decode(msgpack.packb(to_wire(_FULL) | {field: MAX_SAFE_INT + 1}))


def test_decoded_timestamp_is_timezone_aware() -> None:
    assert decode(encode(_FULL)).timestamp.tzinfo is not None


# --------------------------------------------------------------------- throughput


def test_codec_throughput_is_adequate_for_a_live_stream() -> None:
    """A CI-stable ratchet, not a micro-benchmark (house convention, cf. test_type_estimator).
    A 1 kHz robot streaming 3 signals is 1000 packets/s; the codec must not be the bottleneck.
    Measured numbers are reported in the completion report."""
    n = 5_000
    blob = encode(_FULL)

    start = time.perf_counter()
    for _ in range(n):
        encode(_FULL)
    encode_s = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(n):
        decode(blob)
    decode_s = time.perf_counter() - start

    assert n / encode_s > 10_000, f"encode {n / encode_s:.0f}/s"
    assert n / decode_s > 10_000, f"decode {n / decode_s:.0f}/s"
