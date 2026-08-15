"""Edge observers riding a packet stream (LB-02).

Wraps any `PacketSource`: packets pass through UNTOUCHED (observation never
mutates or drops telemetry) while each observer sees every packet and its events
go out the side to `on_event` — the seam the error path (ERR-01) and the Live
Bench anomaly markers consume. This is the "close to the data" placement: events
fire per packet, before windowing can smear them.

A broken event sink is logged and skipped; the stream survives (§7).
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Protocol

from solus_api.graph.packet import TelemetryPacket

from livebench.anomaly.observers import ObserverEvent
from livebench.telemetry.stream_live import PacketSource

logger = logging.getLogger(__name__)

EventSink = Callable[[ObserverEvent], Awaitable[None]]


class Observer(Protocol):
    """A per-packet detector: LB-06 packet in, zero or more events out."""

    def add(self, packet: TelemetryPacket) -> list[ObserverEvent]: ...


class ObservingSource:
    """Pass-through source that runs observers beside the stream."""

    def __init__(
        self, inner: PacketSource, *, observers: Sequence[Observer], on_event: EventSink
    ) -> None:
        self._inner = inner
        self._observers = list(observers)
        self._on_event = on_event

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        async for packet in self._inner:
            for observer in self._observers:
                for event in observer.add(packet):
                    try:
                        await self._on_event(event)
                    except Exception:
                        logger.exception("observer event sink failed; stream continues")
            yield packet

    async def aclose(self) -> None:
        await self._inner.aclose()
