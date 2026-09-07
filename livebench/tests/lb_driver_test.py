"""R3 ProtocolDriver seam: drivers are plugins behind a registry; a driver reads its parameters
from the robot's config (validated by the driver's own params model), never from code."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from livebench.hardware.channel import Channel, Frame
from livebench.hardware.driver import DriverRegistry, ProtocolDriver
from pydantic import BaseModel, ConfigDict, Field
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    HardwareConfig,
    ProtocolBinding,
    TransportBinding,
    TransportKind,
)


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baud: int = Field(default=115200, ge=300, le=3_000_000)
    timeout_s: float = Field(default=0.05, gt=0, le=5)


class _Source:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        yield TelemetryPacket(
            device_id=self.device_id, timestamp=datetime.now(UTC), values={"a.b": 1.0}
        )

    async def aclose(self) -> None:
        self.closed = True


class _Driver:
    driver_id: ClassVar[str] = "demo-bus"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    params_model: ClassVar[type[BaseModel]] = _Params
    display_name: ClassVar[str] = "Demo request-response bus"

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> _Source:
        assert isinstance(params, _Params)
        return _Source(channel.identity.device_ref)


class _Chan:
    kind = TransportKind.USB_SERIAL

    def __init__(self) -> None:
        self.identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="ABC")

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return None

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


def _config(driver_id: str = "demo-bus", **params: object) -> HardwareConfig:
    import uuid

    return HardwareConfig(
        robot_entity_id=uuid.uuid4(),
        identity=TransportBinding(kind=TransportKind.USB_SERIAL, binding="ABC"),
        protocol=ProtocolBinding(driver_id=driver_id, params=params),  # type: ignore[arg-type]
        provenance={"identity": {"by": "detected"}, "protocol": {"by": "user"}},  # type: ignore[dict-item]
    )


def test_register_get_and_catalog() -> None:
    registry = DriverRegistry()
    registry.register(_Driver)
    driver: ProtocolDriver = registry.get("demo-bus")
    assert driver.driver_id == "demo-bus"
    assert registry.catalog() == [
        {
            "driver_id": "demo-bus",
            "display_name": "Demo request-response bus",
            "transports": ["usb_serial"],
            "params_schema": _Params.model_json_schema(),
        }
    ]
    with pytest.raises(KeyError):
        registry.get("nope")
    with pytest.raises(ValueError):
        registry.register(_Driver)


def test_params_come_from_config_and_are_validated_by_the_driver() -> None:
    registry = DriverRegistry()
    registry.register(_Driver)
    params = registry.validate_params(_config(baud=1_000_000, timeout_s=0.02).protocol)
    assert isinstance(params, _Params) and params.baud == 1_000_000
    with pytest.raises(ValueError):
        registry.validate_params(_config(bogus=1).protocol)
    with pytest.raises(ValueError):
        registry.validate_params(_config(baud=10).protocol)


def test_transport_only_keys_never_reach_a_strict_driver_model() -> None:
    registry = DriverRegistry()
    registry.register(_Driver)
    params = registry.validate_params(
        _config(baud=9600, confirmed_device_path="/dev/ttyUSB0", listen_port=14550).protocol
    )
    assert isinstance(params, _Params) and params.baud == 9600


def test_a_driver_must_support_the_channels_transport() -> None:
    registry = DriverRegistry()
    registry.register(_Driver)
    channel = _Chan()
    channel.kind = TransportKind.USB_CAN
    with pytest.raises(ValueError):
        registry.open_source(_config(), channel)


async def test_open_source_yields_packets_keyed_by_the_channel_identity() -> None:
    registry = DriverRegistry()
    registry.register(_Driver)
    source = registry.open_source(_config(baud=1_000_000), _Chan())
    packets = [packet async for packet in source]
    assert packets[0].device_id == "usb:ABC"
    await source.aclose()


def test_driver_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.driver as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None
