"""ODrive CANSimple codec — the heartbeat parser moved from `recognition/passive.py`
(SOLUSDEV-248), plus decoders for the estimate/current/voltage frames. Frames are untrusted
device input (CLAUDE.md §7): length-checked, node-bounded, non-finite floats dropped; nothing
here raises on bus bytes."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from typing import Final, NamedTuple

from livebench.plugins.odrive.odrive_definitions import (
    ODRIVE_CMD_HEARTBEAT,
    ODRIVE_CMD_MASK,
    ODRIVE_FRAME_FIELDS,
    ODRIVE_HEARTBEAT_BYTES,
    ODRIVE_MAX_NODE,
    ODRIVE_NODE_SHIFT,
    ODRIVE_PAIR_BYTES,
)

_PAIR: Final = struct.Struct("<ff")


class OdriveReading(NamedTuple):
    node: int
    cmd: int
    fields: dict[str, float]


def odrive_arbitration_id(node: int, cmd: int) -> int:
    return node << ODRIVE_NODE_SHIFT | cmd


def odrive_split_id(arbitration_id: int) -> tuple[int, int]:
    """(node, cmd) of an arbitration id."""
    return arbitration_id >> ODRIVE_NODE_SHIFT, arbitration_id & ODRIVE_CMD_MASK


def odrive_pack_pair(first: float, second: float) -> bytes:
    """Two float32 LE — the payload shape of every frame this codec decodes (fixture builder)."""
    return _PAIR.pack(first, second)


def odrive_heartbeat_nodes(frames: Iterable[tuple[int, bytes]]) -> list[int]:
    """ODrive nodes announce themselves: heartbeat frames (cmd 0x01) name the node."""
    nodes: set[int] = set()
    for arbitration_id, data in frames:
        node, cmd = odrive_split_id(arbitration_id)
        if cmd == ODRIVE_CMD_HEARTBEAT and len(data) >= ODRIVE_HEARTBEAT_BYTES:
            if node <= ODRIVE_MAX_NODE:
                nodes.add(node)
    return sorted(nodes)


def decode_odrive_frame(arbitration_id: int, data: bytes) -> OdriveReading | None:
    """A reading for the estimate, Iq and bus-voltage commands; None for anything else."""
    node, cmd = odrive_split_id(arbitration_id)
    layout = ODRIVE_FRAME_FIELDS.get(cmd)
    if layout is None or node > ODRIVE_MAX_NODE or len(data) < ODRIVE_PAIR_BYTES:
        return None
    values = _PAIR.unpack_from(data)
    fields = {
        name: float(value)
        for name, value in zip(layout, values, strict=True)
        if math.isfinite(value)
    }
    return OdriveReading(node, cmd, fields) if fields else None
