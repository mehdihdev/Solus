"""Pluggable byte storage for artifacts (docs/api/artifacts.md §4.6, W0-04
`ArtifactRef`/`ArtifactStorage`).

Bytes are written/read through the `ArtifactStore` protocol — S3 in prod, a
local filesystem in dev — mirroring the `SecretStore` selection pattern in
`connectors/secrets.py`. Storage keys are ALWAYS server-generated UUIDs (the
artifact row's own id), NEVER client input (CLAUDE.md §7 upload hygiene);
`validate_storage_key` is defense-in-depth against path traversal / an
injected object key, enforced by every concrete backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from solus_api.models import ArtifactStorage

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.storage.artifacts")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_LOCAL_FILE_MODE = 0o600
# Phase 4 L6 hygiene: the store root itself must not be group/world-readable
# either — a 0700 directory keeps `os.listdir`/traversal from any other local
# account, matching the 0600 posture already applied to each file within it.
_LOCAL_ROOT_MODE = 0o700


class ArtifactNotFoundError(KeyError):
    """No object stored under the given key (missing, expired-and-swept, or
    already consumed)."""


def validate_storage_key(key: str) -> str:
    """Reject anything that isn't a bare UUID string — the only shape a
    server-generated artifact id ever takes. Never derive a storage path from
    client-supplied text (e.g. a filename)."""
    if not isinstance(key, str) or not _UUID_RE.match(key):
        raise ValueError(f"invalid artifact storage key: {key!r}")
    return key


@runtime_checkable
class ArtifactStore(Protocol):
    """put/get/delete over an opaque, server-generated key."""

    backend: ArtifactStorage

    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes:
        """Return the bytes, or raise `ArtifactNotFoundError`."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object; a no-op if already absent."""
        ...


class LocalArtifactStore:
    """Filesystem-backed store (dev). Files are written 0600; the key is
    validated (defense-in-depth) before it ever touches a path."""

    backend = ArtifactStorage.LOCAL

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True, mode=_LOCAL_ROOT_MODE)
        # `mkdir`'s `mode` is masked by the process umask and is a no-op on an
        # already-existing directory — `chmod` afterward enforces 0700
        # unconditionally, regardless of umask or a pre-existing looser root.
        os.chmod(self._root, _LOCAL_ROOT_MODE)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        return self._root / validate_storage_key(key)

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._write_sync, self._path(key), data)

    @staticmethod
    def _write_sync(path: Path, data: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _LOCAL_FILE_MODE)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._unlink_sync, self._path(key))

    @staticmethod
    def _unlink_sync(path: Path) -> None:
        path.unlink(missing_ok=True)


class S3ArtifactStore:
    """S3-backed store (production). boto3 is sync; every call is offloaded to
    a thread (mirrors `AwsSecretsManagerStore` in `connectors/secrets.py`)."""

    backend = ArtifactStorage.S3

    def __init__(self, bucket: str, region: str | None = None, prefix: str = "artifacts/") -> None:
        import boto3  # lazy — only prod needs the SDK / AWS creds

        self._client = boto3.client("s3", region_name=region) if region else boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix

    def _object_key(self, key: str) -> str:
        return f"{self._prefix}{validate_storage_key(key)}"

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=self._object_key(key), Body=data
        )

    async def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=self._object_key(key)
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise ArtifactNotFoundError(key) from exc
            raise
        data: bytes = await asyncio.to_thread(response["Body"].read)
        return data

    async def delete(self, key: str) -> None:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(
                self._client.delete_object, Bucket=self._bucket, Key=self._object_key(key)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchKey":
                raise


def build_artifact_store(settings: Settings) -> ArtifactStore:
    """Select a backend from settings (mirrors `build_secret_store`'s
    fail-fast-outside-dev posture): S3 when a bucket is configured, else a
    local root, else a scratch tmp dir tolerated only in dev."""
    if settings.artifact_s3_bucket:
        return S3ArtifactStore(bucket=settings.artifact_s3_bucket, region=settings.aws_region)
    if settings.artifact_local_root:
        return LocalArtifactStore(settings.artifact_local_root)
    if settings.app_env != "dev":
        raise RuntimeError(
            "No artifact store configured: set SOLUS_ARTIFACT_S3_BUCKET (prod) or "
            "SOLUS_ARTIFACT_LOCAL_ROOT (dev). Refusing to use a scratch tmp "
            f"directory in app_env={settings.app_env!r}."
        )
    logger.warning(
        "No artifact store configured (SOLUS_ARTIFACT_S3_BUCKET / "
        "SOLUS_ARTIFACT_LOCAL_ROOT unset) — using a process-local tmp directory. "
        "Dev only; bytes are lost on cleanup."
    )
    return LocalArtifactStore(tempfile.mkdtemp(prefix="solus-artifacts-"))
