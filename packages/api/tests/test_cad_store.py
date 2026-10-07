"""ADR-038 §1: the durable CAD derivative store (local + S3 backends)."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError
from solus_api.core.config import Settings
from solus_api.storage.cad_store import (
    CadDeleteError,
    CadObjectTooLargeError,
    CadStore,
    InvalidCadKeyError,
    LocalCadStore,
    S3CadStore,
    account_hash,
    build_cad_store,
)

KEY_SHAPE = re.compile(
    r"^cad/[0-9a-f]{64}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SCOPE_A = "onshape:account-a"
SCOPE_B = "onshape:account-b"


class _FakeS3Client:
    """The slice of boto3's S3 client the store uses, with real ClientErrors."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.delete_batches: list[list[str]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        key = kwargs["Key"]
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[key] = kwargs["Body"]

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data = self.objects[Key]

        class _Body:
            @staticmethod
            def read(amt: int | None = None) -> bytes:
                return data if amt is None else data[:amt]

        return {"Body": _Body(), "ContentLength": len(data)}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int = 1000) -> dict[str, Any]:  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))[:MaxKeys]
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop(Key, None)

    def get_paginator(self, name: str) -> Any:
        assert name == "list_objects_v2"
        objects = self.objects

        class _Pager:
            @staticmethod
            def paginate(*, Bucket: str, Prefix: str, PaginationConfig: Any = None) -> Any:  # noqa: N803
                keys = sorted(k for k in objects if k.startswith(Prefix))
                # Two keys per page to exercise pagination.
                for index in range(0, len(keys), 2):
                    yield {"Contents": [{"Key": k} for k in keys[index : index + 2]]}
                if not keys:
                    yield {}

        return _Pager()

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        batch = [item["Key"] for item in Delete["Objects"]]
        self.delete_batches.append(batch)
        for key in batch:
            self.objects.pop(key, None)
        return {}


def _s3(max_bytes: int = 1024) -> tuple[S3CadStore, _FakeS3Client]:
    client = _FakeS3Client()
    return S3CadStore("bucket", client=client, max_object_bytes=max_bytes), client


def _local(tmp_path: Path, max_bytes: int = 1024) -> LocalCadStore:
    return LocalCadStore(str(tmp_path / "cad-root"), max_object_bytes=max_bytes)


