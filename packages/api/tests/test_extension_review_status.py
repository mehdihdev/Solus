"""Review-status and verified-badge routes (SOLUSDEV-235 / ADR-035, EXT-08).

docs/api/extensions.md §5.2 — `GET …/versions/{version}/review` is publisher-only
(everyone else `404`, no existence oracle); §5.4 — `PATCH /extensions/{slug}` is
`RequireStaff` (+ `RequireVerified`), body exactly `{verified: bool}`, returns the
§4.2 detail shape and emits `extension.verified_changed`. The sub-router is mounted
directly on the app here; the aggregator include lands at integration.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import ALICE, BOB, TEST_DATABASE_URL, TEST_JWT_SECRET, bearer
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.agent.runtime import ScaffoldRunner
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.models import (
    ArtifactStorage,
    DataEvent,
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
)
from solus_api.routers.extensions import review as review_router
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

STAFF_ID = uuid.UUID("00000000-0000-0000-0000-00000000f00d")
STAFF_SUB = "staff-sub"
STAFF_EMAIL = "staff@solus.test"
SHA256_HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
PROBLEMS = ["bundle: vendor/helper.wasm has a disallowed asset type"]


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience="authenticated",
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        sync_inline=True,
        public_api_base_url="http://testserver",
        staff_user_ids=str(STAFF_ID),
    )


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    application = create_app(settings=settings, engine=engine)
    application.state.agent_runner = ScaffoldRunner()
    application.include_router(review_router.router)
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@dataclass(frozen=True)
class Seeded:
    publisher_user: User
    staff_user: User
    extension: Extension
    version: ExtensionVersion


@pytest.fixture
async def seeded(db: AsyncSession) -> Seeded:
    alice = User(supabase_user_id=ALICE["sub"], email=ALICE["email"], data_collection_consent=True)
    bob = User(supabase_user_id=BOB["sub"], email=BOB["email"])
    staff = User(
        id=STAFF_ID,
        supabase_user_id=STAFF_SUB,
        email=STAFF_EMAIL,
        data_collection_consent=True,
    )
    db.add_all([alice, bob, staff])
    await db.flush()
    publisher = ExtensionPublisher(user_id=alice.id, display_name="Ada")
    db.add(publisher)
    await db.flush()
    extension = Extension(slug="bom", publisher_id=publisher.id, name="BOM", summary="Bill.")
    db.add(extension)
    await db.flush()
    version = _version(extension.id, "1.3.0", ExtensionReviewStatus.REJECTED, PROBLEMS)
    db.add(version)
    await db.commit()
    return Seeded(alice, staff, extension, version)


def _version(
    extension_id: uuid.UUID,
    semver: str,
    status: ExtensionReviewStatus,
    problems: list[str] | None = None,
    **overrides: Any,
) -> ExtensionVersion:
    fields: dict[str, Any] = {
        "extension_id": extension_id,
        "version": semver,
        "manifest": {"schema_version": 1, "extension": {"id": "bom", "version": semver}},
        "bundle_storage": ArtifactStorage.LOCAL,
        "content_hash": SHA256_HEX,
        "bundle_size_bytes": 1024,
        "review_status": status,
        "review_problems": problems or [],
    }
    fields.update(overrides)
    return ExtensionVersion(**fields)


def staff_headers(**kwargs: Any) -> dict[str, str]:
    headers: dict[str, str] = bearer(STAFF_SUB, STAFF_EMAIL, **kwargs)
    return headers


REVIEW = "/api/v1/extensions/bom/versions/1.3.0/review"
PATCH = "/api/v1/extensions/bom"


# ------------------------------------------------------------ GET review
async def test_publisher_sees_status_and_problems(
    client: AsyncClient, seeded: Seeded, alice_headers: dict[str, str]
) -> None:
    resp = await client.get(REVIEW, headers=alice_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["slug"] == "bom"
    assert data["version"] == "1.3.0"
    assert data["review_status"] == "rejected"
    assert data["review_problems"] == PROBLEMS
    assert data["published_at"] is None


async def test_publisher_sees_a_pending_version_with_empty_problems(
    client: AsyncClient, db: AsyncSession, seeded: Seeded, alice_headers: dict[str, str]
) -> None:
    db.add(_version(seeded.extension.id, "1.4.0", ExtensionReviewStatus.PENDING))
    await db.commit()

    resp = await client.get("/api/v1/extensions/bom/versions/1.4.0/review", headers=alice_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["review_status"] == "pending"
    assert resp.json()["data"]["review_problems"] == []


async def test_slug_lookup_is_case_insensitive(
    client: AsyncClient, seeded: Seeded, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/extensions/BOM/versions/1.3.0/review", headers=alice_headers)
    assert resp.status_code == 200, resp.text


async def test_stranger_gets_404_not_403(
    client: AsyncClient, seeded: Seeded, bob_headers: dict[str, str]
) -> None:
    resp = await client.get(REVIEW, headers=bob_headers)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_staff_are_not_publishers_for_review_reads(
    client: AsyncClient, seeded: Seeded
) -> None:
    resp = await client.get(REVIEW, headers=staff_headers())
    assert resp.status_code == 404


async def test_unknown_version_and_slug_are_404(
    client: AsyncClient, seeded: Seeded, alice_headers: dict[str, str]
) -> None:
    missing_version = await client.get(
        "/api/v1/extensions/bom/versions/9.9.9/review", headers=alice_headers
    )
    missing_slug = await client.get(
        "/api/v1/extensions/nope/versions/1.3.0/review", headers=alice_headers
    )
    assert missing_version.status_code == 404
    assert missing_slug.status_code == 404


async def test_withdrawn_version_is_404_even_to_the_publisher(
    client: AsyncClient, db: AsyncSession, seeded: Seeded, alice_headers: dict[str, str]
) -> None:
    seeded.version.deleted_at = datetime.now(UTC)
    await db.commit()

    resp = await client.get(REVIEW, headers=alice_headers)
    assert resp.status_code == 404


@pytest.mark.parametrize("slug", ["Bad_Slug", "1abc", "a", "x" * 65, "__proto__"])
async def test_malformed_slug_is_422_before_any_lookup(
    client: AsyncClient, seeded: Seeded, alice_headers: dict[str, str], slug: str
) -> None:
    resp = await client.get(
        f"/api/v1/extensions/{slug}/versions/1.3.0/review", headers=alice_headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_review_requires_authentication(client: AsyncClient, seeded: Seeded) -> None:
    resp = await client.get(REVIEW)
    assert resp.status_code == 401


# ---------------------------------------------------------- PATCH verified
async def test_staff_can_flip_verified_and_get_the_detail_shape(
    client: AsyncClient, db: AsyncSession, seeded: Seeded
) -> None:
    resp = await client.patch(PATCH, json={"verified": True}, headers=staff_headers())

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["slug"] == "bom"
    assert data["verified"] is True
    assert data["publisher"] == {"display_name": "Ada"}
    assert data["version"] is None and data["manifest"] is None and data["assets"] is None
    assert set(data) >= {"name", "summary", "install_count", "created_at", "updated_at"}

    await db.refresh(seeded.extension)
    row = seeded.extension
    assert row is not None and row.verified is True

    off = await client.patch(PATCH, json={"verified": False}, headers=staff_headers())
    assert off.status_code == 200 and off.json()["data"]["verified"] is False


async def test_patch_returns_latest_version_and_recorded_assets(
    client: AsyncClient, db: AsyncSession, seeded: Seeded
) -> None:
    approved = _version(
        seeded.extension.id,
        "1.2.0",
        ExtensionReviewStatus.APPROVED,
        published_at=datetime.now(UTC),
        manifest={
            "schema_version": 1,
            "extension": {"id": "bom", "version": "1.2.0"},
            "store": {"overview": "OVERVIEW.md", "screenshots": ["shots/table.png"]},
        },
    )
    db.add(approved)
    await db.flush()
    db.add(
        ExtensionVersionAsset(
            version_id=approved.id,
            path="OVERVIEW.md",
            storage=ArtifactStorage.LOCAL,
            media_type="text/markdown",
            size_bytes=10,
        )
    )
    seeded.extension.latest_approved_version_id = approved.id
    await db.commit()

    resp = await client.patch(PATCH, json={"verified": True}, headers=staff_headers())

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["version"]["version"] == "1.2.0"
    assert data["version"]["bundle_url"] == "/api/v1/extensions/bom/versions/1.2.0/bundle"
    assert data["assets"]["overview"] == "/api/v1/extensions/bom/versions/1.2.0/assets/OVERVIEW.md"
    assert data["assets"]["screenshots"] == []  # not recorded → not a URL


async def test_patch_emits_verified_changed_event(
    client: AsyncClient, db: AsyncSession, seeded: Seeded
) -> None:
    resp = await client.patch(PATCH, json={"verified": True}, headers=staff_headers())
    assert resp.status_code == 200, resp.text

    events = list(
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "extension.verified_changed")
        )
    )
    assert len(events) == 1
    assert events[0].user_id == seeded.staff_user.id
    assert events[0].payload == {"slug": "bom", "verified": True}
    assert events[0].team_id is None and events[0].project_id is None


async def test_publisher_is_forbidden_from_patching_their_own_extension(
    client: AsyncClient, db: AsyncSession, seeded: Seeded, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(PATCH, json={"verified": True}, headers=alice_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    await db.refresh(seeded.extension)
    row = seeded.extension
    assert row is not None and row.verified is False


async def test_stranger_is_forbidden_from_patching(
    client: AsyncClient, seeded: Seeded, bob_headers: dict[str, str]
) -> None:
    resp = await client.patch(PATCH, json={"verified": True}, headers=bob_headers)
    assert resp.status_code == 403


async def test_unverified_staff_email_is_refused(client: AsyncClient, seeded: Seeded) -> None:
    resp = await client.patch(
        PATCH, json={"verified": True}, headers=staff_headers(email_verified=False)
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


@pytest.mark.parametrize(
    "body",
    [
        {"verified": True, "name": "Renamed"},
        {"verified": True, "summary": "x"},
        {"verified": True, "publisher": {"display_name": "Eve"}},
        {"name": "Renamed"},
        {},
        {"verified": "yes"},
    ],
)
async def test_unknown_or_malformed_body_is_422(
    client: AsyncClient, seeded: Seeded, body: dict[str, Any]
) -> None:
    resp = await client.patch(PATCH, json=body, headers=staff_headers())
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_patch_unknown_slug_is_404(client: AsyncClient, seeded: Seeded) -> None:
    resp = await client.patch(
        "/api/v1/extensions/nope", json={"verified": True}, headers=staff_headers()
    )
    assert resp.status_code == 404


async def test_patch_malformed_slug_is_422(client: AsyncClient, seeded: Seeded) -> None:
    resp = await client.patch(
        "/api/v1/extensions/Not_Valid", json={"verified": True}, headers=staff_headers()
    )
    assert resp.status_code == 422


async def test_patch_requires_authentication(client: AsyncClient, seeded: Seeded) -> None:
    resp = await client.patch(PATCH, json={"verified": True})
    assert resp.status_code == 401
