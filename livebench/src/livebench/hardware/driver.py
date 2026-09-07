"""The ProtocolDriver seam (R3): drivers are plugins behind a registry.

A driver declares which transports it can ride and a Pydantic model for its parameters; the
parameters themselves come from the robot's config (`protocol.params`), never from code, and the
register map from the part definition. Adding a driver is a new module plus a registration.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from pydantic import BaseModel
from solus_api.hardware.config import HardwareConfig, ProtocolBinding, TransportKind

from livebench.hardware.channel import TRANSPORT_ONLY_PARAM_KEYS, Channel
from livebench.telemetry.stream_live import PacketSource


class ProtocolDriver(Protocol):
    driver_id: ClassVar[str]
    display_name: ClassVar[str]
    transports: ClassVar[frozenset[TransportKind]]
    params_model: ClassVar[type[BaseModel]]

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> PacketSource:
        """A packet source over an open channel. Called off-loop; may block briefly."""
        ...


class DriverRegistry:
    def __init__(self) -> None:
        self._drivers: dict[str, ProtocolDriver] = {}

    def register(self, driver_cls: type[ProtocolDriver]) -> None:
        driver = driver_cls()
        if driver.driver_id in self._drivers:
            raise ValueError(f"driver {driver.driver_id} is already registered")
        self._drivers[driver.driver_id] = driver

    def get(self, driver_id: str) -> ProtocolDriver:
        return self._drivers[driver_id]  # KeyError: unknown driver

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "driver_id": driver.driver_id,
                "display_name": driver.display_name,
                "transports": sorted(kind.value for kind in driver.transports),
                "params_schema": driver.params_model.model_json_schema(),
            }
            for driver in sorted(self._drivers.values(), key=lambda d: d.driver_id)
        ]

    def validate_params(self, protocol: ProtocolBinding | None) -> BaseModel:
        """The driver's own model validates the config's parameters (unknown keys refused)."""
        if protocol is None:
            raise ValueError("the robot's config names no protocol driver")
        try:
            driver = self.get(protocol.driver_id)
        except KeyError:
            raise ValueError(f"unknown driver {protocol.driver_id!r}") from None
        params = {k: v for k, v in protocol.params.items() if k not in TRANSPORT_ONLY_PARAM_KEYS}
        return driver.params_model.model_validate(params)

    def open_source(self, config: HardwareConfig, channel: Channel) -> PacketSource:
        params = self.validate_params(config.protocol)
        assert config.protocol is not None  # validate_params refused None
        driver = self.get(config.protocol.driver_id)
        if channel.kind not in driver.transports:
            raise ValueError(
                f"driver {driver.driver_id} does not ride {channel.kind.value} transports"
            )
        return driver.open(channel, params, config)
