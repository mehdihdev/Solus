"""Durable CAD derivative store (ADR-038 §1).

Onshape-derived artifacts (STEP exports, part metadata, meshes) are written ONCE
under server-generated keys, never mutated, never shared across provider
accounts, and deleted when the account connection is revoked. Redis keeps only
the index (`IntegrationCache`); the bytes live here — S3 in production, a local
directory in dev (mirrors `artifact_store.py`).

Object keys are `cad/<account_hash>/<uuid4>` where
`account_hash = sha256("<provider>:<account_ref>")`: no ids, names or emails ever
appear in a key, and every key read back is validated against that exact shape,
which is also the path-traversal guard for the local backend.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.storage.cad")

_PREFIX = "cad"
_KEY_RE = re.compile(
    r"^cad/(?P<account>[0-9a-f]{64})/"
    r"(?P<object>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\Z"
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}\Z")
_FILE_MODE = 0o600
_DIR_MODE = 0o700
#: A fresh uuid4 colliding is astronomically unlikely; this bounds the retry
#: anyway so write-once can never become an unbounded loop.
_PUT_ATTEMPTS = 3
#: S3's `DeleteObjects` accepts at most 1000 keys.
_S3_DELETE_BATCH = 1000


class CadObjectTooLargeError(ValueError):
    """The object exceeds `cad_store_max_object_bytes`; nothing was written."""


class CadDeleteError(RuntimeError):
    """A delete did not fully succeed: objects remain under the prefix. The caller
    must retry; it must never treat the account's CAD as gone."""


class InvalidCadKeyError(ValueError):
    """The key is not a server-generated `cad/<account_hash>/<uuid>` key."""


def account_hash(account_scope: str) -> str:
    """Opaque, stable per-account path segment from `"<provider>:<account_ref>"`."""
    return hashlib.sha256(account_scope.encode("utf-8")).hexdigest()


def account_prefix(account_scope: str) -> str:
    return f"{_PREFIX}/{account_hash(account_scope)}/"


def _validated_hash(digest: str) -> str:
    if not isinstance(digest, str) or not _HASH_RE.match(digest):
        raise InvalidCadKeyError("invalid CAD account hash")
    return digest


def validate_cad_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise InvalidCadKeyError("invalid CAD store object key")
    return key


def _new_key(account_scope: str) -> str:
    return f"{account_prefix(account_scope)}{uuid.uuid4()}"


@runtime_checkable
class CadStore(Protocol):
    """put-once / get / delete-by-account over server-generated keys."""

    max_object_bytes: int

    async def put(self, account_scope: str, data: bytes) -> str:
        """Write `data` under a NEW key and return it. Never overwrites."""
        ...

    async def get(self, object_key: str) -> bytes | None:
        """The bytes, or None when the object is absent. Raises
        `InvalidCadKeyError` for a malformed key."""
        ...

    async def delete_account(self, account_scope: str) -> int:
        """Remove every object of one account; returns how many were removed.
        Raises `CadDeleteError` when anything could not be removed."""
        ...

    async def delete_account_hash(self, digest: str) -> int:
        """`delete_account` for a caller that only holds the opaque account hash
        (the durable purge record stores no ids)."""
        ...

    async def delete(self, object_key: str) -> None:
        """Remove ONE object (idempotent). Raises `InvalidCadKeyError` for a bad key."""
        ...


