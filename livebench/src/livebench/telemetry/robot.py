"""Robot `LiveConnection`s (LB-02): serial and WS transports composed with
reconnect/backoff and edge observers into the MCP-02 seam.

Composition order matters and is fixed here: transport → `ReconnectingSource`
(the link heals) → `ObservingSource` (observers see the HEALED stream, so a
reconnect gap is visible to the gap watchdog, not hidden by it) → windowing in
`PacketStreamLiveConnection`.

`SerialRobotConnection.open` opens the device eagerly — a nonexistent port fails
at the call site, not silently inside the reconnect loop. Reconnect then re-opens
the same device on link loss (USB re-enumeration keeps stable paths via
/dev/serial/by-id, which is what callers should pass).
"""

from collections.abc import Sequence
from typing import ClassVar
from uuid import UUID

import serial as pyserial

from livebench.telemetry.observing_source import EventSink, Observer, ObservingSource
from livebench.telemetry.reconnect import ReconnectingSource
from livebench.telemetry.serial_source import SerialPacketSource
from livebench.telemetry.stream_live import PacketSource, PacketStreamLiveConnection
from livebench.telemetry.ws_source import WsPacketSource

_DEFAULT_BAUD = 115200
_DEFAULT_TIMEOUT_S = 1.0


def _observed(
    source: PacketSource, observers: Sequence[Observer], on_event: EventSink | None
) -> PacketSource:
    if not observers or on_event is None:
        return source
    return ObservingSource(source, observers=observers, on_event=on_event)


class SerialRobotConnection(PacketStreamLiveConnection):
    """A robot on a serial link, streaming LB-06 JSON lines."""

    provider: ClassVar[str] = "serial"

    @classmethod
    def open(
        cls,
        device: str,
        baud: int = _DEFAULT_BAUD,
        *,
        observers: Sequence[Observer] = (),
        on_event: EventSink | None = None,
        project_id: UUID | None = None,
    ) -> "SerialRobotConnection":
        pyserial.Serial(device, baud, timeout=_DEFAULT_TIMEOUT_S).close()  # fail fast

        def factory() -> PacketSource:
            return SerialPacketSource(pyserial.Serial(device, baud, timeout=_DEFAULT_TIMEOUT_S))

        source = _observed(ReconnectingSource(factory), observers, on_event)
        return cls(source=source, project_id=project_id)


class WsRobotConnection(PacketStreamLiveConnection):
    """A robot over wifi/direct, pushing LB-06 frames on its own WebSocket."""

    provider: ClassVar[str] = "robot-ws"

    @classmethod
    def open(
        cls,
        url: str,
        *,
        observers: Sequence[Observer] = (),
        on_event: EventSink | None = None,
        project_id: UUID | None = None,
    ) -> "WsRobotConnection":
        WsPacketSource(url)  # validate the URL at the call site, not in the loop

        def factory() -> PacketSource:
            return WsPacketSource(url)

        source = _observed(ReconnectingSource(factory), observers, on_event)
        return cls(source=source, project_id=project_id)
