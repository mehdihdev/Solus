"""Extension catalog READ routes (SOLUSDEV-235 / ADR-035, task EXT-06).

Pins `docs/api/extensions.md` §4.1 (list), §4.2 (detail), §4.3 (versions):
envelope + `(name, id)` cursor pagination, approved-only visibility with no
existence oracle for unreleased listings, case-insensitive slugs, `verified`
sourced from the row, relative API asset/bundle URLs, and the publisher-only
view of pending / checking / rejected versions.

Wiring note: the aggregator include (`extensions.router.include_router(
catalog.router)`) lands at integration; until then this suite mounts the
catalog router on the test app itself (see `catalog_app`).
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import ALICE, API_DIR, BOB, bearer
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.core.errors import APIError
from solus_api.extensions import catalog_service as svc
from solus_api.extensions.slugs import validate_extension_slug
from solus_api.models import (
    ArtifactStorage,
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
)
from solus_api.routers.extensions import catalog
from sqlalchemy.ext.asyncio import AsyncSession

MANIFEST_MINIMAL = (
    API_DIR.parent / "shared-types" / "fixtures" / "extension-manifest" / "manifest-minimal.json"
)
SHA256_HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
PUBLISHED_AT = datetime(2026, 9, 1, 9, 12, 3, tzinfo=UTC)
PUBLISHED_AT_JSON = "2026-09-01T09:12:03Z"  # pydantic json-mode spelling of UTC
LIST_ITEM_KEYS = {
    "slug",
    "name",
    "summary",
    "publisher",
    "verified",
    "install_count",
    "latest_version",
    "requires",
    "views",
    "updated_at",
}


def minimal_manifest(slug: str, semver: str = "0.1.0") -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(MANIFEST_MINIMAL.read_text())
    manifest["extension"]["id"] = slug
    manifest["extension"]["version"] = semver
    return manifest


def make_version(
    extension: Extension, semver: str, status: ExtensionReviewStatus, **overrides: Any
) -> ExtensionVersion:
    approved = status is ExtensionReviewStatus.APPROVED
    fields: dict[str, Any] = {
        "extension_id": extension.id,
        "version": semver,
        "manifest": minimal_manifest(extension.slug, semver),
        "bundle_storage": ArtifactStorage.LOCAL,
        "content_hash": SHA256_HEX,
        "bundle_size_bytes": 1024,
        "review_status": status,
        "published_at": PUBLISHED_AT if approved else None,
    }
    fields.update(overrides)
    return ExtensionVersion(**fields)


@dataclass(frozen=True)
class Seed:
    """alice publishes `bom` (approved 1.2.0 + 1.0.0, rejected 1.3.0, pending
    0.9.0, soft-deleted 1.1.0) and `hidden` (pending only); `carol` publishes
    `alpha` (approved, verified) — three catalog rows, two visible."""

    alice: User
    alice_publisher: ExtensionPublisher
    bom: Extension
    hidden: Extension
    alpha: Extension
    bom_latest: ExtensionVersion


async def seed_catalog(db: AsyncSession) -> Seed:
    alice = User(supabase_user_id=ALICE["sub"], email=ALICE["email"])
    carol = User(supabase_user_id="sub-carol", email="carol@example.com")
    db.add_all([alice, carol])
    await db.flush()
    alice_pub = ExtensionPublisher(user_id=alice.id, display_name="Ada")
    # Display name "Solus" but NOT verified — proves `verified` is never derived from it.
    carol_pub = ExtensionPublisher(user_id=carol.id, display_name="Solus")
    db.add_all([alice_pub, carol_pub])
    await db.flush()
    bom = Extension(
        slug="bom",
        publisher_id=alice_pub.id,
        name="BOM",
        summary="Bill of materials.",
        verified=True,
    )
    hidden = Extension(
        slug="hidden", publisher_id=alice_pub.id, name="Hidden", summary="Unreleased."
    )
    alpha = Extension(
        slug="alpha", publisher_id=carol_pub.id, name="Alpha", summary="First.", install_count=412
    )
    db.add_all([bom, hidden, alpha])
    await db.flush()
    bom_latest = make_version(bom, "1.2.0", ExtensionReviewStatus.APPROVED)
    versions = [
        bom_latest,
        make_version(bom, "1.0.0", ExtensionReviewStatus.APPROVED),
        make_version(
            bom,
            "1.3.0",
            ExtensionReviewStatus.REJECTED,
            review_problems=["store.screenshots[0]: too big"],
        ),
        make_version(bom, "0.9.0", ExtensionReviewStatus.PENDING),
        make_version(bom, "1.1.0", ExtensionReviewStatus.APPROVED, deleted_at=datetime.now(UTC)),
        make_version(hidden, "0.1.0", ExtensionReviewStatus.PENDING),
    ]
    alpha_latest = make_version(alpha, "2.0.0", ExtensionReviewStatus.APPROVED)
    db.add_all([*versions, alpha_latest])
    await db.flush()
    db.add(
        ExtensionVersionAsset(
            version_id=bom_latest.id,
            path="OVERVIEW.md",
            storage=ArtifactStorage.LOCAL,
            media_type="text/markdown; charset=utf-8",
            size_bytes=12,
        )
    )
    bom.latest_approved_version_id = bom_latest.id
    alpha.latest_approved_version_id = alpha_latest.id
    await db.commit()
    return Seed(alice, alice_pub, bom, hidden, alpha, bom_latest)


@pytest.fixture
def catalog_app(app: FastAPI) -> FastAPI:
    # The aggregator include is an integration-time edit to routers/extensions/__init__.py;
    # mount the catalog router directly so the routes are reachable here.
    app.include_router(catalog.router)
    return app


@pytest.fixture
async def client(catalog_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=catalog_app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def seed(db: AsyncSession) -> Seed:
    return await seed_catalog(db)


@pytest.fixture
def bob_headers() -> dict[str, str]:
    return bearer(BOB["sub"], BOB["email"])


# ------------------------------------------------------------------ auth
@pytest.mark.parametrize(
    "path", ["/api/v1/extensions", "/api/v1/extensions/bom", "/api/v1/extensions/bom/versions"]
)
async def test_catalog_routes_require_a_bearer_token(client: AsyncClient, path: str) -> None:
    resp = await client.get(path)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


# ------------------------------------------------------------------ §4.1 list
async def test_list_shows_only_extensions_with_an_approved_version(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions", headers=bob_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["slug"] for item in body["data"]] == ["alpha", "bom"]  # name ascending
    assert body["meta"] == {"limit": 24, "has_next": False, "next_cursor": None}
    bom = body["data"][1]
    assert set(bom) == LIST_ITEM_KEYS
    assert bom["publisher"] == {"display_name": "Ada"}
    assert bom["latest_version"] == {"version": "1.2.0", "published_at": PUBLISHED_AT_JSON}
    assert bom["requires"] == []
    assert bom["views"] == ["widget"]


async def test_list_item_verified_and_install_count_come_from_the_row(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions", headers=bob_headers)
    by_slug = {item["slug"]: item for item in resp.json()["data"]}
    assert by_slug["bom"]["verified"] is True
    assert by_slug["alpha"]["verified"] is False  # publisher display_name "Solus" grants nothing
    assert by_slug["alpha"]["install_count"] == 412  # cached column, no install rows exist


async def test_list_paginates_with_an_opaque_cursor_over_name_and_id(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    first = await client.get("/api/v1/extensions", params={"limit": 1}, headers=bob_headers)
    assert first.status_code == 200, first.text
    meta = first.json()["meta"]
    assert meta["has_next"] is True and meta["limit"] == 1
    assert isinstance(meta["next_cursor"], str) and "alpha" not in meta["next_cursor"].lower()

    second = await client.get(
        "/api/v1/extensions",
        params={"limit": 1, "cursor": meta["next_cursor"]},
        headers=bob_headers,
    )
    assert second.status_code == 200, second.text
    assert [i["slug"] for i in first.json()["data"]] == ["alpha"]
    assert [i["slug"] for i in second.json()["data"]] == ["bom"]
    assert second.json()["meta"] == {"limit": 1, "has_next": False, "next_cursor": None}


async def test_list_rejects_a_malformed_cursor(
    client: AsyncClient, bob_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions", params={"cursor": "!!"}, headers=bob_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("BILL", ["bom"]),  # summary, case-insensitive
        ("alp", ["alpha"]),  # name / slug
        ("hidden", []),  # unreleased never surfaces through search
        ("%", []),  # LIKE wildcards are literal
        ("_", []),
    ],
)
async def test_list_q_matches_slug_name_summary_case_insensitively(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str], q: str, expected: list[str]
) -> None:
    resp = await client.get("/api/v1/extensions", params={"q": q}, headers=bob_headers)
    assert resp.status_code == 200, resp.text
    assert [item["slug"] for item in resp.json()["data"]] == expected


@pytest.mark.parametrize(
    "params", [{"q": "x" * 81}, {"limit": 0}, {"limit": 101}, {"limit": "many"}]
)
async def test_list_validates_query_parameters(
    client: AsyncClient, bob_headers: dict[str, str], params: dict[str, Any]
) -> None:
    resp = await client.get("/api/v1/extensions", params=params, headers=bob_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------- §4.2 detail
async def test_detail_matches_the_slug_case_insensitively(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions/BOM", headers=bob_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["slug"] == "bom"
    assert data["verified"] is True
    assert data["publisher"] == {"display_name": "Ada"}
    assert data["version"] == {
        "version": "1.2.0",
        "published_at": PUBLISHED_AT_JSON,
        "content_hash": SHA256_HEX,
        "bundle_size_bytes": 1024,
        "bundle_url": "/api/v1/extensions/bom/versions/1.2.0/bundle",
    }
    assert data["manifest"] == seed.bom_latest.manifest


async def test_detail_asset_urls_are_relative_api_routes_for_recorded_paths_only(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions/bom", headers=bob_headers)
    assert resp.json()["data"]["assets"] == {
        "overview": "/api/v1/extensions/bom/versions/1.2.0/assets/OVERVIEW.md",
        "privacy_policy": None,
        "icon": None,
        "screenshots": [],
        "sections": [],
    }
    text = resp.text
    for locator in ("s3://", "storage_key", str(seed.bom_latest.id), "local"):
        assert locator not in text


@pytest.mark.parametrize("slug", ["nope", "hidden"])
async def test_detail_is_404_for_unknown_and_unreleased_slugs_to_non_publishers(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str], slug: str
) -> None:
    resp = await client.get(f"/api/v1/extensions/{slug}", headers=bob_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_detail_of_a_soft_deleted_extension_is_404(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    seed.bom.deleted_at = datetime.now(UTC)
    await db.commit()
    resp = await client.get("/api/v1/extensions/bom", headers=alice_headers)
    assert resp.status_code == 404
    listed = await client.get("/api/v1/extensions", headers=alice_headers)
    assert [i["slug"] for i in listed.json()["data"]] == ["alpha"]


async def test_detail_publisher_sees_own_unreleased_listing_with_null_version(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions/hidden", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["slug"] == "hidden"
    assert data["version"] is None and data["manifest"] is None and data["assets"] is None


@pytest.mark.parametrize("slug", ["1abc", "Bad_Slug", "a", "x" * 65, "a.b"])
async def test_detail_rejects_a_malformed_slug_before_any_lookup(
    client: AsyncClient, bob_headers: dict[str, str], slug: str
) -> None:
    resp = await client.get(f"/api/v1/extensions/{slug}", headers=bob_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# -------------------------------------------------------------- §4.3 versions
async def test_versions_for_a_stranger_are_approved_live_only_newest_first(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions/bom/versions", headers=bob_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [v["version"] for v in body["data"]] == ["1.2.0", "1.0.0"]  # 1.1.0 soft-deleted
    assert body["meta"] == {"limit": 24, "has_next": False, "next_cursor": None}
    item = body["data"][0]
    assert "review_problems" not in item
    assert item["review_status"] == "approved"
    assert item["content_hash"] == SHA256_HEX
    assert item["bundle_size_bytes"] == 1024
    assert item["published_at"] == PUBLISHED_AT_JSON


async def test_versions_for_the_publisher_include_pending_and_rejected(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions/bom/versions", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [v["version"] for v in data] == ["1.3.0", "1.2.0", "1.0.0", "0.9.0"]
    by_version = {v["version"]: v for v in data}
    assert by_version["1.3.0"]["review_status"] == "rejected"
    assert by_version["1.3.0"]["review_problems"] == ["store.screenshots[0]: too big"]
    assert by_version["1.3.0"]["published_at"] is None
    assert by_version["0.9.0"]["review_status"] == "pending"
    assert "review_problems" not in by_version["0.9.0"]  # only when rejected
    assert "review_problems" not in by_version["1.2.0"]


async def test_versions_paginate_with_a_cursor_round_trip(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str]
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, Any] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get(
            "/api/v1/extensions/bom/versions", params=params, headers=alice_headers
        )
        assert resp.status_code == 200, resp.text
        seen.extend(v["version"] for v in resp.json()["data"])
        cursor = resp.json()["meta"]["next_cursor"]
        if not resp.json()["meta"]["has_next"]:
            break
    assert seen == ["1.3.0", "1.2.0", "1.0.0", "0.9.0"]
    assert cursor is None


async def test_versions_of_an_unreleased_extension_leak_nothing_to_a_stranger(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str], alice_headers: dict[str, str]
) -> None:
    stranger = await client.get("/api/v1/extensions/hidden/versions", headers=bob_headers)
    assert stranger.status_code == 404
    assert stranger.json()["error"]["code"] == "not_found"
    publisher = await client.get("/api/v1/extensions/hidden/versions", headers=alice_headers)
    assert publisher.status_code == 200, publisher.text
    assert [v["version"] for v in publisher.json()["data"]] == ["0.1.0"]


async def test_versions_reject_malformed_cursor_and_slug(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str]
) -> None:
    bad_cursor = await client.get(
        "/api/v1/extensions/bom/versions", params={"cursor": "!!"}, headers=bob_headers
    )
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error"]["code"] == "invalid_cursor"
    bad_slug = await client.get("/api/v1/extensions/-bad/versions", headers=bob_headers)
    assert bad_slug.status_code == 422


# ------------------------------------------------------------ service units
def test_semver_key_orders_releases_and_prereleases() -> None:
    versions = ["1.0.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-beta", "0.9.9", "1.10.0", "1.2.0"]
    ordered = sorted(versions, key=svc.semver_key, reverse=True)
    assert ordered == [
        "1.10.0",
        "1.2.0",
        "1.0.0",
        "1.0.0-beta",
        "1.0.0-alpha.1",
        "1.0.0-alpha",
        "0.9.9",
    ]


def test_semver_key_tolerates_a_non_semver_string() -> None:
    # Stored versions are contract-validated; a stray value must still sort deterministically.
    assert svc.semver_key("garbage") < svc.semver_key("0.0.1")


def test_cursor_codec_round_trips_and_rejects_garbage() -> None:
    item_id = uuid.uuid4()
    cursor = svc.encode_cursor(["BOM", str(item_id)])
    assert "=" not in cursor
    assert svc.decode_cursor(cursor, 2) == ["BOM", str(item_id)]
    for bad in ("!!", svc.encode_cursor(["only-one"]), "e30"):  # e30 == "{}"
        with pytest.raises(APIError) as excinfo:
            svc.decode_cursor(bad, 2)
        assert excinfo.value.status_code == 400
        assert excinfo.value.code == "invalid_cursor"


def test_validate_slug_normalizes_case_and_rejects_bad_syntax() -> None:
    """One validator for every `{slug}` (Phase 4 REV-MEDIUM): `BOM` normalizes to
    `bom`; garbage and the contract's reserved ids are 422 before any lookup."""
    assert validate_extension_slug("BOM") == "bom"
    assert validate_extension_slug("bom") == "bom"
    for bad in ("1abc", "a", "-x", "a_b", "x" * 65, "constructor", "__proto__", "Prototype"):
        with pytest.raises(APIError) as excinfo:
            validate_extension_slug(bad)
        assert excinfo.value.status_code == 422
        assert excinfo.value.code == "validation_error"


@pytest.mark.parametrize("slug", ["constructor", "__proto__", "prototype"])
async def test_reserved_slugs_are_422_on_the_catalog_routes(
    client: AsyncClient, bob_headers: dict[str, str], slug: str
) -> None:
    for url in (f"/api/v1/extensions/{slug}", f"/api/v1/extensions/{slug}/versions"):
        resp = await client.get(url, headers=bob_headers)
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "validation_error"
