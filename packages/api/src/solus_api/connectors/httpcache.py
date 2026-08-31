"""Shared cache + single-flight for integration calls (SOLUSDEV-167).

Onshape's quota is ANNUAL — 2,500 calls per user per year, only 2xx/3xx counted.
That is 6.8 calls a day, so the cheapest call is the one never made. Two
mechanisms here do almost all of the saving:

**Single-flight.** N concurrent askers for one resource collapse to one upstream
call. Built on a `SET NX EX` claim rather than per-key futures because the same
primitive has to work across PROCESSES (the API and the ARQ worker are separate,
and in production several API tasks): an in-process future would coalesce one
worker's callers and let the other N-1 through.

**A shared store** for both, mirroring the repo's Redis-optional convention (see
`graph/buffer.py`): a narrow Protocol, an in-memory backend for dev and tests, a
Redis backend when one is configured, chosen once at app assembly.

**If a RESPONSE cache is ever added here** (it is not needed for sync — the
freshness gate and single-flight already collapse that path — but the SOL agent's
Onshape tools are still uncached), its keys must carry BOTH identity segments,
and neither is optional:

  * `team_id` alone would be wrong: one team can hold two projects with two
    Onshape sources connected by two DIFFERENT accounts.
  * `source_id` alone would also be wrong: a reconnect deliberately reuses the
    same Source row to switch account (`routers/integrations.py::_reusable_source`
    — "which doubles as switch account"), so one row carries different provider
    identities over time.

Put the resource's change token in the key too, and a change makes every derived
key unreachable by construction — partial invalidation with no invalidation code.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

logger = logging.getLogger("solus.connectors.httpcache")

_KEY_PREFIX = "solus:ic"

#: How long a losing single-flight caller waits for the winner's value before
#: giving up and fetching itself. Bounded so a winner that dies mid-flight
#: cannot park every other caller until its claim expires.
_FLIGHT_POLL_SECONDS = 0.05
_FLIGHT_WAIT_SECONDS = 30.0


class CacheStore(Protocol):
    """The narrow slice both backends implement. Structural, so
    `redis.asyncio.Redis` satisfies the read/write half as-is."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        """Atomically take `key` if free. True = you own it (SET NX EX)."""
        ...


class InMemoryCacheStore:
    """Dev and test backend. Per-process, so it coalesces callers inside ONE
    process only — which is exactly what the Redis backend exists to fix."""

    def __init__(self, *, clock: Any = time.monotonic) -> None:
        self._clock = clock
        self._values: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    def _live(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._values[key]
            return None
        return value

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._values[key] = (self._clock() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        # The lock is what makes this atomic. Without it two coroutines can both
        # observe "free" between the read and the write, and single-flight
        # silently becomes double-flight — the exact bug this class exists to
        # prevent, and one no test would notice.
        async with self._lock:
            if self._live(key) is not None:
                return False
            self._values[key] = (self._clock() + ttl_seconds, "1")
            return True


class RedisCacheStore:
    """Shared across processes AND users — the multiplier. Two engineers on one
    Onshape document cost one fetch, not two."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self._redis.set(key, "1", nx=True, ex=ttl_seconds))


async def single_flight(
    store: CacheStore,
    key: str,
    *,
    ttl_seconds: int,
    wait_seconds: float = _FLIGHT_WAIT_SECONDS,
) -> bool:
    """Take the flight for `key`, or wait for whoever has it.

    Returns True if the caller should do the work. A loser waits for the winner
    to finish and then returns True as well — it does NOT return a value, because
    what the winner produced (a graph write, an export) is not always something
    that can be handed over. The point is that the losers do their (now cheap)
    pass AFTER the expensive one has landed, not simultaneously with it.

    Falls through to True on a store error: a broken cache must never stop work
    happening (the same fail-open policy the rate limiter documents).
    """
    try:
        if await store.claim(key, ttl_seconds):
            return True
    except Exception:  # noqa: BLE001 — a broken store must not block the caller
        logger.warning("single-flight claim failed for %s; proceeding unclaimed", key)
        return True

    waited = 0.0
    while waited < wait_seconds:
        await asyncio.sleep(_FLIGHT_POLL_SECONDS)
        waited += _FLIGHT_POLL_SECONDS
        try:
            if await store.get(key) is None:
                return True  # the winner finished (or died); carry on
        except Exception:  # noqa: BLE001
            return True
    return True


async def release_flight(store: CacheStore, key: str) -> None:
    try:
        await store.delete(key)
    except Exception:  # noqa: BLE001 — the TTL is the backstop
        logger.warning("could not release single-flight claim %s", key)