@pytest.fixture(params=["local", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> CadStore:
    if request.param == "local":
        return _local(tmp_path)
    return _s3()[0]


async def test_round_trip_returns_the_bytes_under_a_server_generated_key(store: CadStore) -> None:
    key = await store.put(SCOPE_A, b"step bytes")
    assert KEY_SHAPE.match(key)
    assert key.startswith(f"cad/{account_hash(SCOPE_A)}/")
    assert await store.get(key) == b"step bytes"


async def test_keys_carry_no_ids_names_or_emails(store: CadStore) -> None:
    key = await store.put("onshape:alice@example.com", b"x")
    assert "alice" not in key and "example" not in key and "onshape" not in key
    assert (
        account_hash("onshape:alice@example.com")
        == hashlib.sha256(b"onshape:alice@example.com").hexdigest()
    )


async def test_missing_object_reads_as_none(store: CadStore) -> None:
    key = f"cad/{account_hash(SCOPE_A)}/{uuid.uuid4()}"
    assert await store.get(key) is None


async def test_put_is_write_once_each_put_gets_a_fresh_object(store: CadStore) -> None:
    first = await store.put(SCOPE_A, b"one")
    second = await store.put(SCOPE_A, b"two")
    assert first != second
    assert await store.get(first) == b"one"
    assert await store.get(second) == b"two"


async def test_local_store_never_overwrites_on_a_key_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _local(tmp_path)
    fixed = uuid.UUID("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr("solus_api.storage.cad_store.uuid.uuid4", lambda: fixed)
    key = await store.put(SCOPE_A, b"original")
    with pytest.raises(FileExistsError):
        await store.put(SCOPE_A, b"clobber")
    assert await store.get(key) == b"original"


async def test_s3_store_retries_on_a_precondition_failure_without_overwriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, client = _s3()
    existing = uuid.UUID("22222222-2222-4222-8222-222222222222")
    fresh = uuid.UUID("33333333-3333-4333-8333-333333333333")
    taken = f"cad/{account_hash(SCOPE_A)}/{existing}"
    client.objects[taken] = b"original"
    ids = iter([existing, fresh])
    monkeypatch.setattr("solus_api.storage.cad_store.uuid.uuid4", lambda: next(ids))
    key = await store.put(SCOPE_A, b"new")
    assert key.endswith(str(fresh))
    assert client.objects[taken] == b"original"


async def test_objects_over_the_cap_are_refused_before_writing(
    tmp_path: Path,
) -> None:
    local = _local(tmp_path, max_bytes=8)
    with pytest.raises(CadObjectTooLargeError):
        await local.put(SCOPE_A, b"123456789")
    assert not any((tmp_path / "cad-root").rglob("*.*")) and not list(
        p for p in (tmp_path / "cad-root").rglob("*") if p.is_file()
    )
    s3, client = _s3(max_bytes=8)
    with pytest.raises(CadObjectTooLargeError):
        await s3.put(SCOPE_A, b"123456789")
    assert client.put_calls == []
    assert await s3.put(SCOPE_A, b"12345678")  # exactly at the cap is fine


async def test_s3_puts_always_request_server_side_encryption() -> None:
    store, client = _s3()
    await store.put(SCOPE_A, b"x")
    await store.put(SCOPE_B, b"y")
    assert len(client.put_calls) == 2
    assert all(call["ServerSideEncryption"] == "AES256" for call in client.put_calls)
    assert all(call["Bucket"] == "bucket" for call in client.put_calls)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../etc/passwd",
        "cad/../../etc/passwd",
        f"cad/{'a' * 64}/../{uuid.uuid4()}",
        f"cad/{'A' * 64}/{uuid.uuid4()}",  # uppercase hash
        f"cad/{'a' * 63}/{uuid.uuid4()}",
        f"cad/{'a' * 64}/not-a-uuid",
        f"/cad/{'a' * 64}/{uuid.uuid4()}",
        f"cad/{'a' * 64}/{uuid.uuid4()}/extra",
        f"cad/{'a' * 64}/{uuid.uuid4()}\n",
        f"artifacts/{'a' * 64}/{uuid.uuid4()}",
    ],
)
async def test_reading_a_key_of_the_wrong_shape_is_rejected(store: CadStore, bad: str) -> None:
    with pytest.raises(InvalidCadKeyError):
        await store.get(bad)


async def test_a_non_string_key_is_rejected(store: CadStore) -> None:
    with pytest.raises(InvalidCadKeyError):
        await store.get(None)  # type: ignore[arg-type]


async def test_delete_account_removes_only_that_accounts_objects(store: CadStore) -> None:
    a_keys = [await store.put(SCOPE_A, f"a{i}".encode()) for i in range(5)]
    b_key = await store.put(SCOPE_B, b"b")
    assert await store.delete_account(SCOPE_A) == 5
    for key in a_keys:
        assert await store.get(key) is None
    assert await store.get(b_key) == b"b"
    assert await store.delete_account(SCOPE_A) == 0  # idempotent


async def test_s3_delete_account_batches_deletes_by_the_account_prefix() -> None:
    store, client = _s3()
    for i in range(3):
        await store.put(SCOPE_A, bytes([i]))
    other = await store.put(SCOPE_B, b"keep")
    assert await store.delete_account(SCOPE_A) == 3
    assert [len(batch) for batch in client.delete_batches] == [2, 1]
    assert all(
        key.startswith(f"cad/{account_hash(SCOPE_A)}/")
        for batch in client.delete_batches
        for key in batch
    )
    assert other in client.objects


async def test_one_accounts_prefix_cannot_resolve_another_accounts_object(
    store: CadStore,
) -> None:
    key_b = await store.put(SCOPE_B, b"secret b")
    assert not key_b.startswith(f"cad/{account_hash(SCOPE_A)}/")
    assert account_hash(SCOPE_A) != account_hash(SCOPE_B)


async def test_local_store_files_are_private(tmp_path: Path) -> None:
    store = _local(tmp_path)
    key = await store.put(SCOPE_A, b"x")
    path = tmp_path / "cad-root" / key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "cad-root").stat().st_mode) == 0o700
    assert os.path.commonpath([path, tmp_path / "cad-root"]) == str(tmp_path / "cad-root")


def _settings(**fields: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "supabase_jwt_secret": "dummy",
        "database_url": "sqlite+aiosqlite://",
    }
    return Settings(**{**base, **fields})


def test_build_cad_store_selects_a_backend_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert build_cad_store(_settings()) is None
    local = build_cad_store(_settings(cad_store_local_root=str(tmp_path / "r")))
    assert isinstance(local, LocalCadStore)
    assert local.max_object_bytes == _settings().cad_store_max_object_bytes

    created: dict[str, Any] = {}

    def fake_client(service: str, **kwargs: Any) -> _FakeS3Client:
        created.update(service=service, **kwargs)
        return _FakeS3Client()

    monkeypatch.setattr("boto3.client", fake_client)
    both = build_cad_store(
        _settings(cad_store_local_root=str(tmp_path / "r"), cad_store_s3_bucket="b")
    )
    assert isinstance(both, S3CadStore)  # S3 wins when both are set
    assert created["service"] == "s3"


