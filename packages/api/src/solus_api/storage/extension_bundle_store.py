"""Extension bundle + store-asset bytes (SOLUSDEV-235 / ADR-035, EXT-07;
docs/api/extensions.md §4.4/§4.5/§5.1 step 4, docs/schemas/extensions.md §8.1).

A thin, typed wrapper over the `ArtifactStore` PROTOCOL: bundle bytes live under
key = `extension_versions.id`, extracted store assets under key =
`extension_version_assets.storage_key` (the asset row's own id). No `artifacts`
row is ever written — that table is project-scoped and cascades on project
delete, while the registry is global. Keys are ALWAYS server-generated UUIDs
(never client input) and are re-validated here as defense in depth.
"""

from __future__ import annotations

import uuid

from solus_api.models import ArtifactStorage
from solus_api.storage.artifact_store import ArtifactStore, validate_storage_key


def _key(row_id: uuid.UUID | str) -> str:
    return validate_storage_key(str(row_id))


class ExtensionBundleStore:
    """put/get/delete of bundle zips and store assets over an `ArtifactStore`."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    @property
    def backend(self) -> ArtifactStorage:
        """What `extension_versions.bundle_storage` / `..._assets.storage` record."""
        return self._store.backend

    async def put_bundle(self, version_id: uuid.UUID | str, data: bytes) -> None:
        await self._store.put(_key(version_id), data)

    async def get_bundle(self, version_id: uuid.UUID | str) -> bytes:
        """The stored zip bytes, verbatim; raises `ArtifactNotFoundError` when absent."""
        return await self._store.get(_key(version_id))

    async def delete_bundle(self, version_id: uuid.UUID | str) -> None:
        await self._store.delete(_key(version_id))

    async def put_asset(self, asset_id: uuid.UUID | str, data: bytes) -> None:
        await self._store.put(_key(asset_id), data)

    async def get_asset(self, asset_id: uuid.UUID | str) -> bytes:
        """The stored (already sanitized) asset bytes; raises `ArtifactNotFoundError`."""
        return await self._store.get(_key(asset_id))

    async def delete_asset(self, asset_id: uuid.UUID | str) -> None:
        await self._store.delete(_key(asset_id))
