"""ADR-038 §1 Phase 4 fixes: what reaches the durable store, reclamation, tombstone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.storage.cad_store import LocalCadStore

KIB = 1024
MIB = KIB * 1024
BIG = "x" * (300 * KIB)  # above the 256 KiB durable threshold
SMALL = "y" * (10 * KIB)


def _setup(tmp_path: Path) -> tuple[IntegrationCache, InMemoryCacheStore, LocalCadStore]:
    redis = InMemoryCacheStore()
    cad = LocalCadStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)
    return IntegrationCache(redis, durable_store=cad), redis, cad


def _files(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "cad").rglob("*") if p.is_file()]


def _key(provider: str, kind: str, account: str = "acct", item: str = "doc1") -> str:
    return IntegrationCache.payload_key(provider, account, item, "mv1", kind, "e1")


async def _put(cache: IntegrationCache, key: str, value: Any) -> bool:
    return await cache.put(key, {"value": value, "fetched_at": "2026-01-01T00:00:00+00:00"}, 60)


async def test_non_onshape_payloads_never_reach_the_durable_store(tmp_path: Path) -> None:
    cache, redis, _ = _setup(tmp_path)
    for provider, kind in (
        ("github", "document-tree"),
        ("gitlab", "revision-v3-export"),
        ("kicad", "immutable-read-v1"),
    ):
        key = _key(provider, kind)
        assert await _put(cache, key, BIG)
        raw = await redis.get(key)
        assert raw is not None and "durable" not in raw
    assert _files(tmp_path) == []


async def test_small_onshape_payloads_and_cheap_kinds_stay_in_redis(tmp_path: Path) -> None:
    cache, redis, _ = _setup(tmp_path)
    for kind, value in (
        ("revision-v3-elements", BIG),  # cheap to recreate: never durable, whatever its size
        ("revision-v3-parts", SMALL),
        ("immutable-read-v1", SMALL),  # SOL read below the threshold
        ("sol-read-v1", SMALL),
        ("document-tree", BIG),
    ):
        key = _key("onshape", kind)
        assert await _put(cache, key, value)
        raw = await redis.get(key)
        assert raw is not None and "durable" not in raw, kind
    assert _files(tmp_path) == []


async def test_large_sol_reads_and_every_step_export_go_to_the_durable_store(
    tmp_path: Path,
) -> None:
    cache, redis, _ = _setup(tmp_path)
    for kind, value in (
        ("revision-v3-export", SMALL),  # a STEP export is always durable
        ("immutable-read-v1", BIG),
        ("sol-read-v1", BIG),
    ):
        key = _key("onshape", kind)
        assert await _put(cache, key, value)
        raw = await redis.get(key)
        assert raw is not None and "durable" in raw, kind
    assert len(_files(tmp_path)) == 3


async def test_replacing_an_index_deletes_the_object_it_pointed_at(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    key = _key("onshape", "revision-v3-export")
    await _put(cache, key, "first")
    old = json.loads(str(await redis.get(key)))["durable"]["object_key"]

    await _put(cache, key, "second")

    new = json.loads(str(await redis.get(key)))["durable"]["object_key"]
    assert new != old
    assert await cad.get(old) is None
    assert await cad.get(new) is not None
    assert len(_files(tmp_path)) == 1


async def test_replacing_a_durable_index_with_a_small_payload_also_reclaims(
    tmp_path: Path,
) -> None:
    cache, redis, cad = _setup(tmp_path)
    key = _key("onshape", "immutable-read-v1")
    await _put(cache, key, BIG)
    old = json.loads(str(await redis.get(key)))["durable"]["object_key"]
    await _put(cache, key, SMALL)
    assert await cad.get(old) is None
    assert "durable" not in str(await redis.get(key))


async def test_invalidating_an_index_deletes_its_object(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    key = _key("onshape", "revision-v3-export")
    await _put(cache, key, "payload")
    object_key = json.loads(str(await redis.get(key)))["durable"]["object_key"]
    await cache.invalidate(key)
    assert await redis.get(key) is None
    assert await cad.get(object_key) is None


async def test_a_forged_index_never_deletes_another_accounts_object(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    key_a = _key("onshape", "revision-v3-export", account="acct-a")
    key_b = _key("onshape", "revision-v3-export", account="acct-b")
    await _put(cache, key_b, "b private")
    b_index = json.loads(str(await redis.get(key_b)))
    b_object = b_index["durable"]["object_key"]
    await redis.set(key_a, json.dumps(b_index), 60)

    await cache.invalidate(key_a)

    assert await cad.get(b_object) is not None


async def test_a_process_without_a_durable_store_treats_a_durable_index_as_a_miss(
    tmp_path: Path,
) -> None:
    cache, redis, _ = _setup(tmp_path)
    key = _key("onshape", "revision-v3-export")
    await _put(cache, key, "payload")
    plain = IntegrationCache(redis)  # same Redis, no durable store configured

    assert await plain.get(key) is None
    calls = 0

    async def fetch() -> str:
        nonlocal calls
        calls += 1
        return "fresh"

    result = await plain.fetch(key, ttl_seconds=60, fetch=fetch)
    assert calls == 1 and result.value == "fresh"


async def test_a_tombstoned_account_cannot_write_durable_objects(tmp_path: Path) -> None:
    cache, redis, _ = _setup(tmp_path)
    key = _key("onshape", "revision-v3-export")
    assert await cache.tombstone_account("onshape", "acct")

    assert await _put(cache, key, "late write from an in-flight sync") is False

    assert _files(tmp_path) == []
    assert await redis.get(key) is None
    # Another account is unaffected.
    assert await _put(cache, _key("onshape", "revision-v3-export", account="other"), "ok")


async def test_the_tombstone_expires(tmp_path: Path) -> None:
    now = [0.0]
    redis = InMemoryCacheStore(clock=lambda: now[0])
    cad = LocalCadStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)
    cache = IntegrationCache(redis, durable_store=cad)
    await cache.tombstone_account("onshape", "acct")
    now[0] += 2 * 3600
    assert await _put(cache, _key("onshape", "revision-v3-export"), "after the window")


async def test_invalidate_account_can_skip_the_inline_durable_delete(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    key = _key("onshape", "revision-v3-export")
    await _put(cache, key, "payload")
    object_key = json.loads(str(await redis.get(key)))["durable"]["object_key"]

    await cache.invalidate_account("onshape", "acct", delete_durable=False)

    assert await redis.get(key) is None
    assert await cad.get(object_key) is not None  # the purge record owns this deletion
