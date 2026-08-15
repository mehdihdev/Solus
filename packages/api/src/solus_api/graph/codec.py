"""LB-06 telemetry packet codec — msgpack on the wire, JSON for debugging (SOLUSDEV-126).

ONE canonical wire mapping (`to_wire` / `from_wire`), two transports over it: msgpack for
throughput and JSON for eyeballing and for JSON-only carriers (Foxglove's `json` message
encoding). Keeping a single mapping is what lets the TypeScript decoder be one implementation
instead of two, and what makes the golden-fixture corpus meaningful.

**Forward compatibility is the load-bearing property.** Producers and consumers upgrade at
different times, so the split is Postel's:

  * `TelemetryPacket` keeps `extra="forbid"` — Solus code can never CONSTRUCT a malformed packet.
  * `from_wire` filters to known keys before validating — a packet from a NEWER producer decodes
    fine, its unknown fields ignored, its higher `schema_version` reported rather than rewritten.

Adding a field is therefore a non-breaking change by construction. Removing or retyping one is
not, and needs a `schema_version` major treatment plus a contract amendment.

Timestamps ride as epoch MICROSECONDS (`ts_us`, integer), computed with integer arithmetic.
`datetime.timestamp()` returns float seconds and silently loses microsecond precision at modern
epoch magnitudes — for a telemetry clock that is a correctness bug, not a rounding detail.

Decoding is a TRUST BOUNDARY (CLAUDE.md §7). The bytes arrive from a device nobody controls, so
the payload is size-capped before unpacking, the unpacker is bounded on every axis msgpack can
grow (str/map/array/bin/ext), and every failure surfaces as `PacketDecodeError` — ingestion
catches exactly one type and drops the packet instead of crashing the stream.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import msgpack
from pydantic import ValidationError

from solus_api.graph.packet import MAX_SAFE_INT, MAX_SIGNALS_PER_PACKET, TelemetryPacket

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

#: Wire key for the timestamp. Named distinctly from the model field so the unit is unmissable:
#: it is an integer count of microseconds since the Unix epoch, never seconds and never a string.
TS_KEY: Final = "ts_us"

#: A packet is ONE reading from ONE device, not a file. Anything larger is not a packet.
MAX_PACKET_BYTES: Final = 64 * 1024

# Unpacker bounds (§7): every axis msgpack could be made to grow along. `bin`/`ext` are disabled
# outright — the format has no field that uses them, so accepting them is pure attack surface.
_MAX_MAP_LEN: Final = MAX_SIGNALS_PER_PACKET * 2 + 16  # values + units + the scalar fields
_MAX_STR_LEN: Final = 1024  # comfortably over device_id (512) and signal names (128)
_UNPACK_LIMITS: Final[dict[str, Any]] = {
    "strict_map_key": True,
    "raw": False,
    "max_str_len": _MAX_STR_LEN,
    "max_map_len": _MAX_MAP_LEN,
    "max_array_len": _MAX_MAP_LEN,
    "max_bin_len": 0,
    "max_ext_len": 0,
}

#: The keys this build understands. Anything else on the wire came from a newer producer.
_WIRE_KEYS: Final[frozenset[str]] = frozenset(
    (set(TelemetryPacket.model_fields) - {"timestamp"}) | {TS_KEY}
)


class PacketDecodeError(ValueError):
    """A packet could not be decoded. The one exception type ingestion catches — malformed
    framing, oversize payloads and failed validation all surface as this, so a hostile stream
    cannot distinguish failure modes or crash the reader."""


def _to_epoch_us(moment: datetime) -> int:
    delta = moment - _EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _from_epoch_us(raw: object) -> datetime:
    # bool is an int subclass — a JSON `true` must not silently become 1970-01-01T00:00:00.000001.
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise PacketDecodeError(f"{TS_KEY} must be an integer count of microseconds")
    # Bounded to the JS-safe range, not to Python's: a timestamp this decoder accepts but the
    # TypeScript one silently rounds is a packet that cannot survive the round trip to the UI.
    if abs(raw) > MAX_SAFE_INT:
        raise PacketDecodeError(f"{TS_KEY} exceeds the safe integer range")
    try:
        return _EPOCH + timedelta(microseconds=raw)
    except (OverflowError, OSError, ValueError) as exc:
        raise PacketDecodeError(f"{TS_KEY} out of representable range") from exc


def to_wire(packet: TelemetryPacket) -> dict[str, Any]:
    """The canonical language-neutral wire dict. Both encoders serialize exactly this.

    The wire carries an INSTANT, not a local time: a decoded packet's `timestamp` is always UTC,
    whatever zone the producer used. The instant is preserved exactly, but the producer's original
    `tzinfo` is not — so a decoded packet is `==` to the original for ordinary timestamps and for
    UTC ones, while a producer that stamps local wall-clock inside a DST-ambiguous or
    non-existent hour gets a datetime that is the same instant yet compares unequal (PEP 495
    fold semantics). Producers should stamp in UTC; consumers should compare instants.
    """
    wire: dict[str, Any] = {
        "schema_version": packet.schema_version,
        "device_id": packet.device_id,
        TS_KEY: _to_epoch_us(packet.timestamp),
        "values": dict(packet.values),
    }
    # Omit what carries no information — an unsequenced packet and an unlabelled one should not
    # pay for fields they do not use, on a wire that carries thousands of packets a second.
    if packet.seq is not None:
        wire["seq"] = packet.seq
    if packet.units:
        wire["units"] = dict(packet.units)
    return wire


def from_wire(wire: Mapping[str, Any]) -> TelemetryPacket:
    """Wire dict → packet, tolerantly: unknown keys are dropped so a newer producer's packet
    still decodes here. Everything that survives is validated by `TelemetryPacket` (§7)."""
    if not isinstance(wire, Mapping):
        raise PacketDecodeError("packet payload must be a map")
    known: dict[str, Any] = {k: v for k, v in wire.items() if k in _WIRE_KEYS}
    if TS_KEY not in known:
        raise PacketDecodeError(f"packet is missing {TS_KEY}")
    timestamp = _from_epoch_us(known.pop(TS_KEY))
    try:
        return TelemetryPacket(timestamp=timestamp, **known)
    except ValidationError as exc:
        raise PacketDecodeError(f"packet failed validation: {exc.error_count()} error(s)") from exc


def encode(packet: TelemetryPacket) -> bytes:
    """msgpack — the throughput form, for sim/robot/bridge transports and MCAP."""
    packed: bytes = msgpack.packb(to_wire(packet), use_bin_type=True)
    return packed


def decode(raw: bytes) -> TelemetryPacket:
    """msgpack → packet. Size-capped and bounded; every failure is a `PacketDecodeError`."""
    if not raw:
        raise PacketDecodeError("empty packet payload")
    if len(raw) > MAX_PACKET_BYTES:
        # Checked BEFORE unpacking: refusing by length costs nothing, whereas letting the
        # unpacker discover the size means already having allocated for it.
        raise PacketDecodeError(f"packet exceeds {MAX_PACKET_BYTES} bytes")
    try:
        wire = msgpack.unpackb(raw, **_UNPACK_LIMITS)
    except Exception as exc:  # msgpack raises several unrelated types for malformed input
        raise PacketDecodeError("malformed msgpack payload") from exc
    return from_wire(wire)


def encode_json(packet: TelemetryPacket) -> str:
    """The debug form — the SAME wire dict, JSON-encoded. Readable in a log, and the payload for
    JSON-only carriers (e.g. a Foxglove WS channel using the `json` message encoding)."""
    return json.dumps(to_wire(packet), separators=(",", ":"), sort_keys=True)


def decode_json(raw: str | bytes) -> TelemetryPacket:
    """JSON → packet, with the same tolerance and the same single error type as `decode`."""
    # Measure BYTES, not characters: `len()` on a str counts code points, so a payload of
    # multi-byte characters would slip ~3x past a cap that claims to be in bytes.
    blob = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    if len(blob) > MAX_PACKET_BYTES:
        raise PacketDecodeError(f"packet exceeds {MAX_PACKET_BYTES} bytes")
    try:
        wire = json.loads(blob)
    except Exception as exc:
        # As broad as the msgpack path, and for the same reason: `json` raises types that are
        # neither JSONDecodeError nor UnicodeDecodeError. Deep nesting raises RecursionError, and
        # a long integer literal raises a bare ValueError (CPython's int_max_str_digits guard) —
        # and since PacketDecodeError SUBCLASSES ValueError, that one would sail straight through
        # a caller's `except PacketDecodeError` and kill the reader for every device on the link.
        raise PacketDecodeError("malformed JSON payload") from exc
    return from_wire(wire)


__all__ = [
    "MAX_PACKET_BYTES",
    "TS_KEY",
    "PacketDecodeError",
    "decode",
    "decode_json",
    "encode",
    "encode_json",
    "from_wire",
    "to_wire",
]
