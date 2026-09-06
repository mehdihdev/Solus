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

The account/version payload cache lives in `integration_cache.py`. Account
identity must be in every resource key: project and source IDs alone cannot
identify the provider grant, and project-independent keys let the same account
reuse its exports across projects. Source attachment never silently changes
an existing source to a different account.

"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from solus_api.connectors.contracts import ConnectorError

logger = logging.getLogger("solus.connectors.httpcache")

_KEY_PREFIX = "solus:ic"

#: Waiters must acquire their own lease after the winner. A bounded wait
#: defers work rather than authorizing an unclaimed concurrent fetch.
_FLIGHT_POLL_SECONDS = 0.05
_FLIGHT_WAIT_SECONDS = 30.0
_FLIGHT_RELEASE_SECONDS = 1.0


class CacheStore(Protocol):
    """The narrow slice both backends implement. Structural, so
    `redis.asyncio.Redis` satisfies the read/write half as-is."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def release(self, key: str, owner: str) -> None: ...

    async def renew(self, key: str, owner: str, ttl_seconds: int) -> bool: ...

    async def claim(self, key: str, ttl_seconds: int, owner: str = "1") -> bool:
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

    async def claim(self, key: str, ttl_seconds: int, owner: str = "1") -> bool:
        # The lock is what makes this atomic. Without it two coroutines can both
        # observe "free" between the read and the write, and single-flight
        # silently becomes double-flight — the exact bug this class exists to
        # prevent, and one no test would notice.
        async with self._lock:
            if self._live(key) is not None:
                return False
            self._values[key] = (self._clock() + ttl_seconds, owner)
            return True

    async def release(self, key: str, owner: str) -> None:
        async with self._lock:
            if self._live(key) == owner:
                self._values.pop(key, None)

    async def renew(self, key: str, owner: str, ttl_seconds: int) -> bool:
        async with self._lock:
            if self._live(key) != owner:
                return False
            self._values[key] = (self._clock() + ttl_seconds, owner)
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

    async def claim(self, key: str, ttl_seconds: int, owner: str = "1") -> bool:
        return bool(await self._redis.set(key, owner, nx=True, ex=ttl_seconds))

    async def release(self, key: str, owner: str) -> None:
        # Compare/delete is atomic: an expired owner's cleanup cannot remove a
        # successor's lease. This fixed script never executes provider input.
        await self._redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            key,
            owner,
        )

    async def renew(self, key: str, owner: str, ttl_seconds: int) -> bool:
        return bool(
            await self._redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
                1,
                key,
                owner,
                ttl_seconds,
            )
        )


async def single_flight(
    store: CacheStore,
    key: str,
    *,
    ttl_seconds: int,
    wait_seconds: float | None = _FLIGHT_WAIT_SECONDS,
) -> str:
    """Acquire an owned lease before proceeding; unavailable/busy fails closed.

    Every waiter must atomically claim the released key itself. A timeout or
    cache outage is not permission to export concurrently.
    """
    owner = uuid.uuid4().hex
    deadline = time.monotonic() + wait_seconds if wait_seconds is not None else None
    while True:
        try:
            if await store.claim(key, ttl_seconds, owner):
                return owner
        except Exception as exc:
            logger.warning("single-flight claim unavailable")
            raise ConnectorError(
                "single_flight_unavailable",
                "Synchronization is temporarily unavailable; retry later",
            ) from exc
        if deadline is not None and time.monotonic() >= deadline:
            raise ConnectorError(
                "single_flight_busy", "Synchronization is already running; retry later"
            )
        await asyncio.sleep(_FLIGHT_POLL_SECONDS)


async def release_flight(store: CacheStore, key: str, owner: str) -> None:
    try:
        async with asyncio.timeout(_FLIGHT_RELEASE_SECONDS):
            await store.release(key, owner)
    except Exception:  # noqa: BLE001 — the TTL is the backstop
        logger.warning("could not release single-flight claim")


async def run_in_flight[T](
    store: CacheStore,
    key: str,
    owner: str,
    *,
    ttl_seconds: int,
    run: Callable[[], Awaitable[T]],
) -> T:
    """Renew ownership during work; cancel and await the work if ownership is lost.

    Renewal itself is bounded to TTL/3. An unavailable store therefore cancels
    work before the last confirmed lease expires, instead of silently leaving
    a still-running provider request behind an expired lock.
    """
    interval = ttl_seconds / 3

    async def renew() -> None:
        try:
            async with asyncio.timeout(interval):
                if await store.renew(key, owner, ttl_seconds):
                    return
        except Exception as exc:
            raise ConnectorError(
                "single_flight_lost", "Synchronization ownership was lost; retry later"
            ) from exc
        raise ConnectorError(
            "single_flight_lost", "Synchronization ownership was lost; retry later"
        )

    async def maintain() -> None:
        while True:
            await asyncio.sleep(interval)
            await renew()

    await renew()
    work = asyncio.ensure_future(run())
    renewal = asyncio.create_task(maintain())
    try:
        done, _ = await asyncio.wait((work, renewal), return_when=asyncio.FIRST_COMPLETED)
        if renewal in done:
            await renewal  # raises before the work's result can be used
        return await work
    finally:
        work.cancel()
        renewal.cancel()
        await asyncio.gather(work, renewal, return_exceptions=True)
