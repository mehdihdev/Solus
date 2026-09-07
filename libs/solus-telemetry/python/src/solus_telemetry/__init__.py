"""solus-telemetry — emit Solus LB-06 telemetry packets as JSON lines (MIT, no dependencies).

One packet per line, keys always in this order (``seq`` omitted when ``None``, ``units`` when
empty)::

    {"schema_version":1,"device_id":"usb:5B42134331","ts_us":1757145600000000,
     "values":{"base.velocity":0.1234},"seq":0,"units":{"base.velocity":"m/s"}}

``ts_us`` is an integer count of microseconds (epoch on a host; since boot on a bare board);
``seq`` is the monotonic per-device counter Solus uses to detect drops and reordering. Signal
names follow ``<part>.<quantity>``; the unit lives in ``units``, never in the name.

The bounds below mirror the Solus packet contract (``docs/contracts/telemetry-packet.md`` §2);
the Solus repo asserts they have not drifted. Everything is validated BEFORE it is written so a
line that leaves this library always decodes on the other side.
"""

import json
import math
import time
from collections.abc import Callable, Mapping

SCHEMA_VERSION = 1
MAX_DEVICE_ID_LEN = 512
MAX_SIGNALS = 256
MAX_SIGNAL_NAME_LEN = 128
MAX_UNIT_LEN = 32
#: JavaScript-safe integer ceiling — the wire's integer domain is the intersection of its runtimes.
MAX_SAFE_INT = 2**53 - 1
#: A packet is one reading, not a file; Solus refuses longer lines before parsing them.
MAX_LINE_BYTES = 64 * 1024


def _now_us() -> int:
    return time.time_ns() // 1000


def _check_text(value: object, limit: int, what: str) -> None:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{what} must be a string of 1..{limit} characters")


def _check_int(value: object, what: str, *, low: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= MAX_SAFE_INT:
        raise ValueError(f"{what} must be an integer in {low}..{MAX_SAFE_INT}")


def _check_values(values: Mapping[str, float]) -> None:
    if not values or len(values) > MAX_SIGNALS:
        raise ValueError(f"values must carry 1..{MAX_SIGNALS} signals")
    for name, value in values.items():
        _check_text(name, MAX_SIGNAL_NAME_LEN, "signal name")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"signal {name!r} must be a number")
        if not math.isfinite(value):
            raise ValueError(f"signal {name!r} must be finite")


def _check_units(units: Mapping[str, str], values: Mapping[str, float]) -> None:
    for name, unit in units.items():
        if name not in values:
            raise ValueError(f"unit for {name!r} names a signal not in values")
        _check_text(unit, MAX_UNIT_LEN, f"unit for {name!r}")


def format_line(
    device_id: str,
    values: Mapping[str, float],
    *,
    ts_us: int,
    seq: int | None = None,
    units: Mapping[str, str] | None = None,
) -> str:
    """One LB-06 packet as a JSON line (newline included). Raises ``ValueError`` on anything
    the Solus decoder would refuse, so a bad packet fails here rather than silently on the bus."""
    _check_text(device_id, MAX_DEVICE_ID_LEN, "device_id")
    _check_int(ts_us, "ts_us", low=-MAX_SAFE_INT)
    _check_values(values)
    wire: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "device_id": device_id,
        "ts_us": ts_us,
        "values": dict(values),
    }
    if seq is not None:
        _check_int(seq, "seq", low=0)
        wire["seq"] = seq
    if units:
        _check_units(units, values)
        wire["units"] = dict(units)
    line = json.dumps(wire, separators=(",", ":"), allow_nan=False) + "\n"
    if len(line) > MAX_LINE_BYTES:  # ASCII-only output, so characters == bytes
        raise ValueError(f"line exceeds {MAX_LINE_BYTES} bytes")
    return line


class Emitter:
    """Stamps the clock, assigns the next ``seq`` (monotonic from 0) and writes one line per
    ``send``. ``write`` receives ``bytes`` — ``serial.write``, ``sock.sendall``,
    ``sys.stdout.buffer.write`` all fit."""

    def __init__(
        self,
        device_id: str,
        write: Callable[[bytes], object],
        *,
        clock_us: Callable[[], int] = _now_us,
    ) -> None:
        _check_text(device_id, MAX_DEVICE_ID_LEN, "device_id")
        self.device_id = device_id
        self._write = write
        self._clock_us = clock_us
        self._seq = 0

    def send(self, values: Mapping[str, float], units: Mapping[str, str] | None = None) -> int:
        """Write one packet; returns the ``seq`` it carried. A rejected packet consumes no seq."""
        seq = self._seq
        line = format_line(self.device_id, values, ts_us=self._clock_us(), seq=seq, units=units)
        self._write(line.encode("ascii"))
        self._seq = seq + 1
        return seq


__all__ = [
    "MAX_DEVICE_ID_LEN",
    "MAX_LINE_BYTES",
    "MAX_SAFE_INT",
    "MAX_SIGNALS",
    "MAX_SIGNAL_NAME_LEN",
    "MAX_UNIT_LEN",
    "SCHEMA_VERSION",
    "Emitter",
    "format_line",
]
