"""Feetech STS/SMS/SCS servo bus (LeRobot SO-10x arms): wire codec, polling driver, ping
interrogator. Vendor names live here and in `feetech_definitions`; the seams they plug into
(`livebench.hardware`) never name them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.feetech.feetech_driver import FeetechStsDriver
from livebench.plugins.feetech.feetech_interrogator import FeetechBusInterrogator

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    registries.drivers.register(FeetechStsDriver)
    registries.interrogators.register(FeetechBusInterrogator)
