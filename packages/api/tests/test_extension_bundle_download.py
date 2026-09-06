"""GET …/versions/{version}/bundle and GET …/versions/{version}/assets/{path}
(SOLUSDEV-235 EXT-07; docs/api/extensions.md §4.4, §4.5, §12, §14).

The visibility matrix (approved → anyone signed in; pending/checking/rejected →
the publisher only; soft-deleted → nobody; never a 403), the response headers
the desktop installer verifies against, the per-user download budget, and the
asset table as the ONLY thing the asset route will serve.
"""

import hashlib
import io
import uuid
from typing import Any

import pytest
from conftest import me
from fastapi import FastAPI
from fixtures.extensions import VALID_ICON_SVG, build_zip, minimal_files
from httpx import AsyncClient, Response
from solus_api.models import (
    ArtifactStorage,
    DataEvent,
    Extension,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
    utcnow,
)
from solus_api.routers.extensions import bundle, publish
from solus_api.storage.extension_bundle_store import ExtensionBundleStore
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

BUNDLE_URL = "/api/v1/extensions/bom-lite/versions/1.0.0/bundle"
ASSET_URL = "/api/v1/extensions/bom-lite/versions/1.0.0/assets/"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    # EXT-07 owns only its sub-routers; the aggregator include lands at
    # integration (orchestrator), so this suite mounts them directly.
    app.include_router(publish.router)
    app.include_router(bundle.router)
    return app


# ------------------------------------------------------------------ helpers
async def _publish(client: AsyncClient, headers: dict[str, str], data: bytes) -> Response:
    return await client.post(
        "/api/v1/extensions/publish",
        files={"bundle": ("bundle.zip", io.BytesIO(data), "application/zip")},
        headers={**headers, "Idempotency-Key": "k"},
    )


async def _version(db: AsyncSession) -> ExtensionVersion:
    db.expire_all()
    row = await db.scalar(select(ExtensionVersion))
    assert row is not None
    return row


async def _set_status(db: AsyncSession, status: ExtensionReviewStatus) -> None:
    row = await _version(db)
    row.review_status = status
    await db.commit()


async def _soft_delete(db: AsyncSession) -> None:
    row = await _version(db)
    row.deleted_at = utcnow()
    await db.commit()


async def _add_asset(
    db: AsyncSession, app: FastAPI, path: str, media_type: str, data: bytes
) -> ExtensionVersionAsset:
    row = await _version(db)
    asset = ExtensionVersionAsset(
        version_id=row.id,
        path=path,
        storage=ArtifactStorage.LOCAL,
        media_type=media_type,
        size_bytes=len(data),
    )
    await ExtensionBundleStore(app.state.artifact_store).put_asset(asset.storage_key, data)
    db.add(asset)
    await db.commit()
    return asset


