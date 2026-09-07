"""MAVLink v2 vendor data: the message layouts this plugin decodes, their crc_extra bytes and the
MAV_TYPE / MAV_AUTOPILOT name tables.

Definitions, not configuration. A message id, a field's width, a crc_extra byte are facts the
MAVLink dialect fixed (common.xml); which system id, which port, which heartbeat timeout THIS
robot uses are values in its HardwareConfig. Hand-rolled on purpose: pymavlink is LGPL.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class MavlinkMessageDef:
    """One message: `fields` are (name, struct code) in WIRE order — the MAVLink rule sorts base
    fields by size descending then declaration order; extension fields follow unsorted."""

    msg_id: int
    name: str
    crc_extra: int
    fields: tuple[tuple[str, str], ...]

    @property
    def wire_format(self) -> str:
        return "<" + "".join(code for _, code in self.fields)

    @property
    def length(self) -> int:
        return struct.calcsize(self.wire_format)


MAX_SERVO_OUTPUTS: Final = 16

HEARTBEAT: Final = MavlinkMessageDef(
    msg_id=0,
    name="HEARTBEAT",
    crc_extra=50,
    fields=(
        ("custom_mode", "I"),
        ("type", "B"),
        ("autopilot", "B"),
        ("base_mode", "B"),
        ("system_status", "B"),
        ("mavlink_version", "B"),
    ),
)
ATTITUDE: Final = MavlinkMessageDef(
    msg_id=30,
    name="ATTITUDE",
    crc_extra=39,
    fields=(
        ("time_boot_ms", "I"),
        ("roll", "f"),
        ("pitch", "f"),
        ("yaw", "f"),
        ("rollspeed", "f"),
        ("pitchspeed", "f"),
        ("yawspeed", "f"),
    ),
)
#: servo9..16 are v2 extension fields — absent on a v1-length frame, zero-padded by the decoder.
SERVO_OUTPUT_RAW: Final = MavlinkMessageDef(
    msg_id=36,
    name="SERVO_OUTPUT_RAW",
    crc_extra=222,
    fields=(
        ("time_usec", "I"),
        *((f"servo{n}_raw", "H") for n in range(1, 9)),
        ("port", "B"),
        *((f"servo{n}_raw", "H") for n in range(9, MAX_SERVO_OUTPUTS + 1)),
    ),
)

MESSAGES: Final[dict[int, MavlinkMessageDef]] = {
    m.msg_id: m for m in (HEARTBEAT, ATTITUDE, SERVO_OUTPUT_RAW)
}
CRC_EXTRA: Final[dict[int, int]] = {msg_id: m.crc_extra for msg_id, m in MESSAGES.items()}

#: MAV_TYPE and MAV_AUTOPILOT enum values → display names. Absent = unknown, never guessed.
MAV_TYPE_NAMES: Final[dict[int, str]] = {
    1: "fixed-wing",
    2: "quadrotor",
    4: "helicopter",
    10: "ground rover",
    12: "submarine",
    13: "hexarotor",
    14: "octorotor",
    20: "VTOL",
}
MAV_AUTOPILOT_NAMES: Final[dict[int, str]] = {3: "ArduPilot", 12: "PX4"}
