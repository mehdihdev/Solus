"""A robot's LiveConnection from its config (R3): transport → driver → reconnect → observers →
windowing. Composition order is the one `telemetry/robot.py` fixed: the link heals below the
observers so a reconnect gap reaches the gap watchdog.

Identity across reconnects: the source factory re-opens the transport from the config's
binding identity on every incarnation, so the path is re-resolved each time and a swapped tty
can never swap arms.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, ClassVar
from uuid import UUID

from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, ProtocolBinding, TransportBinding, part_ref

from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.telemetry.observing_source import EventSink, Observer
from livebench.telemetry.reconnect import ReconnectingSource
from livebench.telemetry.robot import _observed
from livebench.telemetry.stream_live import PacketSource, PacketStreamLiveConnection


class RobotConnection(PacketStreamLiveConnection):
    """Any configured robot; the driver is a fact on the session, not a provider class."""

    provider: ClassVar[str] = "robot"

    def __init__(
        self, source: PacketSource, *, project_id: UUID | None, device_facts: dict[str, Any]
    ) -> None:
        super().__init__(source, project_id=project_id)
        self.device_facts = device_facts


def part_routes(config: HardwareConfig) -> dict[str, str]:
    """Signal name or `<part>` prefix → the part's graph key `<device ref>/<address>` (what
    confirm wrote to the part's `external_ref`), from the config alone: a bound part's declared
    telemetry names (exact), their `<part>` prefix when no other part claims it (so undeclared
    signals such as `<part>.load` still route), and the drivers' unnamed form `addr_<address>`
    (telemetry-packet.md §2a)."""
    if config.identity is None:
        return {}
    routes: dict[str, str] = {}
    ambiguous: set[str] = set()
    for entry in config.bus_map:
        if entry.part_entity_id is None:
            continue
        key = part_ref(config.identity.device_ref, entry.address)
        routes[f"addr_{entry.address}"] = key
        part = config.parts.get(str(entry.part_entity_id))
        for channel in part.telemetry if part is not None else ():
            routes[channel.name] = key
            prefix = channel.name.split(".", 1)[0]
            if routes.setdefault(prefix, key) != key:
                ambiguous.add(prefix)
    return {name: key for name, key in routes.items() if name not in ambiguous}


class PartRoutingSource:
    """Splits every packet by signal prefix so each part's readings go out under the part's own
    graph key — the telemetry resolver matches `device_id` against `external_ref`, and a sweep
    keyed by the device alone resolves to nothing. Signals no bound part claims keep the
    device's key; `seq` and `timestamp` are shared by the pieces of one sweep."""

    def __init__(self, inner: PacketSource, routes: Mapping[str, str]) -> None:
        self._inner = inner
        self._routes = dict(routes)

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        async for packet in self._inner:
            groups: dict[str, list[str]] = {}
            for name in packet.values:
                key = self._routes.get(name) or self._routes.get(
                    name.split(".", 1)[0], packet.device_id
                )
                groups.setdefault(key, []).append(name)
            for key, names in groups.items():
                yield packet.model_copy(
                    update={
                        "device_id": key,
                        "values": {n: packet.values[n] for n in names},
                        "units": {n: packet.units[n] for n in names if n in packet.units},
                    }
                )

    async def aclose(self) -> None:
        await self._inner.aclose()


def _bindings(config: HardwareConfig) -> tuple[TransportBinding, ProtocolBinding]:
    if config.identity is None or config.protocol is None:
        raise ValueError("the robot's config needs an identity and a protocol before it can open")
    return config.identity, config.protocol


def build_source_factory(
    config: HardwareConfig, *, transports: TransportRegistry, drivers: DriverRegistry
) -> Callable[[], PacketSource]:
    """A factory the reconnect loop calls per incarnation; each call re-opens by identity."""
    identity, protocol = _bindings(config)
    drivers.validate_params(protocol)  # bad parameters fail before any port is touched
    params = dict(protocol.params)

    def factory() -> PacketSource:
        channel = transports.open(identity, params)
        try:
            return drivers.open_source(config, channel)
        except Exception:
            channel.close()
            raise

    return factory


def open_robot_connection(
    config: HardwareConfig,
    *,
    project_id: UUID | None,
    transports: TransportRegistry,
    drivers: DriverRegistry,
    observers: Sequence[Observer] = (),
    on_event: EventSink | None = None,
    reconnect: bool = True,
) -> RobotConnection:
    """Open eagerly (an absent device fails at the call site, not inside the reconnect loop).
    Blocking; callers run it off-loop."""
    identity, protocol = _bindings(config)
    factory = build_source_factory(config, transports=transports, drivers=drivers)
    transports.open(identity, dict(protocol.params)).close()
    source: PacketSource = ReconnectingSource(factory) if reconnect else factory()
    routes = part_routes(config)
    if routes:
        source = PartRoutingSource(source, routes)
    return RobotConnection(
        _observed(source, observers, on_event),
        project_id=project_id,
        device_facts={"device_ref": identity.device_ref, "driver_id": protocol.driver_id},
    )
