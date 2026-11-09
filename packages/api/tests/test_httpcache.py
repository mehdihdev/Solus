"""SOLUSDEV-167: the cache store and single-flight primitives."""

from __future__ import annotations

import asyncio

import pytest
from solus_api.connectors.contracts import ConnectorError
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
        owner = await single_flight(store, "f", ttl_seconds=10)
        order.append("winner-start")
        await asyncio.sleep(0.15)
        order.append("winner-done")
        await release_flight(store, "f", owner)

    async def loser() -> None:
        await asyncio.sleep(0.02)  # arrive second
        owner = await single_flight(store, "f", ttl_seconds=10, wait_seconds=2.0)
        await release_flight(store, "f", owner)
        order.append("loser")

    await asyncio.gather(winner(), loser())

    assert order.index("winner-done") < order.index("loser"), order


async def test_single_flight_fails_closed_when_the_store_is_broken() -> None:
    """An unavailable claim cannot authorize a concurrent provider call."""

    class Broken:
        async def get(self, key: str) -> str | None:
            raise RuntimeError("down")

        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            raise RuntimeError("down")

        async def delete(self, key: str) -> None:
            raise RuntimeError("down")

        async def claim(self, key: str, ttl_seconds: int, owner: str = "1") -> bool:
            raise RuntimeError("down")

        async def release(self, key: str, owner: str) -> None:
            raise RuntimeError("down")

        async def renew(self, key: str, owner: str, ttl_seconds: int) -> bool:
            raise RuntimeError("down")

    with pytest.raises(ConnectorError) as caught:
        await single_flight(Broken(), "f", ttl_seconds=10)
    assert caught.value.code == "single_flight_unavailable"


class _HangingStore(InMemoryCacheStore):
    """A stalled Redis: every read, write and delete waits forever."""

    async def get(self, key: str) -> str | None:
        await asyncio.Event().wait()
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await asyncio.Event().wait()

    async def delete(self, key: str) -> None:
        await asyncio.Event().wait()


async def test_a_hanging_store_is_a_miss_for_the_turn_path_caches(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """M13: the project card and research caches bound every store await by the fan-out's
    timeout. A stalled store reads as a miss, a put or an invalidation is skipped, and each is one
    warning line — the SOL turn never hangs on its cache."""
    import uuid

    from solus_api.agent.project_card import ProjectCard, ProjectCardCache
    from solus_api.agent.research import ResearchCache, ResearchDigest, Source
    from solus_api.graph import graph_changed_fanout

    monkeypatch.setattr(graph_changed_fanout, "CALLBACK_TIMEOUT_SECONDS", 0.05)
    project_id = uuid.uuid4()
    card = ProjectCard(name="p", robots=(), sources=(), solus={}, subsections={})
    digest = ResearchDigest(sources=[Source(url="https://x.example", title="x", fetched=False)])
    cards, research = ProjectCardCache(_HangingStore()), ResearchCache(_HangingStore())

    async with asyncio.timeout(2):
        assert await cards.get(project_id) is None
        await cards.put(project_id, card)
        await cards.invalidate(project_id)
        assert await research.get(project_id, "q") is None
        await research.put(project_id, "q", digest)

    logged = [r.getMessage() for r in caplog.records]
    assert sum("timed out" in m or "TimeoutError" in m for m in logged) == 5, logged


class _DownStore(InMemoryCacheStore):
    """A store that refuses every call, as a Redis that went away does."""

    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis went away")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ConnectionError("redis went away")

    async def delete(self, key: str) -> None:
        raise ConnectionError("redis went away")


async def test_a_down_store_is_a_miss_for_the_card_cache_as_for_research(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Round 2, new issue 8: the card cache treats ANY store error as a miss or a skipped write,
    the way `ResearchCache` does — never a failed turn — with one warning naming the cache."""
    import uuid

    from solus_api.agent.project_card import ProjectCard, ProjectCardCache

    cards, project_id = ProjectCardCache(_DownStore()), uuid.uuid4()
    card = ProjectCard(name="p", robots=(), sources=(), solus={}, subsections={})

    assert await cards.get(project_id) is None
    await cards.put(project_id, card)
    await cards.invalidate(project_id)

    logged = [r.getMessage() for r in caplog.records]
    assert sum("project card" in m and "ConnectionError" in m for m in logged) == 3, logged
