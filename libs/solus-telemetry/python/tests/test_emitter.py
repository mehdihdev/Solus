"""solus-telemetry: the line format, seq, and the validation that keeps bad packets off the bus."""

import json
import time

import pytest
from solus_telemetry import (
    MAX_LINE_BYTES,
    MAX_SAFE_INT,
    MAX_SIGNAL_NAME_LEN,
    MAX_SIGNALS,
    MAX_UNIT_LEN,
    Emitter,
    format_line,
)

DEVICE = "usb:5B42134331"
GOLDEN = (
    '{"schema_version":1,"device_id":"usb:5B42134331","ts_us":1757145600000000,'
    '"values":{"base.velocity":0.1234,"imu.accel_z":9.8067},"seq":7,'
    '"units":{"base.velocity":"m/s"}}\n'
)


def test_golden_line_key_order_and_framing() -> None:
    line = format_line(
        DEVICE,
        {"base.velocity": 0.1234, "imu.accel_z": 9.8067},
        ts_us=1_757_145_600_000_000,
        seq=7,
        units={"base.velocity": "m/s"},
    )
    assert line == GOLDEN
    assert list(json.loads(line)) == [
        "schema_version",
        "device_id",
        "ts_us",
        "values",
        "seq",
        "units",
    ]


def test_seq_and_units_are_omitted_when_absent() -> None:
    line = format_line(DEVICE, {"a": 1.5}, ts_us=0)
    assert (
        line == '{"schema_version":1,"device_id":"usb:5B42134331","ts_us":0,"values":{"a":1.5}}\n'
    )
    assert format_line(DEVICE, {"a": 1.5}, ts_us=0, units={}) == line


def test_emitter_seq_is_monotonic_from_zero_and_stamps_the_clock() -> None:
    out: list[bytes] = []
    tx = Emitter(DEVICE, out.append, clock_us=lambda: 42)
    assert tx.send({"a": 1.0}) == 0
    assert tx.send({"a": 2.0}, {"a": "V"}) == 1
    assert [json.loads(b)["seq"] for b in out] == [0, 1]
    assert json.loads(out[0])["ts_us"] == 42
    assert json.loads(out[1])["units"] == {"a": "V"}
    assert all(b.endswith(b"\n") for b in out)


def test_emitter_default_clock_is_epoch_microseconds() -> None:
    out: list[bytes] = []
    before = time.time_ns() // 1000
    Emitter(DEVICE, out.append).send({"a": 0.0})
    after = time.time_ns() // 1000
    assert before <= json.loads(out[0])["ts_us"] <= after


def test_rejected_packet_consumes_no_seq() -> None:
    out: list[bytes] = []
    tx = Emitter(DEVICE, out.append, clock_us=lambda: 0)
    with pytest.raises(ValueError):
        tx.send({"a": float("nan")})
    assert tx.send({"a": 1.0}) == 0 and len(out) == 1


@pytest.mark.parametrize(
    ("device_id", "values", "kwargs"),
    [
        ("", {"a": 1.0}, {"ts_us": 0}),
        ("x" * 513, {"a": 1.0}, {"ts_us": 0}),
        (DEVICE, {}, {"ts_us": 0}),
        (DEVICE, {f"s{i}": 1.0 for i in range(MAX_SIGNALS + 1)}, {"ts_us": 0}),
        (DEVICE, {"": 1.0}, {"ts_us": 0}),
        (DEVICE, {"n" * (MAX_SIGNAL_NAME_LEN + 1): 1.0}, {"ts_us": 0}),
        (DEVICE, {"a": float("inf")}, {"ts_us": 0}),
        (DEVICE, {"a": float("nan")}, {"ts_us": 0}),
        (DEVICE, {"a": True}, {"ts_us": 0}),
        (DEVICE, {"a": "1.0"}, {"ts_us": 0}),
        (DEVICE, {"a": 1.0}, {"ts_us": 1.5}),
        (DEVICE, {"a": 1.0}, {"ts_us": True}),
        (DEVICE, {"a": 1.0}, {"ts_us": MAX_SAFE_INT + 1}),
        (DEVICE, {"a": 1.0}, {"ts_us": 0, "seq": -1}),
        (DEVICE, {"a": 1.0}, {"ts_us": 0, "seq": 1.0}),
        (DEVICE, {"a": 1.0}, {"ts_us": 0, "seq": MAX_SAFE_INT + 1}),
        (DEVICE, {"a": 1.0}, {"ts_us": 0, "units": {"b": "V"}}),
        (DEVICE, {"a": 1.0}, {"ts_us": 0, "units": {"a": ""}}),
        (DEVICE, {"a": 1.0}, {"ts_us": 0, "units": {"a": "u" * (MAX_UNIT_LEN + 1)}}),
    ],
)
def test_format_line_rejects_what_solus_would_refuse(
    device_id: str, values: dict[str, object], kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        format_line(device_id, values, **kwargs)  # type: ignore[arg-type]


def test_units_must_be_a_subset_of_values_but_may_be_partial() -> None:
    line = format_line(DEVICE, {"a": 1.0, "b": 2.0}, ts_us=0, units={"b": "V"})
    assert json.loads(line)["units"] == {"b": "V"}
    with pytest.raises(ValueError, match="not in values"):
        format_line(DEVICE, {"a": 1.0}, ts_us=0, units={"a": "V", "c": "A"})


def test_line_is_bounded_to_the_packet_size_cap() -> None:
    names = ["n" * (MAX_SIGNAL_NAME_LEN - 3) + str(i).zfill(3) for i in range(MAX_SIGNALS)]
    values = {name: 1.0 for name in names}
    units = {name: "u" * MAX_UNIT_LEN for name in names}
    assert len(format_line(DEVICE, values, ts_us=0)) <= MAX_LINE_BYTES
    with pytest.raises(ValueError, match="exceeds"):
        format_line(DEVICE, values, ts_us=0, units=units)


def test_ints_are_numbers_and_ascii_escaping_keeps_the_line_one_byte_per_char() -> None:
    line = format_line("dev/ü", {"a": 3}, ts_us=0)
    assert '"a":3' in line and "\\u00fc" in line
    assert line.encode("ascii")
