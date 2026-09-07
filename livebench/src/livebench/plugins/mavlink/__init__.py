"""MAVLink v2 autopilot link (PX4, ArduPilot): a hand-rolled codec (pymavlink is LGPL), a
telemetry driver, a heartbeat interrogator, and the UDP transport it usually rides. Vendor
names live here and in `mavlink_definitions`; the seams they plug into never name them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from solus_api.hardware.config import TransportKind

from livebench.hardware.network import register_udp
from livebench.plugins.mavlink.mavlink_driver import MavlinkDriver
from livebench.plugins.mavlink.mavlink_interrogator import MavlinkHeartbeatInterrogator

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    if TransportKind.WIFI not in registries.transports.kinds():
        register_udp(registries.transports)  # shared transport; the host may own it later
    registries.drivers.register(MavlinkDriver)
    registries.interrogators.register(MavlinkHeartbeatInterrogator)
