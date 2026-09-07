"""Plain JSON lines over a serial-shaped transport: the `json-lines` driver."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.jsonlines.jsonlines_driver import JsonLinesDriver

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    registries.drivers.register(JsonLinesDriver)
