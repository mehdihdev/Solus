"""`ExtensionBundleStore` — the typed wrapper over the `ArtifactStore` protocol
for bundle zips and store assets (SOLUSDEV-235 EXT-07, docs/api/extensions.md
§5.1 step 4 / docs/schemas/extensions.md §8.1)."""

import uuid
from pathlib import Path

import pytest
from solus_api.models import ArtifactStorage
from solus_api.storage import ArtifactNotFoundError, LocalArtifactStore
from solus_api.storage.extension_bundle_store import ExtensionBundleStore
from uuid6 import uuid7


@pytest.fixture
def store(tmp_path: Path) -> ExtensionBundleStore:
    return ExtensionBundleStore(LocalArtifactStore(str(tmp_path / "ext")))


async def test_bundle_round_trips_under_the_version_id(store: ExtensionBundleStore) -> None:
    version_id = uuid7()
    await store.put_bundle(version_id, b"PK\x03\x04 bundle bytes")
    assert await store.get_bundle(version_id) == b"PK\x03\x04 bundle bytes"
    await store.delete_bundle(version_id)
    with pytest.raises(ArtifactNotFoundError):
        await store.get_bundle(version_id)


async def test_asset_round_trips_under_the_asset_id(store: ExtensionBundleStore) -> None:
    asset_id = uuid7()
    await store.put_asset(asset_id, b"# Overview")
    assert await store.get_asset(str(asset_id)) == b"# Overview"
    await store.delete_asset(asset_id)
    with pytest.raises(ArtifactNotFoundError):
        await store.get_asset(asset_id)


async def test_bundle_and_asset_keys_share_one_namespace_by_uuid(
    store: ExtensionBundleStore,
) -> None:
    """Keys are row ids (uuid7, globally unique), so a bundle and an asset never
    collide; the wrapper adds no prefix that could leak into a response."""
    a, b = uuid7(), uuid7()
    await store.put_bundle(a, b"zip")
    await store.put_asset(b, b"md")
    assert await store.get_bundle(a) == b"zip"
    assert await store.get_asset(b) == b"md"


async def test_missing_bundle_raises_not_found(store: ExtensionBundleStore) -> None:
    with pytest.raises(ArtifactNotFoundError):
        await store.get_bundle(uuid.uuid4())


async def test_non_uuid_key_is_rejected_before_touching_storage(
    store: ExtensionBundleStore,
) -> None:
    """Defense in depth (CLAUDE.md §7): a key that is not a bare UUID — a path,
    a filename, an S3 prefix — never reaches the backend."""
    for bad in ("../etc/passwd", "bundle.zip", "", "not-a-uuid"):
        with pytest.raises(ValueError):
            await store.put_bundle(bad, b"x")
        with pytest.raises(ValueError):
            await store.get_asset(bad)


def test_backend_reports_the_underlying_store(store: ExtensionBundleStore) -> None:
    assert store.backend is ArtifactStorage.LOCAL
