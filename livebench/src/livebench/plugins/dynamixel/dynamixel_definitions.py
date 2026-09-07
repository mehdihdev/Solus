"""Dynamixel Protocol 2.0 definitions (data only): the model-register → part-number table,
encoder resolution by model, the X-series control-table registers this plugin reads, and the
protocol facts a driver needs. Definitions are facts of the PART; everything the user chooses
(baud, ids, timeouts, poll rate) lives in the robot's config, never here."""

from __future__ import annotations

from typing import Final, NamedTuple

DXL_PROTOCOL_VERSION: Final = 2
#: ROBOTIS factory default — the params default; the robot's config overrides it.
DXL_DEFAULT_BAUD: Final = 57_600

#: Model-number register → part number. Curated; an unknown number stays a number, never a guess.
DXL_MODELS: Final[dict[int, str]] = {
    1020: "XM430-W350",
    1190: "XL330-M288",
    1200: "XC330-M288",
    1060: "XL430-W250",
    1120: "XM540-W270",
    350: "XL320",
}

#: Encoder ticks per revolution: 12-bit on the X series. The XL320 has a 10-bit encoder and its
#: own control table — ponytail: one X-series register map below; key it by model when an XL320
#: lands on the bench.
DXL_TICKS_PER_REV: Final = 4096
DXL_TICKS_PER_REV_BY_MODEL: Final[dict[str, int]] = {"XL320": 1024}


class DxlRegister(NamedTuple):
    address: int
    size: int


#: X-series control table (Protocol 2.0): the registers this plugin reads (or would write).
DXL_REGISTERS: Final[dict[str, DxlRegister]] = {
    "present_position": DxlRegister(132, 4),
    "torque_enable": DxlRegister(64, 1),
    "goal_position": DxlRegister(116, 4),
    "present_load": DxlRegister(126, 2),
    "present_temperature": DxlRegister(146, 1),
}


def dxl_resolution(model: str | None) -> int:
    """Ticks per revolution for a bus-map model (the X-series default when unknown)."""
    return DXL_TICKS_PER_REV_BY_MODEL.get(model or "", DXL_TICKS_PER_REV)
