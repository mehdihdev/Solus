"""ADR-038 §1: IntegrationCache payloads live in the durable CAD store; Redis keeps an index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.storage.cad_store import LocalCadStore, account_hash

MIB = 1024 * 1024
PROVIDER = "onshape"
ACCOUNT_A = "acct-a"
ACCOUNT_B = "acct-b"


class _BrokenStore:
    """A durable store whose every operation fails."""

    max_object_bytes = 64 * MIB

    async def put(self, account_scope: str, data: bytes) -> str:
        raise OSError("disk full")

    async def get(self, object_key: str) -> bytes | None:
        raise OSError("unreachable")

    async def delete_account(self, account_scope: str) -> int:
        raise OSError("unreachable")


def _setup(
    tmp_path: Path, max_bytes: int = 64 * MIB
) -> tuple[IntegrationCache, InMemoryCacheStore, LocalCadStore]:
    redis = InMemoryCacheStore()
    cad = LocalCadStore(str(tmp_path / "cad"), max_object_bytes=max_bytes)
    return IntegrationCache(redis, durable_store=cad), redis, cad


def _key(account: str = ACCOUNT_A, item: str = "doc1") -> str:
    return IntegrationCache.payload_key(PROVIDER, account, item, "mv1", "revision-v3-export", "e1")


async def _fetch_counted(cache: IntegrationCache, key: str, value: Any) -> tuple[Any, int]:
    calls = 0

    async def fetch() -> Any:
        nonlocal calls
        calls += 1
        return value

    result = await cache.fetch(key, ttl_seconds=60, fetch=fetch)
    return result, calls


async def test_payload_bytes_go_to_the_durable_store_and_redis_keeps_only_an_index(
    tmp_path: Path,
) -> None:
    cache, redis, cad = _setup(tmp_path)
    key = _key()
    await _fetch_counted(cache, key, "ISO-10303-21 secret geometry")

    raw = await redis.get(key)
    assert raw is not None
    assert "secret geometry" not in raw
    index = json.loads(raw)["durable"]
    assert set(index) == {"object_key", "sha256", "size"}
    assert index["object_key"].startswith(f"cad/{account_hash('onshape:acct-a')}/")
    stored = await cad.get(index["object_key"])
    assert stored is not None and b"secret geometry" in stored
    assert index["size"] == len(stored)


async def test_a_second_read_is_served_from_the_durable_store(tmp_path: Path) -> None:
    cache, _, _ = _setup(tmp_path)
    key = _key()
    first, first_calls = await _fetch_counted(cache, key, "step")
    second, second_calls = await _fetch_counted(cache, key, "step")
    assert (first.cached, second.cached) == (False, True)
    assert first_calls == 1 and second_calls == 0
    assert second.value == "step"


async def test_a_tampered_object_is_a_miss_and_is_refetched(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    key = _key()
    await _fetch_counted(cache, key, "original")
    index = json.loads(str(await redis.get(key)))["durable"]
    (tmp_path / "cad" / index["object_key"]).write_bytes(b"tampered")

    result, calls = await _fetch_counted(cache, key, "refetched")
    assert calls == 1 and result.cached is False and result.value == "refetched"
    again, again_calls = await _fetch_counted(cache, key, "unused")
    assert again_calls == 0 and again.value == "refetched"


async def test_a_missing_object_is_a_miss(tmp_path: Path) -> None:
    cache, redis, _ = _setup(tmp_path)
    key = _key()
    await _fetch_counted(cache, key, "value")
    index = json.loads(str(await redis.get(key)))["durable"]
    (tmp_path / "cad" / index["object_key"]).unlink()

    result, calls = await _fetch_counted(cache, key, "again")
    assert calls == 1 and result.value == "again"


async def test_durable_read_and_write_failures_degrade_to_a_miss_never_an_error() -> None:
    cache = IntegrationCache(InMemoryCacheStore(), durable_store=_BrokenStore())
    key = _key()
    first, first_calls = await _fetch_counted(cache, key, "value")
    second, second_calls = await _fetch_counted(cache, key, "value")
    # The sync still gets its value; it just is not cached.
    assert first.value == "value" and second.value == "value"
    assert (first_calls, second_calls) == (1, 1)
    assert await cache.invalidate_account(PROVIDER, ACCOUNT_A) == 0


async def test_a_malformed_index_entry_is_a_miss(tmp_path: Path) -> None:
    cache, redis, _ = _setup(tmp_path)
    key = _key()
    bad_entries: list[dict[str, Any]] = [
        {"durable": "nope"},
        {"durable": {"object_key": 1, "sha256": "x", "size": 1}},
        {"durable": {"object_key": "../../etc/passwd", "sha256": "0" * 64, "size": 1}},
        {"durable": {}},
    ]
    for bad in bad_entries:
        await redis.set(key, json.dumps(bad), 60)
        _, calls = await _fetch_counted(cache, key, "v")
        assert calls == 1
        await cache.invalidate(key)


async def test_an_index_can_never_resolve_to_another_accounts_object(tmp_path: Path) -> None:
    cache, redis, _ = _setup(tmp_path)
    key_a, key_b = _key(ACCOUNT_A), _key(ACCOUNT_B)
    await _fetch_counted(cache, key_b, "account B private geometry")
    b_index = json.loads(str(await redis.get(key_b)))
    # An attacker (or a bug) copies B's index entry under A's key.
    await redis.set(key_a, json.dumps(b_index), 60)

    result, calls = await _fetch_counted(cache, key_a, "A's own fetch")
    assert calls == 1
    assert result.value == "A's own fetch"
    assert "account B" not in json.dumps(result.value)


async def test_invalidate_account_deletes_the_durable_objects(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    key_a, key_b = _key(ACCOUNT_A), _key(ACCOUNT_B)
    await _fetch_counted(cache, key_a, "a")
    await _fetch_counted(cache, _key(ACCOUNT_A, "doc2"), "a2")
    await _fetch_counted(cache, key_b, "b")
    a_object = json.loads(str(await redis.get(key_a)))["durable"]["object_key"]

    removed = await cache.invalidate_account(PROVIDER, ACCOUNT_A)

    assert removed == 2
    assert await cad.get(a_object) is None
    assert await redis.get(key_a) is None
    # The other account is untouched.
    result, calls = await _fetch_counted(cache, key_b, "b")
    assert calls == 0 and result.value == "b"


async def test_the_eight_mib_cap_applies_only_without_a_durable_store(tmp_path: Path) -> None:
    big = "x" * (9 * MIB)
    plain = IntegrationCache(InMemoryCacheStore())
    _, calls = await _fetch_counted(plain, _key(), big)
    _, calls_again = await _fetch_counted(plain, _key(), big)
    assert (calls, calls_again) == (1, 1)  # oversize: never kept

    cache, redis, _ = _setup(tmp_path)
    _, calls = await _fetch_counted(cache, _key(), big)
    again, calls_again = await _fetch_counted(cache, _key(), big)
    assert (calls, calls_again) == (1, 0) and again.cached is True
    assert len(str(await redis.get(_key()))) < 1024  # Redis holds the index only


async def test_the_durable_cap_is_the_stores_object_cap(tmp_path: Path) -> None:
    cache, _, _ = _setup(tmp_path, max_bytes=1 * MIB)
    _, calls = await _fetch_counted(cache, _key(), "y" * (2 * MIB))
    _, calls_again = await _fetch_counted(cache, _key(), "y" * (2 * MIB))
    assert (calls, calls_again) == (1, 1)


async def test_listings_and_signals_stay_in_redis_only(tmp_path: Path) -> None:
    cache, redis, cad = _setup(tmp_path)
    await cache.put(
        IntegrationCache.listing_key(PROVIDER, ACCOUNT_A), {"value": [], "fetched_at": "x"}, 60
    )
    await cache.record_signal(
        IntegrationCache.signal_key(PROVIDER, ACCOUNT_A, "doc1"), {"workspace": "w", "version": "v"}
    )
    assert not [p for p in (tmp_path / "cad").rglob("*") if p.is_file()]
    raw = await redis.get(IntegrationCache.signal_key(PROVIDER, ACCOUNT_A, "doc1"))
    assert raw is not None and "durable" not in raw


@pytest.mark.parametrize("value", [None, 0, "", [], {}])
async def test_falsy_payload_values_round_trip(tmp_path: Path, value: Any) -> None:
    cache, _, _ = _setup(tmp_path)
    key = _key()
    await _fetch_counted(cache, key, value)
    again, calls = await _fetch_counted(cache, key, "unused")
    assert calls == 0 and again.value == value
