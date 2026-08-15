"""Foxglove/MCAP JSON message payloads → LB-06 `TelemetryPacket` (CON-03).

Two payload classes, decided by one marker:

* **LB-06 wire** — the payload carries `ts_us`, so it IS the ratified packet format
  (a native Solus producer). Decoded by the LB-06 codec, preserving `seq` and
  `units` — but its `device_id` MUST equal the transport topic. `device_id` is
  graph identity (`graph_entity.external_ref`); a payload publishing on topic A
  must never assert itself as entity B (identity spoofing), so a mismatch drops
  the message. A broken LB-06 payload is rejected outright — never flattened,
  which would turn `ts_us` into a fake signal.
* **Generic JSON message** — any other object (a `foxglove_bridge` topic message,
  a ROS message serialized as json). Numeric leaves become signals, nested keys
  joined with dots; the topic is the `device_id` and the MCAP/WS log time is the
  timestamp.

Everything here is a trust boundary (CLAUDE.md §7): payloads are size-capped before
parsing, depth/width-bounded while flattening, invalid leaves (empty or overlong
names, non-finite or float-overflowing numbers) are dropped leaf-by-leaf, and every
whole-message failure returns ``None`` — one malformed message must never kill a
stream that carries thousands. The final packet construction is guarded too, so no
future validator can reintroduce a crash path.
"""

import json
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import ValidationError
from solus_api.graph.codec import MAX_PACKET_BYTES, TS_KEY, PacketDecodeError, decode_json
from solus_api.graph.packet import (
    MAX_DEVICE_ID_LEN,
    MAX_SIGNAL_NAME_LEN,
    MAX_SIGNALS_PER_PACKET,
    TelemetryPacket,
)

logger = logging.getLogger(__name__)

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

#: Flattening depth cap — a hostile payload nests to blow the stack, a real one doesn't.
MAX_FLATTEN_DEPTH: Final = 8


def timestamp_from_ns(log_time_ns: int) -> datetime:
    """Epoch nanoseconds → tz-aware datetime, exact to the microsecond (integer arithmetic —
    `datetime.fromtimestamp` on float seconds loses microseconds at modern epoch magnitudes)."""
    return _EPOCH + timedelta(microseconds=log_time_ns // 1_000)


def _flatten_numeric(
    obj: dict[str, object], prefix: str, depth: int, out: dict[str, float]
) -> None:
    for key, value in obj.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if not name or len(name) > MAX_SIGNAL_NAME_LEN:
            continue  # the packet would reject it; drop the leaf, keep the message
        # bool is an int subclass — a state flag is not a measurement.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                as_float = float(value)
            except OverflowError:
                continue  # a 400-digit JSON int is not telemetry
            if math.isfinite(as_float):
                out[name] = as_float
        elif isinstance(value, dict) and depth < MAX_FLATTEN_DEPTH:
            _flatten_numeric(value, name, depth + 1, out)


def _decode_lb06(topic: str, payload: bytes, *, trusted_identity: bool) -> TelemetryPacket | None:
    try:
        packet = decode_json(payload)
    except PacketDecodeError:
        logger.debug("dropping invalid LB-06 wire payload on %.64r", topic)
        return None
    if not trusted_identity and packet.device_id != topic:
        # Identity spoofing guard: the packet claims to be an entity the
        # transport topic does not own. Drop it.
        logger.debug("dropping LB-06 payload impersonating %.64r on %.64r", packet.device_id, topic)
        return None
    return packet


def packet_from_json_payload(
    topic: str, log_time_ns: int, payload: bytes, *, trusted_identity: bool = False
) -> TelemetryPacket | None:
    """One JSON message → one packet, or ``None`` when the message carries nothing usable.

    Never raises on payload content — this is the shared choke point for the MCAP
    and WS paths, and a poison message must drop itself, not the stream.

    `trusted_identity` relaxes the LB-06 device_id==topic spoofing guard for DIRECT
    links (serial, a robot's own WS) where the link itself is the identity boundary —
    one wire, one claimant. Bridged multi-topic transports must leave it False.
    """
    if not topic or len(topic) > MAX_DEVICE_ID_LEN:
        return None
    if len(payload) > MAX_PACKET_BYTES:
        logger.debug("dropping oversized payload on %.64r (%d bytes)", topic, len(payload))
        return None
    try:
        parsed = json.loads(payload)
    except Exception:  # same breadth as the LB-06 codec, for the same reason
        logger.debug("dropping malformed JSON payload on %.64r", topic)
        return None
    if not isinstance(parsed, dict):
        return None

    if TS_KEY in parsed:
        return _decode_lb06(topic, payload, trusted_identity=trusted_identity)

    values: dict[str, float] = {}
    _flatten_numeric(parsed, "", 0, values)
    if not values:
        return None
    if len(values) > MAX_SIGNALS_PER_PACKET:
        # Deterministic truncation: the lexicographically first N names, every run.
        values = {k: values[k] for k in sorted(values)[:MAX_SIGNALS_PER_PACKET]}
    try:
        return TelemetryPacket(
            device_id=topic, timestamp=timestamp_from_ns(log_time_ns), values=values
        )
    except ValidationError:
        # Belt-and-braces: no packet validator, current or future, may crash the stream.
        logger.debug("dropping payload failing packet validation on %.64r", topic)
        return None
