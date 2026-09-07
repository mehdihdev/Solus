"""`local.open_robot`: a validated HardwareConfig document in, a `robot` LiveConnection out,
opened through the default registries (built-in transports + plugins)."""

import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from livebench.hardware import registries as hardware_registries
from livebench.hardware.channel import Channel, Frame, TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.local import open_robot
from pydantic import BaseModel, ConfigDict
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportBinding, TransportKind


class _Chan:
    kind = TransportKind.USB_SERIAL

    def __init__(self, identity: TransportBinding) -> None:
        self.identity = identity

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return None

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baud: int = 115200


class _Source:
    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        yield TelemetryPacket(device_id="usb:X", timestamp=datetime.now(UTC), values={"a.b": 1})

    async def aclose(self) -> None: ...


class _Driver:
    driver_id: ClassVar[str] = "demo-bus"
    display_name: ClassVar[str] = "Demo"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    params_model: ClassVar[type[BaseModel]] = _Params

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> _Source:
        return _Source()


@pytest.fixture
def fake_registries(monkeypatch: pytest.MonkeyPatch) -> Registries:
    transports = TransportRegistry()

    def opener(binding: TransportBinding, params: Mapping[str, Any]) -> Channel:
        return _Chan(binding)

    transports.register(TransportKind.USB_SERIAL, opener)
    drivers = DriverRegistry()
    drivers.register(_Driver)
    registries = Registries(transports, drivers, InterrogatorRegistry())
    monkeypatch.setattr(hardware_registries, "default_registries", lambda: registries)
    return registries


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "robot_entity_id": str(uuid.uuid4()),
        "identity": {"kind": "usb_serial", "binding": "5B42134331"},
        "protocol": {"driver_id": "demo-bus", "params": {"baud": 1_000_000}},
        "provenance": {"identity": {"by": "detected"}, "protocol": {"by": "user"}},
    }
    document.update(overrides)
    return document


async def test_open_robot_opens_through_the_default_registries(
    fake_registries: Registries,
) -> None:
    project_id = uuid.uuid4()
    connection = await open_robot(_document(), project_id=project_id)
    assert connection.provider == "robot"
    assert connection.project_id == project_id
    assert connection.device_facts == {"device_ref": "usb:5B42134331", "driver_id": "demo-bus"}
    await connection.aclose()


async def test_open_robot_refuses_an_invalid_document(fake_registries: Registries) -> None:
    with pytest.raises(ValueError):
        await open_robot({"nope": 1}, project_id=uuid.uuid4())
    with pytest.raises(ValueError):
        await open_robot(_document(identity=None), project_id=uuid.uuid4())


async def test_open_robot_refuses_an_unknown_driver(fake_registries: Registries) -> None:
    document = _document(protocol={"driver_id": "no-such-driver", "params": {}})
    with pytest.raises(ValueError):
        await open_robot(document, project_id=uuid.uuid4())
