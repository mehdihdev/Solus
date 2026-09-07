"""The shared registries, built once per process: built-in transports first, then every
plugin under `livebench.plugins` registers what it knows. Shared code never imports a plugin
by name — the roster is data in `livebench.plugins.PLUGIN_MODULES`."""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.repo_config import RepoParserRegistry


@dataclass
class Registries:
    transports: TransportRegistry
    drivers: DriverRegistry
    interrogators: InterrogatorRegistry
    repo_parsers: RepoParserRegistry = field(default_factory=RepoParserRegistry.with_generic)


@functools.cache
def default_registries() -> Registries:
    from livebench.hardware.bluetooth import register_bluetooth
    from livebench.hardware.network import register_udp
    from livebench.hardware.usb_can import register_usb_can
    from livebench.hardware.usb_serial import register_usb_serial
    from livebench.plugins import load_all

    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    # Built-in transports: protocol-ignorant, honest when their stack is absent.
    register_usb_serial(registries.transports)
    register_usb_can(registries.transports)
    register_udp(registries.transports)
    register_bluetooth(registries.transports)
    load_all(registries)
    return registries