# ---------------------------------------------------------------- Phase 4 fixes


class _FailingDeleteS3Client(_FakeS3Client):
    """`DeleteObjects` answers 200 with per-key `Errors` (S3's partial-failure shape)."""

    def __init__(self, failing: set[str]) -> None:
        super().__init__()
        self.failing = failing

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        errors = []
        for item in Delete["Objects"]:
            if item["Key"] in self.failing:
                errors.append({"Key": item["Key"], "Code": "AccessDenied", "Message": "nope"})
            else:
                self.objects.pop(item["Key"], None)
        return {"Errors": errors} if errors else {}


async def test_s3_delete_account_raises_when_delete_objects_reports_errors() -> None:
    client = _FailingDeleteS3Client(set())
    store = S3CadStore("bucket", client=client, max_object_bytes=1024)
    keys = [await store.put(SCOPE_A, bytes([i])) for i in range(3)]
    client.failing = {keys[1]}

    with pytest.raises(CadDeleteError):
        await store.delete_account(SCOPE_A)

    assert keys[1] in client.objects  # the failed key is still there, and we said so
    client.failing = set()
    assert await store.delete_account(SCOPE_A) == 1  # only what was actually deleted is counted


async def test_s3_delete_account_raises_when_the_prefix_is_not_empty_afterwards() -> None:
    store, client = _s3()
    await store.put(SCOPE_A, b"x")
    client.delete_objects = lambda **_: {}  # type: ignore[method-assign]  # silently deletes nothing
    with pytest.raises(CadDeleteError):
        await store.delete_account(SCOPE_A)


async def test_delete_account_hash_matches_delete_account(store: CadStore) -> None:
    key = await store.put(SCOPE_A, b"x")
    assert await store.delete_account_hash(account_hash(SCOPE_A)) == 1
    assert await store.get(key) is None
    with pytest.raises(InvalidCadKeyError):
        await store.delete_account_hash("../..")


async def test_delete_removes_one_object_and_validates_the_key(store: CadStore) -> None:
    first = await store.put(SCOPE_A, b"one")
    second = await store.put(SCOPE_A, b"two")
    await store.delete(first)
    assert await store.get(first) is None and await store.get(second) == b"two"
    await store.delete(first)  # idempotent
    with pytest.raises(InvalidCadKeyError):
        await store.delete("cad/../../etc/passwd")


async def test_local_put_writes_every_byte_even_when_os_write_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _local(tmp_path, max_bytes=1024)
    real_write = os.write

    def short_write(fd: int, data: Any) -> int:
        return real_write(fd, bytes(data)[:3])

    monkeypatch.setattr("solus_api.storage.cad_store.os.write", short_write)
    payload = bytes(range(200))
    key = await store.put(SCOPE_A, payload)
    assert await store.get(key) == payload


async def test_get_refuses_an_object_larger_than_the_cap_without_reading_it(
    tmp_path: Path,
) -> None:
    local = _local(tmp_path, max_bytes=1024)
    key = await local.put(SCOPE_A, b"x" * 10)
    local.max_object_bytes = 5
    with pytest.raises(CadObjectTooLargeError):
        await local.get(key)

    s3, client = _s3(max_bytes=1024)
    s3_key = await s3.put(SCOPE_A, b"x" * 10)
    s3.max_object_bytes = 5
    with pytest.raises(CadObjectTooLargeError):
        await s3.get(s3_key)

    class _NoLengthBody:
        @staticmethod
        def read(amt: int | None = None) -> bytes:
            return b"x" * (100 if amt is None else min(amt, 100))

    client.get_object = lambda **_: {"Body": _NoLengthBody()}  # type: ignore[method-assign]
    with pytest.raises(CadObjectTooLargeError):  # no ContentLength: the bounded read catches it
        await s3.get(s3_key)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("onshape_quiet_period_seconds", -1),
        ("onshape_quiet_period_seconds", 601),
        ("cad_store_max_object_bytes", 1024 * 1024 - 1),
        ("cad_store_max_object_bytes", 1024**3 + 1),
    ],
)
def test_store_and_quiet_period_settings_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: value})


def test_store_and_quiet_period_settings_accept_their_bounds() -> None:
    assert _settings(onshape_quiet_period_seconds=0).onshape_quiet_period_seconds == 0
    assert _settings(onshape_quiet_period_seconds=600).onshape_quiet_period_seconds == 600
    assert _settings(cad_store_max_object_bytes=1024 * 1024).cad_store_max_object_bytes == 1024**2
    assert _settings(cad_store_max_object_bytes=1024**3).cad_store_max_object_bytes == 1024**3
