"""SOLUSDEV-167: the cache store and single-flight primitives."""

from __future__ import annotations

import asyncio

from solus_api.connectors.httpcache import (
    InMemoryCacheStore,
    release_flight,
    single_flight,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_a_value_expires_at_its_ttl() -> None:
    clock = _Clock()
    store = InMemoryCacheStore(clock=clock)
    await store.set("k", "v", 10)

    assert await store.get("k") == "v"
    clock.now += 11
    assert await store.get("k") is None


async def test_claim_is_exclusive_until_released() -> None:
    store = InMemoryCacheStore()

    assert await store.claim("k", 10) is True
    assert await store.claim("k", 10) is False
    await store.delete("k")
    assert await store.claim("k", 10) is True


async def test_concurrent_claims_yield_exactly_one_winner() -> None:
    """The lock inside `claim` is what makes this atomic. Without it two
    coroutines can both observe "free" between the read and the write, and
    single-flight silently becomes double-flight — a bug no call-count test
    would notice, because it only shows up under real concurrency."""
    store = InMemoryCacheStore()

    results = await asyncio.gather(*[store.claim("k", 10) for _ in range(50)])

    assert sum(results) == 1, f"{sum(results)} callers won one claim"


async def test_losers_wait_for_the_winner_then_proceed() -> None:
    """A loser does not get the winner's VALUE — an export is not something that
    can be handed over. It gets to run AFTER, when its own pass is cheap."""
    store = InMemoryCacheStore()
    order: list[str] = []

    async def winner() -> None:
        assert await single_flight(store, "f", ttl_seconds=10) is True
        order.append("winner-start")
        await asyncio.sleep(0.15)
        order.append("winner-done")
        await release_flight(store, "f")

    async def loser() -> None:
        await asyncio.sleep(0.02)  # arrive second
        assert await single_flight(store, "f", ttl_seconds=10, wait_seconds=2.0) is True
        order.append("loser")

    await asyncio.gather(winner(), loser())

    assert order.index("winner-done") < order.index("loser"), order


async def test_single_flight_fails_open_when_the_store_is_broken() -> None:
    """A broken cache must never stop work happening — the same fail-open policy
    the model-call rate limiter documents."""

    class Broken:
        async def get(self, key: str) -> str | None:
            raise RuntimeError("down")

        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            raise RuntimeError("down")

        async def delete(self, key: str) -> None:
            raise RuntimeError("down")

        async def claim(self, key: str, ttl_seconds: int) -> bool:
            raise RuntimeError("down")

    assert await single_flight(Broken(), "f", ttl_seconds=10) is True
