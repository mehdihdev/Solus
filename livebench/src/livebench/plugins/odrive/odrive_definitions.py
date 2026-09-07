"""ODrive CANSimple definitions (data only): the arbitration-id layout, the command ids this
plugin decodes, the wire fields each carries, how those map onto Solus quantities and units,
and a display-only model table. The heartbeat carries no model number, so a detected node's
model is never filled in from here — the table exists for library display alone."""

from __future__ import annotations

from typing import Final

#: arbitration id = node << 5 | cmd (11-bit frames: 6-bit node, 5-bit command).
ODRIVE_NODE_SHIFT: Final = 5
ODRIVE_CMD_MASK: Final = 0x1F
ODRIVE_MAX_NODE: Final = 0x3F

ODRIVE_CMD_HEARTBEAT: Final = 0x01
ODRIVE_CMD_GET_ENCODER_ESTIMATES: Final = 0x09
ODRIVE_CMD_GET_IQ: Final = 0x14
ODRIVE_CMD_BUS_VOLTAGE_CURRENT: Final = 0x17
ODRIVE_HEARTBEAT_BYTES: Final = 8
ODRIVE_PAIR_BYTES: Final = 8  # every decoded command carries two float32 LE

#: The CANSimple default; the params default, overridden by the robot's config.
ODRIVE_DEFAULT_BITRATE: Final = 250_000

#: Command → the two float32-LE fields it carries, in wire order (CANSimple names).
ODRIVE_FRAME_FIELDS: Final[dict[int, tuple[str, str]]] = {
    ODRIVE_CMD_GET_ENCODER_ESTIMATES: ("pos_estimate", "vel_estimate"),
    ODRIVE_CMD_GET_IQ: ("iq_setpoint", "iq_measured"),
    ODRIVE_CMD_BUS_VOLTAGE_CURRENT: ("bus_voltage", "bus_current"),
}

#: Solus quantity → unit (telemetry-packet.md §2a: units ride in the packet, never in names).
ODRIVE_UNITS: Final[dict[str, str]] = {
    "position": "rev",
    "velocity": "rev/s",
    "current": "A",
    "voltage": "V",
}

#: Wire field → Solus quantity. `iq_setpoint` and `bus_current` are decoded but not emitted
#: (ponytail: add them to this map when a Live Bench view wants them).
ODRIVE_SIGNALS: Final[dict[str, str]] = {
    "pos_estimate": "position",
    "vel_estimate": "velocity",
    "iq_measured": "current",
    "bus_voltage": "voltage",
}

#: Display data only — nothing on the bus says which of these a node is.
ODRIVE_MODELS: Final[tuple[str, ...]] = ("ODrive S1", "ODrive Pro", "ODrive v3.6")
