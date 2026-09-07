"""ODrive CANSimple plugin (SOLUSDEV-248): codec, definitions, the `odrive-can` driver and the
heartbeat interrogator. Rides the shared USB-CAN transport (`hardware/usb_can.py`, wired by
the registries) and registers no transport of its own."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.odrive.odrive_driver import OdriveCanDriver
from livebench.plugins.odrive.odrive_interrogator import OdriveCanInterrogator

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def _register_odrive(registries: Registries) -> None:
    registries.drivers.register(OdriveCanDriver)
    registries.interrogators.register(OdriveCanInterrogator)


#: The plugin contract's entry point: `livebench.plugins.load_all` calls `module.register`.
register = _register_odrive
