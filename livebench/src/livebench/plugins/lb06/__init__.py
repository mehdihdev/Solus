"""Solus telemetry over lines: the `lb06` driver and the `serial-framing` interrogator that
recognises line-framed streams (LB-06, plain JSON, CSV floats) on serial-shaped transports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.lb06.lb06_driver import Lb06Driver
from livebench.plugins.lb06.lb06_interrogator import SerialFramingInterrogator

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    registries.drivers.register(Lb06Driver)
    registries.interrogators.register(SerialFramingInterrogator)
