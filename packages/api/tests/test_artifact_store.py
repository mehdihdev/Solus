"""ArtifactStore backend tests — round-trip, file permissions, path-traversal
safety, lazy S3 import, and `build_artifact_store` backend selection
(docs/api/artifacts.md §4.6; mirrors test_secrets.py's SecretStore coverage)."""

import stat
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict
from solus_api.core.config import Settings
from solus_api.models import ArtifactStorage
from solus_api.storage import (
    ArtifactNotFoundError,
    LocalArtifactStore,
    S3ArtifactStore,
    build_artifact_store,
    validate_storage_key,
)

SECRET = "dummy-jwt-signing-value-tests-only"  # placeholder, not a real secret
# Named without "key"/"secret"/"token": storage keys are opaque server-minted
# UUIDs, and a KEY-ish name makes secret scanners flag the literal (gitleaks
# generic-api-key fired on the old name and failed the security stage).
STORAGE_REF = "0d7a5e2a-1c1a-4a6d-9d0e-2b6a5f9c1a10"


class HermeticSettings(Settings):
    """`Settings` that never reads a checkout's `.env` file (mirrors test_secrets.py's
    HermeticSettings — the backend-selection tests must see exactly the fields
    they pass)."""

    model_config = SettingsConfigDict(env_prefix="SOLUS_", env_file=None, extra="ignore")


def _settings(**overrides: Any) -> HermeticSettings:
    fields: dict[str, Any] = {"supabase_jwt_secret": SECRET}
    fields.update(overrides)
    return HermeticSettings(**fields)


# --- key safety ---


def test_validate_storage_key_accepts_uuid() -> None:
    assert validate_storage_key(STORAGE_REF) == STORAGE_REF


@pytest.mark.parametrize(
    "bad_key",
    ["../../etc/passwd", "not-a-uuid", "", "..", "a/b/c", STORAGE_REF + "/../x", "/etc/passwd"],
)
def test_validate_storage_key_rejects_non_uuid(bad_key: str) -> None:
    with pytest.raises(ValueError):
        validate_storage_key(bad_key)


# --- local backend ---


async def test_local_store_roundtrips_bytes(tmp_path: Path) -> None:
    store = LocalArtifactStore(str(tmp_path))
    await store.put(STORAGE_REF, b"hello world")
    assert await store.get(STORAGE_REF) == b"hello world"


async def test_local_store_files_are_0600(tmp_path: Path) -> None:
    store = LocalArtifactStore(str(tmp_path))
    await store.put(STORAGE_REF, b"secret bytes")
    mode = stat.S_IMODE((tmp_path / STORAGE_REF).stat().st_mode)
    assert mode == 0o600


async def test_local_store_missing_raises(tmp_path: Path) -> None:
    store = LocalArtifactStore(str(tmp_path))
    with pytest.raises(ArtifactNotFoundError):
        await store.get(STORAGE_REF)


async def test_local_store_delete_is_idempotent(tmp_path: Path) -> None:
    store = LocalArtifactStore(str(tmp_path))
    await store.put(STORAGE_REF, b"x")
    await store.delete(STORAGE_REF)
    await store.delete(STORAGE_REF)  # no-op, must not raise
    with pytest.raises(ArtifactNotFoundError):
        await store.get(STORAGE_REF)


async def test_local_store_rejects_path_traversal_key(tmp_path: Path) -> None:
    store = LocalArtifactStore(str(tmp_path))
    with pytest.raises(ValueError):
        await store.put("../../evil", b"x")
    # Nothing must have escaped the root.
    assert not (tmp_path.parent / "evil").exists()


def test_local_store_backend_marker(tmp_path: Path) -> None:
    assert LocalArtifactStore(str(tmp_path)).backend == ArtifactStorage.LOCAL


def test_local_store_root_is_introspectable(tmp_path: Path) -> None:
    store = LocalArtifactStore(str(tmp_path))
    assert store.root == tmp_path


def test_local_store_root_is_0700(tmp_path: Path) -> None:
    """Phase 4 L6 hygiene: the store ROOT itself must be 0700, not just each
    file within it — otherwise another local account could list/traverse the
    directory even without read access to any individual file."""
    root = tmp_path / "artifacts"
    LocalArtifactStore(str(root))
    mode = stat.S_IMODE(root.stat().st_mode)
    assert mode == 0o700


def test_local_store_enforces_0700_on_a_preexisting_looser_root(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o755)
    LocalArtifactStore(str(root))
    mode = stat.S_IMODE(root.stat().st_mode)
    assert mode == 0o700


# --- S3 backend (fake boto3, no network, no real bucket) ---


class _FakeS3Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        self.response: dict[str, Any] = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803 — mirrors boto3's signature
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise _FakeClientError("NoSuchKey")
        return {"Body": _FakeS3Body(self.objects[Key])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop(Key, None)


@pytest.fixture
def fake_boto3(monkeypatch: pytest.MonkeyPatch) -> _FakeS3Client:
    client = _FakeS3Client()
    fake_boto3_module = types.SimpleNamespace(client=lambda service, region_name=None: client)
    fake_exceptions = types.SimpleNamespace(ClientError=_FakeClientError)
    fake_botocore = types.SimpleNamespace(exceptions=fake_exceptions)
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3_module)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", fake_exceptions)
    return client


async def test_s3_store_is_lazily_imported_and_roundtrips(fake_boto3: _FakeS3Client) -> None:
    # Importing solus_api.storage at module load must never require boto3 —
    # only constructing an S3ArtifactStore touches the (here, fake) SDK.
    store = S3ArtifactStore(bucket="solus-artifacts-test")
    await store.put(STORAGE_REF, b"cad export bytes")
    assert await store.get(STORAGE_REF) == b"cad export bytes"
    assert store.backend == ArtifactStorage.S3


async def test_s3_store_missing_key_raises(fake_boto3: _FakeS3Client) -> None:
    store = S3ArtifactStore(bucket="solus-artifacts-test")
    with pytest.raises(ArtifactNotFoundError):
        await store.get(STORAGE_REF)


async def test_s3_store_delete_is_idempotent(fake_boto3: _FakeS3Client) -> None:
    store = S3ArtifactStore(bucket="solus-artifacts-test")
    await store.put(STORAGE_REF, b"x")
    await store.delete(STORAGE_REF)
    await store.delete(STORAGE_REF)


async def test_s3_store_rejects_non_uuid_key(fake_boto3: _FakeS3Client) -> None:
    store = S3ArtifactStore(bucket="solus-artifacts-test")
    with pytest.raises(ValueError):
        await store.put("../not-a-uuid", b"x")


# --- build_artifact_store selection ---


def test_build_prefers_s3_when_bucket_set() -> None:
    settings = _settings(artifact_s3_bucket="solus-artifacts")
    assert isinstance(build_artifact_store(settings), S3ArtifactStore)


def test_build_prefers_local_when_root_set(tmp_path: Path) -> None:
    settings = _settings(artifact_local_root=str(tmp_path))
    assert isinstance(build_artifact_store(settings), LocalArtifactStore)


def test_build_falls_back_to_tmp_in_dev() -> None:
    settings = _settings(app_env="dev")
    assert isinstance(build_artifact_store(settings), LocalArtifactStore)


def test_build_hard_fails_in_prod_without_backend() -> None:
    settings = _settings(app_env="production")
    with pytest.raises(RuntimeError):
        build_artifact_store(settings)
