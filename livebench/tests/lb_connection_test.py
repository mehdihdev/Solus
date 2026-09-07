"""R3 robot connection: config in, LiveConnection out. The transport is re-resolved by its
binding identity on every reconnect incarnation, so a swapped tty never swaps arms."""

import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from livebench.hardware.channel import Channel, Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.connection import (
    PartRoutingSource,
    RobotConnection,
    build_source_factory,
    open_robot_connection,
    part_routes,
)
from livebench.hardware.driver import DriverRegistry
from pydantic import BaseModel, ConfigDict
from solus_api.connectors.live import LiveStatus
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    ConfigLayer,
    FieldProvenance,
    HardwareConfig,
    TransportBinding,
    TransportKind,
    merge_layers,
    part_ref,
)


class _Chan:
    kind = TransportKind.USB_SERIAL

    def __init__(self, identity: TransportBinding) -> None:
        self.identity = identity
        self.closed = False

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return None

    def flush_input(self) -> None: ...

    def close(self) -> None:
        self.closed = True


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baud: int = 115200


class _Source:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        yield TelemetryPacket(
            device_id=self.device_id, timestamp=datetime.now(UTC), values={"j.position": 1.0}
        )

    async def aclose(self) -> None:
        self.closed = True


class _Driver:
    driver_id: ClassVar[str] = "demo-bus"
    display_name: ClassVar[str] = "Demo"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    params_model: ClassVar[type[BaseModel]] = _Params

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> _Source:
        return _Source(channel.identity.device_ref)


def _registries() -> tuple[TransportRegistry, DriverRegistry, list[_Chan]]:
    opened: list[_Chan] = []

    def opener(binding: TransportBinding, params: Mapping[str, Any]) -> Channel:
        # A real transport re-resolves the path from the binding on every open.
        channel = _Chan(binding.model_copy(update={"last_seen_path": f"/dev/tty{len(opened)}"}))
        opened.append(channel)
        return channel

    transports = TransportRegistry()
    transports.register(TransportKind.USB_SERIAL, opener)
    drivers = DriverRegistry()
    drivers.register(_Driver)
    return transports, drivers, opened


def _config(**overrides: Any) -> HardwareConfig:
    base: dict[str, Any] = {
        "robot_entity_id": str(uuid.uuid4()),
        "identity": {"kind": "usb_serial", "binding": "5B42134331"},
        "protocol": {"driver_id": "demo-bus", "params": {"baud": 1_000_000}},
        "provenance": {"identity": {"by": "detected"}, "protocol": {"by": "user"}},
    }
    base.update(overrides)
    return HardwareConfig.model_validate(base)


def test_factory_reopens_the_transport_by_identity_each_incarnation() -> None:
    transports, drivers, opened = _registries()
    factory = build_source_factory(_config(), transports=transports, drivers=drivers)
    first = factory()
    second = factory()
    assert isinstance(first, _Source) and isinstance(second, _Source)
    assert len(opened) == 2
    assert opened[0].identity.device_ref == opened[1].identity.device_ref == "usb:5B42134331"
    assert opened[0].identity.last_seen_path != opened[1].identity.last_seen_path


def test_open_probes_the_transport_eagerly_and_exposes_device_facts() -> None:
    transports, drivers, opened = _registries()
    project_id = uuid.uuid4()
    connection = open_robot_connection(
        _config(), project_id=project_id, transports=transports, drivers=drivers
    )
    assert isinstance(connection, RobotConnection)
    assert connection.provider == "robot"
    assert connection.project_id == project_id
    assert connection.status() is LiveStatus.DISCONNECTED
    assert len(opened) == 1 and opened[0].closed  # the eager probe is closed again
    assert connection.device_facts == {"device_ref": "usb:5B42134331", "driver_id": "demo-bus"}


def test_open_fails_fast_when_the_transport_cannot_open() -> None:
    transports = TransportRegistry()
    drivers = DriverRegistry()
    drivers.register(_Driver)
    with pytest.raises(TransportUnavailableError):
        open_robot_connection(
            _config(), project_id=uuid.uuid4(), transports=transports, drivers=drivers
        )


def test_open_refuses_a_config_without_identity_or_protocol() -> None:
    transports, drivers, _ = _registries()
    for missing in ("identity", "protocol"):
        config = _config(**{missing: None})
        with pytest.raises(ValueError):
            open_robot_connection(
                config, project_id=uuid.uuid4(), transports=transports, drivers=drivers
            )


async def test_a_started_connection_streams_packets_keyed_by_the_device_ref() -> None:
    transports, drivers, _ = _registries()
    connection = open_robot_connection(
        _config(), project_id=uuid.uuid4(), transports=transports, drivers=drivers, reconnect=False
    )
    seen: list[TelemetryPacket] = []

    async def tap(packet: TelemetryPacket) -> None:
        seen.append(packet)

    connection.tap = tap
    from solus_api.agent.interfaces import TelemetryWindow

    handle = await connection.subscribe(TelemetryWindow(duration_seconds=1.0))
    import asyncio

    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.01)
    await connection.unsubscribe(handle)
    await connection.aclose()
    assert seen and seen[0].device_id == "usb:5B42134331"


