"""Reconnect-with-backoff wrapper for packet sources (LB-02).

A robot link drops: wifi hiccups, USB re-enumerates, the bridge restarts. This
wrapper turns a source FACTORY into one continuous stream — when an incarnation
ends or raises, it is closed, the wrapper naps (exponential backoff, capped) and
opens a fresh one. A delivered packet resets the schedule, so a healthy link that
blips reconnects fast while a dead one settles at the cap instead of hammering.

The sleeper is injectable so tests drive the schedule deterministically.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Final

from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.stream_live import PacketSource

logger = logging.getLogger(__name__)

DEFAULT_BACKOFF_START: Final = 0.5
DEFAULT_BACKOFF_CAP: Final = 30.0


class ReconnectingSource:
    """One continuous packet stream over successive incarnations of a source."""

    def __init__(
        self,
        factory: Callable[[], PacketSource],
        *,
        backoff_start: float = DEFAULT_BACKOFF_START,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if backoff_start <= 0 or backoff_cap < backoff_start:
            raise ValueError("backoff_start must be positive and <= backoff_cap")
        self._factory = factory
        self._start = backoff_start
        self._cap = backoff_cap
        self._sleep = sleep
        self._closed = False
        self._current: PacketSource | None = None
        self._opening: asyncio.Task[PacketSource | None] | None = None
        self._stop = asyncio.Event()

    async def _open(self) -> PacketSource | None:
        try:
            # Shielded by the caller: cancelling a thread await cannot stop a
            # blocking USB open. Retain ownership until its result is cleaned up.
            source = await asyncio.to_thread(self._factory)
            self._current = source
            if self._is_closed():
                await self._close_current()
                return None
            return source
        except Exception as exc:
            logger.warning("link open failed: %s; reconnecting", type(exc).__name__)
            return None

    async def _close_current(self) -> None:
        source, self._current = self._current, None
        if source is not None:
            await source.aclose()

    async def _backoff(self, seconds: float) -> None:
        nap = asyncio.ensure_future(self._sleep(seconds))
        stopped = asyncio.create_task(self._stop.wait())
        try:
            await asyncio.wait((nap, stopped), return_when=asyncio.FIRST_COMPLETED)
            if nap.done():
                await nap
        finally:
            nap.cancel()
            stopped.cancel()
            await asyncio.gather(nap, stopped, return_exceptions=True)

    def _is_closed(self) -> bool:
        # A method, not a bare attribute read: `aclose` flips the flag from another
        # task across a yield, which mypy's reachability narrowing cannot model.
        return self._closed

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        backoff = self._start
        while not self._is_closed():
            # Off-loop: a serial factory blocks in `pyserial.Serial(...)`, and a
            # wedged USB open must never stall the event loop (SOLUSDEV-72).
            try:
                self._opening = asyncio.create_task(self._open())
                source = await asyncio.shield(self._opening)
                if source is not None:
                    async for packet in source:
                        if self._is_closed():
                            return
                        backoff = self._start  # a live link resets the schedule
                        yield packet
                        if self._is_closed():
                            return
            except asyncio.CancelledError:
                self._closed = True
                self._stop.set()
                raise
            except Exception as exc:
                logger.warning("link dropped: %s; reconnecting", type(exc).__name__)
            finally:
                await self._close_current()
            if self._is_closed():
                return
            await self._backoff(backoff)
            backoff = min(backoff * 2, self._cap)

    async def aclose(self) -> None:
        self._closed = True
        self._stop.set()
        await self._close_current()
