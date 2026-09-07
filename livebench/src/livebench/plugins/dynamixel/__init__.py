"""Dynamixel Protocol 2.0 plugin (SOLUSDEV-248): codec, definitions, the `dynamixel-2` driver and
the broadcast-ping interrogator. Rides the shared USB-serial transport; registers no transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.dynamixel.dynamixel_driver import DynamixelDriver
from livebench.plugins.dynamixel.dynamixel_interrogator import DynamixelBusInterrogator

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def _register_dynamixel(registries: Registries) -> None:
    registries.drivers.register(DynamixelDriver)
    registries.interrogators.register(DynamixelBusInterrogator)


#: The plugin contract's entry point: `livebench.plugins.load_all` calls `module.register`.
register = _register_dynamixel
