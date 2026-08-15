"""`PacketStreamLiveConnection` — the MCP-02 LiveConnection over any packet stream.

One pump, per-subscription event-time windowing (`WindowAggregator`), delivery of
completed `TelemetryWindowSummary` objects to registered callbacks. Every live
source in this lane — Foxglove bridge, MuJoCo/Gazebo sims, MCAP replay, serial —
is a `PacketSource` plugged into this class; the provider subclasses are thin.

Failure honesty (review-driven): a pump that dies — source exhausted, link error —
always drops `status()` to `DISCONNECTED`, and the next `subscribe` starts a fresh
pump instead of joining the corpse. Teardown (`unsubscribe`/`aclose`) flushes each
subscription's pending partial window to its callback before removal, because the
freshest samples are exactly what a disconnect diagnosis needs. One consumer's
broken callback never starves the others.

Tenant binding: `project_id` is carried on the connection (CLAUDE.md §7). No route
exists yet; the route that wires this MUST set it and ship the isolation tests
(LB-05) — a `None` here is a dev-bench connection, never a served one.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from solus_api.agent.interfaces import TelemetryWindow
from solus_api.connectors.live import BatchCallback, LiveConnection, LiveStatus
from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.windowing import WindowAggregator

logger = logging.getLogger(__name__)


class PacketSource(Protocol):
    """Anything that yields LB-06 packets and can be shut down."""

    def __aiter__(self) -> AsyncIterator[TelemetryPacket]: ...

    async def aclose(self) -> None: ...


class PacketStreamLiveConnection(LiveConnection):
    """Live subscription surface over a `PacketSource`; subclasses set `provider`."""

    def __init__(self, source: PacketSource, *, project_id: UUID | None = None) -> None:
        self._source = source
        self.project_id = project_id
        self._aggregators: dict[str, WindowAggregator] = {}
        self._callbacks: dict[str, BatchCallback] = {}
        self._status = LiveStatus.DISCONNECTED
        self._pump: asyncio.Task[None] | None = None
        self._closing = False

    async def subscribe(self, window: TelemetryWindow) -> str:
        handle = uuid.uuid4().hex
        self._aggregators[handle] = WindowAggregator(window)
        if self._pump is None or self._pump.done():
            self._pump = asyncio.create_task(self._run(), name=f"{self.provider}-live-pump")
        if self._status is LiveStatus.DISCONNECTED:
            self._status = LiveStatus.CONNECTED
        return handle

    def on_batch(self, handle: str, callback: BatchCallback) -> None:
        if handle not in self._aggregators:
            raise KeyError(handle)
        self._callbacks[handle] = callback

    async def unsubscribe(self, handle: str) -> None:
        aggregator = self._aggregators.pop(handle)  # KeyError on unknown, per the contract
        callback = self._callbacks.pop(handle, None)
        await self._deliver(handle, aggregator, callback)
        if not self._aggregators:
            self._status = LiveStatus.DISCONNECTED

    def status(self) -> LiveStatus:
        return self._status

    async def aclose(self) -> None:
        """Teardown: stop the pump, flush pending windows, close the source."""
        self._closing = True
        if self._pump is not None:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump
            self._pump = None
        for handle, aggregator in list(self._aggregators.items()):
            await self._deliver(handle, aggregator, self._callbacks.get(handle))
        await self._source.aclose()
        self._aggregators.clear()
        self._callbacks.clear()
        self._status = LiveStatus.DISCONNECTED
        self._closing = False

    async def _deliver(
        self, handle: str, aggregator: WindowAggregator, callback: BatchCallback | None
    ) -> None:
        """Flush `aggregator` and hand the partial window to `callback`, guarded."""
        summary = aggregator.flush()
        if summary is None or callback is None:
            return
        try:
            await callback(summary)
        except Exception:
            logger.exception("batch callback for %s failed during flush", handle)

    async def _run(self) -> None:
        try:
            async for packet in self._source:
                for handle, aggregator in list(self._aggregators.items()):
                    summary = aggregator.add(packet)
                    if summary is None:
                        continue
                    callback = self._callbacks.get(handle)
                    if callback is None:
                        continue  # a completed window before on_batch registered is dropped
                    try:
                        await callback(summary)
                    except Exception:
                        logger.exception("batch callback for %s failed; pump continues", handle)
                        continue
                    self._status = LiveStatus.STREAMING
        except Exception as exc:
            # Class name only: a connect error's message can embed the full URI.
            logger.error("%s pump died: %s", self.provider, type(exc).__name__)
        finally:
            if not self._closing:
                self._status = LiveStatus.DISCONNECTED
