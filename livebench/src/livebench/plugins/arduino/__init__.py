"""Arduino-ecosystem plugin. On the `PLUGIN_MODULES` roster for its repo-config parser: the
sketch print-order reader (`sketch_parser.py`) that names a bare board's float channels from
`loop()` / `while True:`. The `arduino-cli` flash tool (`arduino_flash.py`) stays behind the
shared `FlashRunner` seam and is picked explicitly by the deploy path, never registered here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.arduino.sketch_parser import SketchConfigParser

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    registries.repo_parsers.register(SketchConfigParser)
