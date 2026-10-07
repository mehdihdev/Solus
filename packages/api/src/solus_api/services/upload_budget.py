"""Shared fixed-window upload budgets (SOLUSDEV-100 Phase 4 M2 follow-up).

`FixedWindowLimiter` is per-process, so on N API instances a budget of L really
admits `L * N`. `UploadBudget` counts in Redis (INCRBY on a window-stamped key) so the
budget is aggregate, and degrades to a per-process `FixedWindowLimiter` whenever Redis is
unconfigured, errors, or stalls past a short timeout. During a Redis outage the budget is
per-instance again and counts restart from zero, so a flap can admit up to about twice the
limit in that window; it never fails the upload request. Windows use wall-clock time, so
instances with skewed clocks may disagree on window boundaries."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from solus_api.services.artifacts import FixedWindowLimiter

logger = logging.getLogger("solus.artifacts.budget")

_KEY_PREFIX = "solus:upload-budget"
#: Keys carry their window index, so a TTL of two windows is always enough.
_TTL_WINDOWS = 2
#: A Redis that accepts the connection but never answers must not stall uploads.
_REDIS_CALL_TIMEOUT_SECONDS = 0.25


class BudgetRedis(Protocol):
    async def incrby(self, name: str, amount: int) -> int: ...
    async def set(self, name: str, value: int, *, ex: int, nx: bool) -> object: ...


class UploadBudget:
    def __init__(self, name: str, window_seconds: int, redis: BudgetRedis | None) -> None:
        self._name = name
        self._window_seconds = window_seconds
        self._redis = redis
        self._fallback = FixedWindowLimiter(window_seconds=window_seconds)

    async def bump(self, key: str, amount: int = 1) -> int:
        """Add `amount` to `key`'s current-window total and return the new total."""
        if self._redis is None:
            return self._fallback.bump(key, amount)
        window = int(time.time()) // self._window_seconds
        redis_key = f"{_KEY_PREFIX}:{self._name}:{window}:{key}"
        try:
            async with asyncio.timeout(_REDIS_CALL_TIMEOUT_SECONDS):
                # TTL first (NX): a failure between the two calls can then never leave a
                # counter without an expiry. INCRBY preserves the TTL.
                await self._redis.set(redis_key, 0, ex=self._window_seconds * _TTL_WINDOWS, nx=True)
                total = await self._redis.incrby(redis_key, amount)
        except Exception as exc:  # noqa: BLE001 — any Redis fault degrades, never fails the upload
            logger.warning(
                "upload budget %s: redis unavailable (%s), per-process fallback",
                self._name,
                type(exc).__name__,
            )
            return self._fallback.bump(key, amount)
        return total