class LocalCadStore:
    """Filesystem backend (dev). Files 0600, directories 0700, `O_EXCL` writes."""

    def __init__(self, root: str, *, max_object_bytes: int) -> None:
        self._root = Path(root)
        self.max_object_bytes = max_object_bytes
        self._root.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        os.chmod(self._root, _DIR_MODE)

    def _path(self, key: str) -> Path:
        return self._root / validate_cad_key(key)

    async def put(self, account_scope: str, data: bytes) -> str:
        if len(data) > self.max_object_bytes:
            raise CadObjectTooLargeError("CAD object exceeds the per-object cap")
        key = _new_key(account_scope)
        await asyncio.to_thread(self._write_sync, self._path(key), data)
        return key

    @staticmethod
    def _write_sync(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        # O_EXCL: an existing object is never truncated or replaced.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
        try:
            view = memoryview(data)
            while view:  # os.write may be short; loop until every byte is down
                view = view[os.write(fd, view) :]
        finally:
            os.close(fd)

    async def get(self, object_key: str) -> bytes | None:
        path = self._path(object_key)
        try:
            return await asyncio.to_thread(self._read_bounded, path, self.max_object_bytes)
        except FileNotFoundError:
            return None

    @staticmethod
    def _read_bounded(path: Path, cap: int) -> bytes:
        with path.open("rb") as handle:
            if os.fstat(handle.fileno()).st_size > cap:
                raise CadObjectTooLargeError("stored CAD object exceeds the per-object cap")
            data = handle.read(cap + 1)
        if len(data) > cap:
            raise CadObjectTooLargeError("stored CAD object exceeds the per-object cap")
        return data

    async def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        await asyncio.to_thread(path.unlink, True)

    async def delete_account(self, account_scope: str) -> int:
        return await self.delete_account_hash(account_hash(account_scope))

    async def delete_account_hash(self, digest: str) -> int:
        directory = self._root / _PREFIX / _validated_hash(digest)
        return await asyncio.to_thread(self._remove_tree, directory)

    @staticmethod
    def _remove_tree(directory: Path) -> int:
        if not directory.is_dir():
            return 0
        count = sum(1 for entry in directory.iterdir() if entry.is_file())
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            raise CadDeleteError("could not remove the account's CAD directory") from exc
        if directory.exists():
            raise CadDeleteError("the account's CAD directory still exists")
        return count


class S3CadStore:
    """S3 backend (production). boto3 is sync; every call runs in a thread."""

    def __init__(
        self,
        bucket: str,
        *,
        max_object_bytes: int,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            import boto3  # lazy — only prod needs the SDK / AWS creds

            client = boto3.client("s3", region_name=region) if region else boto3.client("s3")
        self._client = client
        self._bucket = bucket
        self.max_object_bytes = max_object_bytes

    async def put(self, account_scope: str, data: bytes) -> str:
        from botocore.exceptions import ClientError

        if len(data) > self.max_object_bytes:
            raise CadObjectTooLargeError("CAD object exceeds the per-object cap")
        for _ in range(_PUT_ATTEMPTS):
            key = _new_key(account_scope)
            try:
                await asyncio.to_thread(
                    self._client.put_object,
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    ServerSideEncryption="AES256",
                    IfNoneMatch="*",  # write-once: refuse to replace an existing object
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") == "PreconditionFailed":
                    continue
                raise
            return key
        raise FileExistsError("could not allocate an unused CAD object key")

    async def get(self, object_key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        key = validate_cad_key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        cap = self.max_object_bytes
        length = response.get("ContentLength")
        if isinstance(length, int) and length > cap:
            raise CadObjectTooLargeError("stored CAD object exceeds the per-object cap")
        data: bytes = await asyncio.to_thread(response["Body"].read, cap + 1)
        if len(data) > cap:
            raise CadObjectTooLargeError("stored CAD object exceeds the per-object cap")
        return data

    async def delete(self, object_key: str) -> None:
        key = validate_cad_key(object_key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def delete_account(self, account_scope: str) -> int:
        return await self.delete_account_hash(account_hash(account_scope))

    async def delete_account_hash(self, digest: str) -> int:
        prefix = f"{_PREFIX}/{_validated_hash(digest)}/"
        return await asyncio.to_thread(self._delete_prefix_sync, prefix)

    def _delete_prefix_sync(self, prefix: str) -> int:
        """Delete every object under `prefix`, then PROVE the prefix lists empty.

        `DeleteObjects` answers 200 even when individual keys fail (they come back
        in `Errors`), so a 200 is not a deletion: errors raise, only keys S3 did
        not report are counted, and a final listing must come back empty."""
        removed = 0
        failed = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            for start in range(0, len(keys), _S3_DELETE_BATCH):
                batch = keys[start : start + _S3_DELETE_BATCH]
                response = self._client.delete_objects(
                    Bucket=self._bucket, Delete={"Objects": batch, "Quiet": True}
                )
                errors = response.get("Errors") or []
                failed += len(errors)
                removed += len(batch) - len(errors)
        if failed:
            raise CadDeleteError(f"{failed} CAD objects could not be deleted")
        leftover = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, MaxKeys=1)
        if leftover.get("Contents"):
            raise CadDeleteError("CAD objects remain under the account prefix after deletion")
        return removed


def build_cad_store(settings: Settings) -> CadStore | None:
    """S3 when a bucket is configured, a local root for dev, else None (the
    integration cache then stays Redis-only with its 8 MiB cap)."""
    cap = settings.cad_store_max_object_bytes
    if settings.cad_store_s3_bucket:
        return S3CadStore(
            settings.cad_store_s3_bucket, max_object_bytes=cap, region=settings.aws_region
        )
    if settings.cad_store_local_root:
        return LocalCadStore(settings.cad_store_local_root, max_object_bytes=cap)
    return None
