"""Feetech STS/SMS/SCS vendor data: control table, resolutions, model numbers, baud table.

Definitions, not configuration. A register address, a model number, a load-register bit layout
are facts about the product line the vendor fixed; which baud, which ids, which timeout THIS robot
uses are values in its HardwareConfig. Model 777 → STS3215 was read live from an SO-10x arm; the
other model numbers are the vendor's published values.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class FeetechRegister(NamedTuple):
    address: int
    size: int


#: STS/SMS series — protocol version 0, little-endian words.
STS_CONTROL_TABLE: Final[dict[str, FeetechRegister]] = {
    "Model_Number": FeetechRegister(3, 2),
    "ID": FeetechRegister(5, 1),
    "Baud_Rate": FeetechRegister(6, 1),
    "Homing_Offset": FeetechRegister(31, 2),
    "Torque_Enable": FeetechRegister(40, 1),
    "Goal_Position": FeetechRegister(42, 2),
    "Present_Position": FeetechRegister(56, 2),
    "Present_Load": FeetechRegister(60, 2),
    "Present_Temperature": FeetechRegister(63, 1),
}
#: SCS series — protocol version 1, big-endian words; these registers share the STS addresses.
SCS_CONTROL_TABLE: Final[dict[str, FeetechRegister]] = dict(STS_CONTROL_TABLE)
CONTROL_TABLE_BY_PROTOCOL: Final[dict[int, dict[str, FeetechRegister]]] = {
    0: STS_CONTROL_TABLE,
    1: SCS_CONTROL_TABLE,
}

#: Encoder ticks per revolution, by part number.
FEETECH_RESOLUTION: Final[dict[str, int]] = {
    "STS3215": 4096,
    "STS3250": 4096,
    "SM8512BL": 4096,
    "SCS0009": 1024,
}
DEFAULT_RESOLUTION: Final = 4096

#: Model-register value → part number. An unknown number is reported numerically, never guessed
#: into a name.
FEETECH_MODELS: Final[dict[int, str]] = {777: "STS3215", 2825: "STS3250", 11272: "SM8512BL"}

#: `Baud_Rate` register value is the index into this table (0 = 1 Mbaud, the factory rate).
FEETECH_BAUDS: Final[tuple[int, ...]] = (
    1_000_000,
    500_000,
    250_000,
    128_000,
    115_200,
    57_600,
    38_400,
    19_200,
)
#: Driver parameter DEFAULTS — the robot's config overrides them.
DEFAULT_BAUD: Final = 1_000_000
DEFAULT_TIMEOUT_S: Final = 0.05  # a servo answers in ~1 ms at 1 Mbaud
#: SO-10x arms use ids 1–6; scanning a little past that catches extra servos.
DEFAULT_CANDIDATE_IDS: Final = range(1, 13)
#: The wire allows ids 0..253 (254 is broadcast).
MAX_SERVO_ID: Final = 253

#: `Homing_Offset` is sign-magnitude: bit 11 set means negative (a burned -1934 reads as
#: 0x800 | 1934 == 3982). Each arm's burned offsets are its calibration signature.
HOMING_OFFSET_SIGN_BIT: Final = 0x800
#: `Present_Load`: bits 0–9 magnitude in 0.1 % steps (0..1000), bit 10 direction.
LOAD_MAGNITUDE_MASK: Final = 0x3FF
LOAD_DIRECTION_BIT: Final = 0x400
LOAD_PERCENT_PER_UNIT: Final = 0.1