async def _published(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> bytes:
    data = build_zip(minimal_files())
    assert (await _publish(client, alice_headers, data)).status_code == 202
    await me(client, bob_headers)
    return data


# -------------------------------------------------------------------- bundle
async def test_publisher_downloads_own_pending_bundle_with_verifiable_headers(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    data = await _published(client, alice_headers, bob_headers)
    resp = await client.get(BUNDLE_URL, headers=alice_headers)
    assert resp.status_code == 200
    assert resp.content == data
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-length"] == str(len(data))
    assert resp.headers["x-solus-content-hash"] == hashlib.sha256(data).hexdigest()
    # Phase 4 M6: never sniffed, always a download named after the version.
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-disposition"] == 'attachment; filename="bom-lite-1.0.0.zip"'


@pytest.mark.parametrize(
    "status",
    [ExtensionReviewStatus.PENDING, ExtensionReviewStatus.CHECKING, ExtensionReviewStatus.REJECTED],
)
async def test_unapproved_bundle_is_404_to_a_non_publisher_never_403(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    status: ExtensionReviewStatus,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _set_status(db, status)
    assert (await client.get(BUNDLE_URL, headers=alice_headers)).status_code == 200
    resp = await client.get(BUNDLE_URL, headers=bob_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_approved_bundle_is_visible_to_anyone_signed_in(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _set_status(db, ExtensionReviewStatus.APPROVED)
    assert (await client.get(BUNDLE_URL, headers=bob_headers)).status_code == 200
    assert (await client.get(BUNDLE_URL)).status_code == 401


async def test_soft_deleted_bundle_is_404_for_everyone(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _set_status(db, ExtensionReviewStatus.APPROVED)
    await _soft_delete(db)
    assert (await client.get(BUNDLE_URL, headers=alice_headers)).status_code == 404
    assert (await client.get(BUNDLE_URL, headers=bob_headers)).status_code == 404


async def test_unknown_slug_or_version_is_404(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await _published(client, alice_headers, bob_headers)
    for url in (
        "/api/v1/extensions/nope/versions/1.0.0/bundle",
        BUNDLE_URL.replace("1.0.0", "9.9.9"),
    ):
        assert (await client.get(url, headers=alice_headers)).status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/extensions/-bom-lite/versions/1.0.0/bundle",
        "/api/v1/extensions/bom-lite/versions/v1/bundle",
    ],
)
async def test_bad_slug_or_version_syntax_is_422(
    client: AsyncClient, alice_headers: dict[str, str], url: str
) -> None:
    resp = await client.get(url, headers=alice_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_bundle_download_rate_limit_is_429_with_retry_after(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str], app: FastAPI
) -> None:
    await _published(client, alice_headers, bob_headers)
    app.state.settings.extension_bundle_downloads_per_minute_per_user = 1
    assert (await client.get(BUNDLE_URL, headers=alice_headers)).status_code == 200
    resp = await client.get(BUNDLE_URL, headers=alice_headers)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert resp.headers["Retry-After"] == "60"


async def test_bundle_whose_bytes_are_gone_is_404_without_storage_detail(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    await _published(client, alice_headers, bob_headers)
    row = await _version(db)
    await ExtensionBundleStore(app.state.artifact_store).delete_bundle(row.id)
    resp = await client.get(BUNDLE_URL, headers=alice_headers)
    assert resp.status_code == 404
    assert str(app.state.artifact_store.root) not in resp.text


# -------------------------------------------------------------------- assets
async def test_asset_download_rate_limit_is_429_with_retry_after_and_event(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    """Phase 4 L3: the asset route rides its own per-user window, not just the
    global limiter; the refusal is a data event like every other §12 429."""
    await _published(client, alice_headers, bob_headers)
    await db.execute(
        update(User).where(User.email == "alice@example.com").values(data_collection_consent=True)
    )
    await db.commit()
    await _add_asset(db, app, "OVERVIEW.md", "text/markdown", b"# Overview\n")
    app.state.settings.extension_asset_downloads_per_minute_per_user = 1
    assert (await client.get(ASSET_URL + "OVERVIEW.md", headers=alice_headers)).status_code == 200
    resp = await client.get(ASSET_URL + "OVERVIEW.md", headers=alice_headers)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert resp.headers["Retry-After"] == "60"
    # Bob's window is his own.
    await _set_status(db, ExtensionReviewStatus.APPROVED)
    assert (await client.get(ASSET_URL + "OVERVIEW.md", headers=bob_headers)).status_code == 200
    event = await db.scalar(
        select(DataEvent).where(DataEvent.event_type == "extension.rate_limited")
    )
    assert event is not None and event.payload == {"route": "asset"}


async def test_recorded_markdown_asset_is_served_with_hardening_headers(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _set_status(db, ExtensionReviewStatus.APPROVED)
    await _add_asset(db, app, "OVERVIEW.md", "text/markdown", b"# Overview\n")

    resp = await client.get(ASSET_URL + "OVERVIEW.md", headers=bob_headers)
    assert resp.status_code == 200
    assert resp.content == b"# Overview\n"
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert resp.headers["content-length"] == str(len(b"# Overview\n"))
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cache-control"] == "private, max-age=86400, immutable"
    assert "content-security-policy" not in resp.headers


async def test_svg_asset_carries_a_no_script_csp(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _add_asset(db, app, "icon.svg", "image/svg+xml", VALID_ICON_SVG)
    resp = await client.get(ASSET_URL + "icon.svg", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"
    assert (
        resp.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    )
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_nested_asset_path_matches_the_whole_recorded_string(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _add_asset(db, app, "shots/table.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"\0" * 8)
    assert (
        await client.get(ASSET_URL + "shots/table.png", headers=alice_headers)
    ).status_code == 200
    assert (await client.get(ASSET_URL + "table.png", headers=alice_headers)).status_code == 404
    assert (
        await client.get(ASSET_URL + "shots/TABLE.png", headers=alice_headers)
    ).status_code == 404


@pytest.mark.parametrize("path", ["widget.html", "app.js", "extension.toml", "..%2FOVERVIEW.md"])
async def test_paths_in_the_zip_but_not_in_the_asset_table_are_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    path: str,
) -> None:
    """Entry HTML/JS and the manifest are in the bundle but never extracted as
    assets — the route consults ONLY `extension_version_assets`, never the zip."""
    await _published(client, alice_headers, bob_headers)
    await _set_status(db, ExtensionReviewStatus.APPROVED)
    await _add_asset(db, app, "OVERVIEW.md", "text/markdown", b"# Overview\n")
    resp = await client.get(ASSET_URL + path, headers=alice_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_asset_of_an_unapproved_version_is_404_to_a_non_publisher(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    await _published(client, alice_headers, bob_headers)
    await _add_asset(db, app, "OVERVIEW.md", "text/markdown", b"# Overview\n")
    assert (await client.get(ASSET_URL + "OVERVIEW.md", headers=alice_headers)).status_code == 200
    assert (await client.get(ASSET_URL + "OVERVIEW.md", headers=bob_headers)).status_code == 404


async def test_asset_from_another_version_is_not_served(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    """The asset lookup is keyed by THIS version's id: a row recorded for a
    sibling version of the same extension does not answer for 1.0.0."""
    await _published(client, alice_headers, bob_headers)
    ext = await db.scalar(select(Extension))
    assert ext is not None
    sibling = ExtensionVersion(
        extension_id=ext.id,
        version="1.1.0",
        manifest={"schema_version": 1},
        bundle_storage=ArtifactStorage.LOCAL,
        content_hash="0" * 64,
        bundle_size_bytes=1,
    )
    db.add(sibling)
    await db.flush()
    asset = ExtensionVersionAsset(
        version_id=sibling.id, path="OVERVIEW.md", storage=ArtifactStorage.LOCAL,
        media_type="text/markdown", size_bytes=3,
    )  # fmt: skip
    await ExtensionBundleStore(app.state.artifact_store).put_asset(asset.storage_key, b"sib")
    db.add(asset)
    await db.commit()
    assert (await client.get(ASSET_URL + "OVERVIEW.md", headers=alice_headers)).status_code == 404


async def test_no_response_body_ever_carries_a_storage_locator(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    await _published(client, alice_headers, bob_headers)
    asset = await _add_asset(db, app, "OVERVIEW.md", "text/markdown", b"# Overview\n")
    root = str(app.state.artifact_store.root)
    responses: list[Any] = [
        await client.get(BUNDLE_URL, headers=bob_headers),
        await client.get(ASSET_URL + "OVERVIEW.md", headers=bob_headers),
        await client.get(ASSET_URL + "missing.md", headers=alice_headers),
        await client.get(ASSET_URL + "OVERVIEW.md", headers=alice_headers),
    ]
    for resp in responses:
        assert root not in resp.text
        assert str(asset.storage_key) not in resp.headers.values()
    assert uuid.UUID(str(asset.storage_key))  # sanity: the key is a bare UUID, never a path