def test_connection_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.connection as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None


_PART_1, _PART_6 = str(uuid.uuid4()), str(uuid.uuid4())


def _keyed_config(parts: dict[str, list[str]] | None = None) -> HardwareConfig:
    """Bound parts (addresses 1 and 6 by default) and one unbound bus slot (9)."""
    parts = parts or {_PART_1: ["shoulder_pan.position"], _PART_6: ["gripper.position"]}
    addresses = dict(zip(parts, ("1", "6", "0"), strict=False))
    document = {
        "identity": {"kind": "usb_serial", "binding": "5B42134331"},
        "protocol": {"driver_id": "demo-bus", "params": {"baud": 1_000_000}},
        "bus_map": [
            {"protocol": "demo-bus", "address": addresses[pid], "part_entity_id": pid}
            for pid in parts
        ]
        + [{"protocol": "demo-bus", "address": "9", "part_entity_id": None}],
        "parts": {
            pid: {"telemetry": [{"name": name} for name in names], "lifecycle": "live"}
            for pid, names in parts.items()
        },
    }
    return merge_layers(uuid.uuid4(), [ConfigLayer(by=FieldProvenance.DETECTED, document=document)])


def test_part_routes_come_from_the_config_alone() -> None:
    key_1, key_6 = "usb:5B42134331/1", "usb:5B42134331/6"
    assert part_routes(_keyed_config()) == {
        "shoulder_pan.position": key_1,
        "shoulder_pan": key_1,
        "addr_1": key_1,
        "gripper.position": key_6,
        "gripper": key_6,
        "addr_6": key_6,
    }
    assert part_routes(_config()) == {}  # no parts → nothing to route


def test_a_prefix_two_parts_share_routes_by_exact_name_only() -> None:
    """Two parts whose channels share a `<part>` prefix: each exact name routes to its own
    part; the ambiguous prefix routes nowhere (an undeclared `base.x` keeps the device key)."""
    routes = part_routes(
        _keyed_config({_PART_1: ["base.velocity"], _PART_6: ["base.angular_velocity"]})
    )
    assert routes == {
        "base.velocity": "usb:5B42134331/1",
        "addr_1": "usb:5B42134331/1",
        "base.angular_velocity": "usb:5B42134331/6",
        "addr_6": "usb:5B42134331/6",
    }


async def test_packets_are_split_so_each_part_carries_its_own_graph_key() -> None:
    """The silent-zero trap (docs/api/hardware.md §6): the resolver matches `device_id` against
    `external_ref`, and a part's external_ref is `<device ref>/<address>` — so a sweep packet
    keyed by the device alone resolves to nothing. Every signal goes out under its part's key;
    signals no bound part claims keep the device's key."""

    class _Sweep:
        async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
            yield TelemetryPacket(
                device_id="usb:5B42134331",
                timestamp=datetime.now(UTC),
                seq=7,
                values={
                    "shoulder_pan.position": 1.0,
                    "shoulder_pan.load": 2.0,
                    "gripper.position": 3.0,
                    "addr_9.position": 4.0,
                    "bus.voltage": 5.0,
                },
                units={"shoulder_pan.position": "deg", "gripper.position": "%", "bus.voltage": "V"},
            )

        async def aclose(self) -> None: ...

    source = PartRoutingSource(_Sweep(), part_routes(_keyed_config()))
    packets = [packet async for packet in source]
    by_key = {p.device_id: p for p in packets}
    assert set(by_key) == {"usb:5B42134331/1", "usb:5B42134331/6", "usb:5B42134331"}
    assert by_key["usb:5B42134331/1"].values == {
        "shoulder_pan.position": 1.0,
        "shoulder_pan.load": 2.0,
    }
    assert by_key["usb:5B42134331/1"].units == {"shoulder_pan.position": "deg"}
    assert by_key["usb:5B42134331/6"].values == {"gripper.position": 3.0}
    assert by_key["usb:5B42134331"].values == {"addr_9.position": 4.0, "bus.voltage": 5.0}
    assert {p.seq for p in packets} == {7}
    assert len({p.timestamp for p in packets}) == 1


async def test_an_opened_connection_routes_to_parts_when_the_config_binds_them() -> None:
    transports, drivers, _ = _registries()

    class _KeyedDriver(_Driver):
        def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> _Source:
            source = _Source(channel.identity.device_ref)
            return source

    drivers = DriverRegistry()
    drivers.register(_KeyedDriver)
    config = _keyed_config({_PART_1: ["j.position"]})
    connection = open_robot_connection(
        config, project_id=uuid.uuid4(), transports=transports, drivers=drivers, reconnect=False
    )
    seen: list[TelemetryPacket] = []

    async def tap(packet: TelemetryPacket) -> None:
        seen.append(packet)

    connection.tap = tap
    import asyncio

    from solus_api.agent.interfaces import TelemetryWindow

    handle = await connection.subscribe(TelemetryWindow(duration_seconds=1.0))
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.01)
    await connection.unsubscribe(handle)
    await connection.aclose()
    assert seen and seen[0].device_id == part_ref("usb:5B42134331", "1")
