"""SOLUSDEV-241: the integration cache — fetch-through, signals, key hygiene."""

from __future__ import annotations

import asyncio

from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache


class _Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


def _cache(clock: _Clock | None = None, **kwargs: int) -> tuple[IntegrationCache, _Clock]:
    clock = clock or _Clock()
    store = InMemoryCacheStore(clock=clock)
    return IntegrationCache(store, clock=clock, **kwargs), clock


async def test_fetch_pays_once_then_serves_from_cache() -> None:
    cache, _ = _cache()
    calls = 0

    async def fetch() -> list[str]:
        nonlocal calls
        calls += 1
        return ["dA", "dB"]

    first = await cache.fetch("k", ttl_seconds=60, fetch=fetch)
    second = await cache.fetch("k", ttl_seconds=60, fetch=fetch)

    assert first.cached is False and second.cached is True
    assert second.value == ["dA", "dB"]
    assert second.fetched_at == first.fetched_at
    assert calls == 1


async def test_refresh_pays_again_and_replaces_the_entry() -> None:
    cache, clock = _cache()
    values = iter([["old"], ["new"]])

    async def fetch() -> list[str]:
        return next(values)

    await cache.fetch("k", ttl_seconds=60, fetch=fetch)
    clock.now += 5
    refreshed = await cache.fetch("k", ttl_seconds=60, fetch=fetch, refresh=True)
    assert refreshed.cached is False and refreshed.value == ["new"]
    served = await cache.fetch("k", ttl_seconds=60, fetch=fetch)
    assert served.cached is True and served.value == ["new"]
    assert served.fetched_at == refreshed.fetched_at


async def test_an_entry_expires_at_its_ttl() -> None:
    cache, clock = _cache()
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        return calls

    await cache.fetch("k", ttl_seconds=10, fetch=fetch)
    clock.now += 11
    again = await cache.fetch("k", ttl_seconds=10, fetch=fetch)
    assert again.cached is False and again.value == 2


async def test_concurrent_misses_collapse_to_one_fetch() -> None:
    cache, _ = _cache()
    calls = 0
    gate = asyncio.Event()

    async def fetch() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        return "v"

    tasks = [asyncio.create_task(cache.fetch("k", ttl_seconds=60, fetch=fetch)) for _ in range(8)]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert calls == 1
    assert sum(1 for r in results if not r.cached) == 1
    assert all(r.value == "v" for r in results)


async def test_oversize_payloads_are_used_but_not_kept() -> None:
    cache, _ = _cache(max_payload_bytes=32)
    calls = 0

    async def fetch() -> str:
        nonlocal calls
        calls += 1
        return "x" * 100

    first = await cache.fetch("k", ttl_seconds=60, fetch=fetch)
    second = await cache.fetch("k", ttl_seconds=60, fetch=fetch)
    assert first.value == second.value
    assert second.cached is False
    assert calls == 2


async def test_signal_is_trusted_only_within_the_readers_window() -> None:
    cache, clock = _cache()
    await cache.record_signal("s", {"version": "mv1"})

    assert (await cache.signal("s", max_age_seconds=3600)) == {
        "version": "mv1",
        "observed_at": clock.now,
    }
    clock.now += 400
    assert await cache.signal("s", max_age_seconds=300) is None, "the sweep window is short"
    assert (await cache.signal("s", max_age_seconds=3600)) is not None, "a human's is long"
    assert await cache.signal("s", max_age_seconds=None) is None, "a webhook never trusts"


async def test_keys_carry_the_account_and_quote_provider_ids() -> None:
    account = IntegrationCache.account_key("onshape", "acct/1")
    assert account == "solus:icache:onshape:acct%2F1"
    assert IntegrationCache.listing_key("onshape", "acct/1") == f"{account}:listing"
    assert IntegrationCache.signal_key("onshape", "acct/1", "d:1") == f"{account}:signal:d%3A1"
    assert (
        IntegrationCache.payload_key("onshape", "acct/1", "dA", "mv1", "export", "e1")
        == f"{account}:export:dA:mv1:e1"
    )
    # Two accounts never share an entry, whatever their document ids.
    assert IntegrationCache.signal_key("onshape", "a", "d") != IntegrationCache.signal_key(
        "onshape", "b", "d"
    )


async def test_malformed_entries_read_as_misses() -> None:
    clock = _Clock()
    store = InMemoryCacheStore(clock=clock)
    cache = IntegrationCache(store, clock=clock)
    await store.set("k", "{not json", 60)
    assert await cache.get("k") is None
    assert await store.get("k") is None, "the bad entry is dropped, not re-served"


async def test_refresh_inside_the_cooldown_is_served_from_the_cache() -> None:
    cache, clock = _cache()
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        return calls

    await cache.fetch("k", ttl_seconds=600, fetch=fetch)
    clock.now += 10
    held = await cache.fetch("k", ttl_seconds=600, fetch=fetch, refresh=True, min_age_seconds=60)
    assert held.cached is True and calls == 1
    clock.now += 61
    walked = await cache.fetch("k", ttl_seconds=600, fetch=fetch, refresh=True, min_age_seconds=60)
    assert walked.cached is False and calls == 2


async def test_invalidate_account_drops_every_entry_for_that_account_only() -> None:
    cache, _ = _cache()

    async def fetch() -> str:
        return "v"

    listing = IntegrationCache.listing_key("onshape", "acct-1")
    export = IntegrationCache.payload_key("onshape", "acct-1", "dA", "mv1", "export", "e1")
    other = IntegrationCache.listing_key("onshape", "acct-2")
    for key in (listing, export, other):
        await cache.fetch(key, ttl_seconds=600, fetch=fetch)
    await cache.record_signal(IntegrationCache.signal_key("onshape", "acct-1", "dA"), {"v": 1})

    removed = await cache.invalidate_account("onshape", "acct-1")

    assert removed == 3
    assert await cache.get(listing) is None
    assert await cache.get(export) is None
    assert await cache.get(IntegrationCache.signal_key("onshape", "acct-1", "dA")) is None
    assert await cache.get(other) is not None, "another account's entries are untouched"


async def test_oversize_text_is_refused_before_it_is_encoded() -> None:
    cache, _ = _cache(max_payload_bytes=8)
    assert await cache.put("k", "x" * 9, 60) is False
    assert await cache.get("k") is None
