"""Solus telemetry emitter for MicroPython — one LB-06 JSON line per send() (MIT).

Copy this file to the board (``mpremote cp solus_telemetry.py :``) and::

    from solus_telemetry import Emitter
    tx = Emitter("usb:5B42134331", uart.write)
    tx.send({"base.velocity": 0.1234}, {"base.velocity": "m/s"})

Same line format as the Python and Arduino emitters (see README.md): fixed envelope key order
schema_version, device_id, ts_us, values, seq, units. Plain MicroPython — no typing module, no
f-strings, ujson or json, time.time_ns() when the port has it, else time.ticks_us().
The dict passed as ``values`` keeps whatever order the runtime gives it (MicroPython dicts are
unordered); Solus does not care about the order of signals inside ``values``.
"""

import time

try:
    import ujson as json
except ImportError:
    import json

SCHEMA_VERSION = 1
MAX_DEVICE_ID_LEN = 512
MAX_SIGNALS = 256
MAX_SIGNAL_NAME_LEN = 128
MAX_UNIT_LEN = 32
MAX_SAFE_INT = 2**53 - 1
MAX_LINE_BYTES = 64 * 1024
_INF = float("inf")


def _now_us():
    try:
        return time.time_ns() // 1000
    except AttributeError:  # port without time_ns(): microseconds since boot, wraps
        return time.ticks_us()  # type: ignore[attr-defined]  # MicroPython-only


def _check_text(value, limit, what):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(what + " must be a string of 1.." + str(limit) + " characters")


def _check_int(value, what, low):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= MAX_SAFE_INT:
        raise ValueError(what + " must be an integer in " + str(low) + ".." + str(MAX_SAFE_INT))


def _num(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("signal " + name + " must be a number")
    if value != value or value == _INF or value == -_INF:
        raise ValueError("signal " + name + " must be finite")
    return str(value)


def _values_json(values):
    if not values or len(values) > MAX_SIGNALS:
        raise ValueError("values must carry 1.." + str(MAX_SIGNALS) + " signals")
    parts = []
    for name in values:
        _check_text(name, MAX_SIGNAL_NAME_LEN, "signal name")
        parts.append(json.dumps(name) + ":" + _num(name, values[name]))
    return "{" + ",".join(parts) + "}"


def _units_json(units, values):
    parts = []
    for name in units:
        if name not in values:
            raise ValueError("unit for " + name + " names a signal not in values")
        _check_text(units[name], MAX_UNIT_LEN, "unit for " + name)
        parts.append(json.dumps(name) + ":" + json.dumps(units[name]))
    return "{" + ",".join(parts) + "}"


def format_line(device_id, values, *, ts_us, seq=None, units=None):
    """One LB-06 packet as a JSON line (newline included); ValueError on anything Solus refuses."""
    _check_text(device_id, MAX_DEVICE_ID_LEN, "device_id")
    _check_int(ts_us, "ts_us", -MAX_SAFE_INT)
    line = (
        '{"schema_version":'
        + str(SCHEMA_VERSION)
        + ',"device_id":'
        + json.dumps(device_id)
        + ',"ts_us":'
        + str(ts_us)
        + ',"values":'
        + _values_json(values)
    )
    if seq is not None:
        _check_int(seq, "seq", 0)
        line += ',"seq":' + str(seq)
    if units:
        line += ',"units":' + _units_json(units, values)
    line += "}\n"
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("line exceeds " + str(MAX_LINE_BYTES) + " bytes")
    return line


class Emitter:
    """send(values, units=None) -> the seq it carried; seq is monotonic from 0.
    ``write`` receives bytes (``uart.write``, ``sock.send``, ``sys.stdout.buffer.write``)."""

    def __init__(self, device_id, write, clock_us=None):
        _check_text(device_id, MAX_DEVICE_ID_LEN, "device_id")
        self.device_id = device_id
        self._write = write
        self._clock_us = clock_us or _now_us
        self._seq = 0

    def send(self, values, units=None):
        seq = self._seq
        line = format_line(self.device_id, values, ts_us=self._clock_us(), seq=seq, units=units)
        self._write(line.encode())
        self._seq = seq + 1
        return seq


if (
    __name__ == "__main__"
):  # self-check: python3 solus_telemetry.py  /  mpremote run solus_telemetry.py
    _golden = (
        '{"schema_version":1,"device_id":"usb:5B42134331","ts_us":1234567,'
        '"values":{"base.velocity":0.1234},"seq":0,"units":{"base.velocity":"m/s"}}\n'
    )
    _line = format_line(
        "usb:5B42134331",
        {"base.velocity": 0.1234},
        ts_us=1234567,
        seq=0,
        units={"base.velocity": "m/s"},
    )
    assert _line == _golden, _line
    _out = []  # type: list[bytes]
    _tx = Emitter("usb:5B42134331", _out.append, clock_us=lambda: 1234567)
    assert _tx.send({"base.velocity": 0.1234}, {"base.velocity": "m/s"}) == 0
    assert _tx.send({"base.velocity": 0.1234}) == 1
    assert _out[0] == _golden.encode() and b'"seq":1}\n' in _out[1], _out
    for _bad in ({}, {"x": float("nan")}, {"x": True}, {"": 1.0}):
        try:
            format_line("d", _bad, ts_us=0)
        except ValueError:
            pass
        else:
            raise AssertionError(_bad)
    print("solus_telemetry self-check ok")
