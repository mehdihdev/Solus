"""Redis-backed artifact upload budgets (SOLUSDEV-100 Phase 4 M2 follow-up) and the
dedicated `FixedWindowLimiter` stale-eviction unit test."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from solus_api.services.artifacts import FixedWindowLimiter
from solus_api.services.upload_budget import UploadBudget


class FakeRedis:
    """Minimal INCRBY/EXPIRE double; `fail` simulates an outage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.fail = fail

    async def incrby(self, key: str, amount: int) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    async def set(self, key: str, value: int, *, ex: int, nx: bool) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        if nx and key in self.counts:
            return False
        self.counts[key] = value
        self.ttls[key] = ex
        return True


# ----------------------------------------------------- limiter eviction (follow-up)


def test_fixed_window_limiter_evicts_counters_from_past_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"t": 1_000.0}
    monkeypatch.setattr("solus_api.services.artifacts.time.time", lambda: now["t"])
    limiter = FixedWindowLimiter(window_seconds=60)
    for i in range(50):
        limiter.bump(f"user-{i}")
    assert len(limiter._counters) == 50

    now["t"] += 61  # next window
    assert limiter.bump("fresh") == 1
    assert set(limiter._counters) == {"fresh"}, "stale keys must not survive a window roll"


def test_fixed_window_limiter_resets_a_returning_key_after_window_roll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"t": 1_000.0}
    monkeypatch.setattr("solus_api.services.artifacts.time.time", lambda: now["t"])
    limiter = FixedWindowLimiter(window_seconds=60)
    assert limiter.bump("u", 5) == 5
    assert limiter.bump("u") == 6
    now["t"] += 60
    assert limiter.bump("u") == 1


# ------------------------------------------------------------------ UploadBudget


async def test_budget_counts_in_redis_shared_across_instances() -> None:
    redis = FakeRedis()
    a = UploadBudget("req", window_seconds=60, redis=redis)
    b = UploadBudget("req", window_seconds=60, redis=redis)  # a second API instance
    assert await a.bump("u1") == 1
    assert await b.bump("u1") == 2, "the budget is aggregate, not limit x instances"
    assert await b.bump("u2", 10) == 10
    assert redis.ttls and set(redis.ttls.values()) == {120}, "every window key expires"


async def test_budget_keys_are_namespaced_per_budget_name() -> None:
    redis = FakeRedis()
    await UploadBudget("req", 60, redis=redis).bump("k")
    await UploadBudget("bytes", 60, redis=redis).bump("k", 7)
    assert len(redis.counts) == 2


async def test_budget_falls_back_to_memory_when_redis_raises() -> None:
    budget = UploadBudget("req", window_seconds=60, redis=FakeRedis(fail=True))
    assert await budget.bump("u") == 1
    assert await budget.bump("u") == 2, "outage degrades to the per-process counter, never open"


async def test_budget_without_redis_uses_memory() -> None:
    budget = UploadBudget("req", window_seconds=60, redis=None)
    assert await budget.bump("u", 3) == 3


async def test_budget_recovers_to_redis_after_outage() -> None:
    redis: Any = FakeRedis(fail=True)
    budget = UploadBudget("req", window_seconds=60, redis=redis)
    await budget.bump("u")
    redis.fail = False
    assert await budget.bump("u") == 1, "redis counter starts fresh once reachable"


class _HungRedis:
    async def set(self, name: str, value: int, *, ex: int, nx: bool) -> bool:
        await asyncio.Event().wait()
        return True

    async def incrby(self, name: str, amount: int) -> int:
        return 0


async def test_budget_falls_back_when_redis_hangs() -> None:
    budget = UploadBudget("hang", 60, _HungRedis())
    total = await asyncio.wait_for(budget.bump("k"), timeout=5)
    assert total == 1


class _IncrFailsRedis(FakeRedis):
    async def incrby(self, key: str, amount: int) -> int:
        raise ConnectionError("incrby failed")


async def test_failure_after_ttl_set_never_leaves_a_ttl_less_key() -> None:
    redis = _IncrFailsRedis()
    budget = UploadBudget("atomic", 60, redis)
    await budget.bump("k")
    assert redis.counts and set(redis.counts) == set(redis.ttls)
