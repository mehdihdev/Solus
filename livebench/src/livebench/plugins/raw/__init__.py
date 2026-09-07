"""Raw numeric lines over a serial-shaped transport: the `raw-lines` driver."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.raw.raw_driver import RawLinesDriver

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    registries.drivers.register(RawLinesDriver)
