"""Vendor and protocol plugins (SOLUSDEV-248). This is the ONLY tree where a product may be
named. Each module exposes `register(registries)` and adds its transports, drivers and
interrogators; the roster below is the whole extension point — adding a machine class is a
new module plus one line here, never a change to shared code.

A plugin whose optional dependency is absent (no CAN library, no BLE stack) is skipped with a
log line and the registries simply lack it; nothing is faked.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries

logger = logging.getLogger(__name__)

PLUGIN_MODULES: Final[tuple[str, ...]] = (
    "livebench.plugins.lb06",
    "livebench.plugins.jsonlines",
    "livebench.plugins.raw",
    "livebench.plugins.feetech",
    "livebench.plugins.dynamixel",
    "livebench.plugins.odrive",
    "livebench.plugins.mavlink",
    "livebench.plugins.lerobot",
    "livebench.plugins.arduino",
)


def load_all(registries: Registries, *, modules: Sequence[str] = PLUGIN_MODULES) -> list[str]:
    """Import each plugin and let it register. Returns the modules that loaded."""
    loaded: list[str] = []
    for name in modules:
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            logger.info("plugin %s not loaded: %s", name, exc)
            continue
        module.register(registries)  # AttributeError here is a packaging bug, not a runtime one
        loaded.append(name)
    return loaded


def presence_provider() -> object | None:
    """Discover the provider-owned local compiler without request-supplied paths."""
    import shutil
    from pathlib import Path

    from livebench.plugins.arduino.presence_provider import LocalPresenceProvider

    binary = shutil.which("arduino-cli")
    if binary is None:
        return None
    library = Path(__file__).resolve().parents[4] / "libs/solus-telemetry/arduino"
    return LocalPresenceProvider(binary=str(Path(binary).resolve()), library=library)
