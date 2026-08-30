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

    def _is_closed(self) -> bool:
        # A method, not a bare attribute read: `aclose` flips the flag from another
        # task across a yield, which mypy's reachability narrowing cannot model.
        return self._closed

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        backoff = self._start
        while not self._is_closed():
            # Off-loop: a serial factory blocks in `pyserial.Serial(...)`, and a
            # wedged USB open must never stall the event loop (SOLUSDEV-72).
            source = await asyncio.to_thread(self._factory)
            self._current = source
            try:
                async for packet in source:
                    backoff = self._start  # a live link resets the schedule
                    yield packet
                    if self._is_closed():
                        return
            except Exception as exc:
                logger.warning("link dropped: %s; reconnecting", type(exc).__name__)
            finally:
                self._current = None
                await source.aclose()
            if self._is_closed():
                return
            await self._sleep(backoff)
            backoff = min(backoff * 2, self._cap)

    async def aclose(self) -> None:
        self._closed = True
        if self._current is not None:
            await self._current.aclose()
