"""Team extension policy routes (SOLUSDEV-235 / ADR-035, task EXT-10).

Pins docs/api/extensions.md §10: `TeamCtx` + owner floor, the PUT body shape and
its 422s, `default_settings` validation against the latest approved manifest,
the block effect on every install in the team's projects (and on no other
team's), the "unblock does not re-enable" rule, DELETE as reset, the §11 events
and the §12 per-team write budget.

The policy router is mounted on the test app here because the aggregator
include lands at integration (guarded so a wired aggregator is not mounted twice).
"""

import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import ALICE, API_DIR, BOB, add_member, bearer, create_project, create_team, me
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.extensions.policy import DEFAULT_SETTINGS_MAX_BYTES, validate_default_settings
from solus_api.main import create_app
from solus_api.models import (
    ArtifactStorage,
    DataEvent,
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    TeamExtensionPolicy,
    User,
)
from solus_api.routers.extensions import policy as policy_router
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

MANIFEST_PATH = (
    API_DIR.parent.parent / "packages/shared-types/fixtures/extension-manifest/manifest-full.json"
)
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text())
SHA256_HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

CAROL = {"sub": "00000000-0000-0000-0000-0000000000c4", "email": "carol@example.com"}
DAVE = {"sub": "00000000-0000-0000-0000-0000000000d4", "email": "dave@example.com"}

VALID_SETTINGS = {"refresh": "hourly", "flag_eol": False, "max_rows": 50, "vendor": "Digi-Key"}


# ------------------------------------------------------------------ helpers
def _mount(application: FastAPI) -> FastAPI:
    prefix = policy_router.router.prefix
    if not any(str(getattr(r, "path", "")).startswith(prefix) for r in application.routes):
        application.include_router(policy_router.router)
    return application


def _url(team_id: str, slug: str | None = None) -> str:
    base = f"/api/v1/teams/{team_id}/extensions/policies"
    return f"{base}/{slug}" if slug else base


def _manifest(slug: str) -> dict[str, Any]:
    manifest = deepcopy(MANIFEST)
    manifest["extension"]["id"] = slug
    return manifest


async def seed_extension(
    db: AsyncSession, manifest: dict[str, Any], *, approved: bool = True
) -> tuple[Extension, ExtensionVersion]:
    publisher = ExtensionPublisher(display_name=manifest["extension"]["publisher"])
    db.add(publisher)
    await db.flush()
    extension = Extension(
        slug=manifest["extension"]["id"],
        publisher_id=publisher.id,
        name=manifest["extension"]["name"],
        summary=manifest["extension"]["summary"][:160],
    )
    db.add(extension)
    await db.flush()
    version = ExtensionVersion(
        extension_id=extension.id,
        version=manifest["extension"]["version"],
        manifest=manifest,
        bundle_storage=ArtifactStorage.LOCAL,
        content_hash=SHA256_HEX,
        bundle_size_bytes=1024,
        review_status=ExtensionReviewStatus.APPROVED if approved else ExtensionReviewStatus.PENDING,
        published_at=datetime.now(UTC) if approved else None,
    )
    db.add(version)
    await db.flush()
    if approved:
        extension.latest_approved_version_id = version.id
    await db.commit()
    return extension, version


@dataclass(frozen=True)
class Seed:
    alice_id: str
    team_id: str
    other_team_id: str
    projects: tuple[str, str]
    other_project: str
    extension: Extension
    version: ExtensionVersion


async def build_seed(client: AsyncClient, db: AsyncSession) -> Seed:
    """Alice owns a team with Carol (admin), Dave (member) and two projects; Bob
    owns a second team with one project. `bom` is approved and installed in all
    three projects."""
    alice_headers = bearer(ALICE["sub"], ALICE["email"])
    bob_headers = bearer(BOB["sub"], BOB["email"])
    alice = await me(client, alice_headers)
    await db.execute(
        update(User).where(User.id == uuid.UUID(alice["id"])).values(data_collection_consent=True)
    )
    await db.commit()
    team = await create_team(client, alice_headers)
    await add_member(
        client, alice_headers, bearer(CAROL["sub"], CAROL["email"]), CAROL, team["id"], role="admin"
    )
    await add_member(client, alice_headers, bearer(DAVE["sub"], DAVE["email"]), DAVE, team["id"])
    rover = await create_project(client, alice_headers, team["id"], "Rover")
    arm = await create_project(client, alice_headers, team["id"], "Arm")
    other_team = await create_team(client, bob_headers, "Other")
    drone = await create_project(client, bob_headers, other_team["id"], "Drone")

    extension, version = await seed_extension(db, MANIFEST)
    for project in (rover, arm, drone):
        db.add(
            ExtensionInstall(
                project_id=uuid.UUID(project["id"]),
                extension_id=extension.id,
                version_id=version.id,
                granted_scopes=["graph.read"],
            )
        )
    await db.commit()
    return Seed(
        alice_id=alice["id"],
        team_id=team["id"],
        other_team_id=other_team["id"],
        projects=(rover["id"], arm["id"]),
        other_project=drone["id"],
        extension=extension,
        version=version,
    )


async def install_enabled(db: AsyncSession, project_id: str) -> bool:
    db.expire_all()
    enabled = await db.scalar(
        select(ExtensionInstall.enabled).where(ExtensionInstall.project_id == uuid.UUID(project_id))
    )
    assert enabled is not None
    return enabled


async def events(db: AsyncSession, event_type: str) -> list[DataEvent]:
    db.expire_all()
    rows = await db.scalars(
        select(DataEvent).where(DataEvent.event_type == event_type).order_by(DataEvent.created_at)
    )
    return list(rows.all())


# ----------------------------------------------------------------- fixtures
@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return _mount(create_app(settings=settings, engine=engine))


@pytest.fixture
async def seed(client: AsyncClient, db: AsyncSession) -> Seed:
    return await build_seed(client, db)


@pytest.fixture
def carol_headers() -> dict[str, str]:
    return bearer(CAROL["sub"], CAROL["email"])


@pytest.fixture
def dave_headers() -> dict[str, str]:
    return bearer(DAVE["sub"], DAVE["email"])


# ----------------------------------------------------------------- GET list
async def test_owner_lists_an_empty_policy_set(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str]
) -> None:
    resp = await client.get(_url(seed.team_id), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["has_next"] is False
    assert body["meta"]["next_cursor"] is None


async def test_list_is_cursor_paginated_newest_first(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    await seed_extension(db, _manifest("cam"))
    for slug in ("bom", "cam"):
        put = await client.put(
            _url(seed.team_id, slug), json={"blocked": True}, headers=alice_headers
        )
        assert put.status_code == 201, put.text

    first = await client.get(_url(seed.team_id), params={"limit": 1}, headers=alice_headers)
    assert first.status_code == 200, first.text
    assert [row["extension"]["slug"] for row in first.json()["data"]] == ["cam"]
    assert first.json()["meta"]["has_next"] is True
    cursor = first.json()["meta"]["next_cursor"]

    second = await client.get(
        _url(seed.team_id), params={"limit": 1, "cursor": cursor}, headers=alice_headers
    )
    assert [row["extension"]["slug"] for row in second.json()["data"]] == ["bom"]
    assert second.json()["meta"]["has_next"] is False


# ------------------------------------------------------------------ PUT
async def test_put_creates_then_updates_the_policy_row(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str]
) -> None:
    created = await client.put(
        _url(seed.team_id, "bom"),
        json={"default_installed": True, "default_settings": VALID_SETTINGS},
        headers=alice_headers,
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["extension"] == {"slug": "bom", "name": "BOM", "verified": False}
    assert row["blocked"] is False
    assert row["default_installed"] is True
    assert row["default_settings"] == VALID_SETTINGS
    assert row["updated_by"] == seed.alice_id
    assert set(row) == {
        "extension",
        "blocked",
        "default_installed",
        "default_settings",
        "updated_by",
        "updated_at",
    }

    updated = await client.put(
        _url(seed.team_id, "bom"), json={"default_installed": False}, headers=alice_headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["default_installed"] is False
    # Unmentioned keys are kept — PUT is a partial upsert of the policy row.
    assert updated.json()["data"]["default_settings"] == VALID_SETTINGS

    listed = await client.get(_url(seed.team_id), headers=alice_headers)
    assert len(listed.json()["data"]) == 1


async def test_slug_is_matched_case_insensitively_at_the_lookup(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    seed.extension.slug = "BOM"
    db.add(seed.extension)
    await db.commit()
    resp = await client.put(
        _url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"blocked": True, "colour": "red"},
        {"blocked": "yes"},
        {"default_settings": ["refresh"]},
        {"blocked": True, "default_installed": True},
    ],
)
async def test_put_rejects_malformed_bodies(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str], body: dict[str, Any]
) -> None:
    resp = await client.put(_url(seed.team_id, "bom"), json=body, headers=alice_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


async def test_blocking_a_current_default_requires_clearing_the_default(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str]
) -> None:
    ok = await client.put(
        _url(seed.team_id, "bom"), json={"default_installed": True}, headers=alice_headers
    )
    assert ok.status_code == 201, ok.text
    merged = await client.put(
        _url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers
    )
    assert merged.status_code == 422, merged.text
    explicit = await client.put(
        _url(seed.team_id, "bom"),
        json={"blocked": True, "default_installed": False},
        headers=alice_headers,
    )
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["data"]["blocked"] is True


@pytest.mark.parametrize("slug", ["Bom", "1bom", "b", "a" * 65, "bom_x"])
async def test_bad_slug_syntax_is_422_before_any_lookup(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str], slug: str
) -> None:
    resp = await client.put(_url(seed.team_id, slug), json={"blocked": True}, headers=alice_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


async def test_unknown_or_unapproved_extension_is_404(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    await seed_extension(db, _manifest("draft"), approved=False)
    for slug in ("nope", "draft"):
        resp = await client.put(
            _url(seed.team_id, slug), json={"blocked": True}, headers=alice_headers
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"


# ----------------------------------------------------- default_settings
@pytest.mark.parametrize(
    "settings_body",
    [
        {"unknown": 1},
        {"refresh": "weekly"},
        {"refresh": True},
        {"flag_eol": "yes"},
        {"max_rows": 5},
        {"max_rows": 1000},
        {"max_rows": True},
        {"vendor": 3},
        {"vendor": None},
        {"vendor": "x" * DEFAULT_SETTINGS_MAX_BYTES},
    ],
)
async def test_default_settings_are_validated_against_the_latest_approved_manifest(
    client: AsyncClient,
    seed: Seed,
    alice_headers: dict[str, str],
    settings_body: dict[str, Any],
) -> None:
    resp = await client.put(
        _url(seed.team_id, "bom"), json={"default_settings": settings_body}, headers=alice_headers
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"
    assert resp.json()["error"]["details"], "problems are listed for the caller"


async def test_valid_default_settings_are_stored_verbatim(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    resp = await client.put(
        _url(seed.team_id, "bom"), json={"default_settings": VALID_SETTINGS}, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text
    stored = await db.scalar(
        select(TeamExtensionPolicy.default_settings).where(
            TeamExtensionPolicy.team_id == uuid.UUID(seed.team_id)
        )
    )
    assert stored == VALID_SETTINGS


def test_validate_default_settings_reports_every_problem() -> None:
    validate_default_settings(MANIFEST, {})
    validate_default_settings(MANIFEST, {"max_rows": 10.0})
    with pytest.raises(APIError) as excinfo:
        validate_default_settings(MANIFEST, {"unknown": 1, "refresh": "never", "max_rows": 1})
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "validation_error"
    assert len(excinfo.value.details) == 3


# -------------------------------------------------------------- block effect
async def test_block_disables_installs_in_every_team_project_and_no_other(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    resp = await client.put(
        _url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text

    for project_id in seed.projects:
        assert await install_enabled(db, project_id) is False
    assert await install_enabled(db, seed.other_project) is True

    disables = await events(db, "extension.disable")
    assert {str(e.project_id) for e in disables} == set(seed.projects)
    assert all(e.team_id == uuid.UUID(seed.team_id) for e in disables)
    assert all(
        e.payload == {"slug": "bom", "version": "1.2.0", "reason": "team_policy"} for e in disables
    )

    changed = await events(db, "extension.grants_changed")
    assert len(changed) == 1
    assert changed[0].team_id == uuid.UUID(seed.team_id)
    assert changed[0].payload == {
        "slug": "bom",
        "scope": "team",
        "added_scopes": [],
        "removed_scopes": [],
        "added_network": [],
        "removed_network": [],
        "changed_keys": ["blocked"],
    }


async def test_re_asserting_a_block_disables_nothing_twice(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    await client.put(_url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers)
    again = await client.put(
        _url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers
    )
    assert again.status_code == 200, again.text
    assert len(await events(db, "extension.disable")) == 2
    # Nothing changed, nothing to report.
    assert len(await events(db, "extension.grants_changed")) == 1


async def test_unblocking_does_not_re_enable_installs(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    await client.put(_url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers)
    resp = await client.put(
        _url(seed.team_id, "bom"), json={"blocked": False}, headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["blocked"] is False
    for project_id in seed.projects:
        assert await install_enabled(db, project_id) is False
    assert len(await events(db, "extension.enable")) == 0


# ------------------------------------------------------------------ DELETE
async def test_delete_resets_the_policy_and_leaves_installs_alone(
    client: AsyncClient, seed: Seed, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    await client.put(_url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers)
    resp = await client.delete(_url(seed.team_id, "bom"), headers=alice_headers)
    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    listed = await client.get(_url(seed.team_id), headers=alice_headers)
    assert listed.json()["data"] == []
    for project_id in seed.projects:
        assert await install_enabled(db, project_id) is False

    changed = await events(db, "extension.grants_changed")
    assert changed[-1].payload["scope"] == "team"
    assert changed[-1].payload["changed_keys"] == ["blocked"]

    again = await client.delete(_url(seed.team_id, "bom"), headers=alice_headers)
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "not_found"


# ----------------------------------------------------------- authorization
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
@pytest.mark.parametrize("who", ["carol_headers", "dave_headers"])
async def test_admin_and_member_are_forbidden(
    client: AsyncClient,
    seed: Seed,
    request: pytest.FixtureRequest,
    method: str,
    who: str,
) -> None:
    headers = request.getfixturevalue(who)
    url = _url(seed.team_id) if method == "GET" else _url(seed.team_id, "bom")
    body = {"blocked": True} if method == "PUT" else None
    resp = await client.request(method, url, json=body, headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_non_member_gets_404_never_403(
    client: AsyncClient, seed: Seed, bob_headers: dict[str, str], method: str
) -> None:
    url = _url(seed.team_id) if method == "GET" else _url(seed.team_id, "bom")
    body = {"blocked": True} if method == "PUT" else None
    resp = await client.request(method, url, json=body, headers=bob_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "not_found"


async def test_policies_are_team_scoped(
    client: AsyncClient, seed: Seed, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await client.put(_url(seed.team_id, "bom"), json={"blocked": True}, headers=alice_headers)
    other = await client.get(_url(seed.other_team_id), headers=bob_headers)
    assert other.status_code == 200, other.text
    assert other.json()["data"] == []
    assert await client.delete(_url(seed.other_team_id, "bom"), headers=bob_headers) is not None
    still = await client.get(_url(seed.team_id), headers=alice_headers)
    assert [row["blocked"] for row in still.json()["data"]] == [True]


async def test_anonymous_is_401(client: AsyncClient, seed: Seed) -> None:
    resp = await client.get(_url(seed.team_id))
    assert resp.status_code == 401


# --------------------------------------------------------------- rate limit
async def test_policy_writes_are_rate_limited_per_team(
    settings: Settings, engine: AsyncEngine, db: AsyncSession
) -> None:
    strict = settings.model_copy(update={"extension_policy_writes_per_minute_per_team": 2})
    application = _mount(create_app(settings=strict, engine=engine))
    alice_headers = bearer(ALICE["sub"], ALICE["email"])
    bob_headers = bearer(BOB["sub"], BOB["email"])
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        seed = await build_seed(client, db)
        url = _url(seed.team_id, "bom")
        assert (
            await client.put(url, json={"blocked": True}, headers=alice_headers)
        ).status_code == 201
        assert (await client.delete(url, headers=alice_headers)).status_code == 204

        limited = await client.put(url, json={"blocked": True}, headers=alice_headers)
        assert limited.status_code == 429, limited.text
        assert limited.json()["error"]["code"] == "rate_limited"
        assert limited.headers["Retry-After"] == "60"
        # Reads ride the global limiter only.
        assert (await client.get(_url(seed.team_id), headers=alice_headers)).status_code == 200
        # The budget is per team: another team's owner is unaffected.
        other = await client.put(
            _url(seed.other_team_id, "bom"), json={"blocked": True}, headers=bob_headers
        )
        assert other.status_code == 201, other.text

    limited_events = await events(db, "extension.rate_limited")
    assert len(limited_events) == 1
    assert limited_events[0].team_id == uuid.UUID(seed.team_id)
    assert limited_events[0].payload["budget"] == "extension_policy_writes_per_minute_per_team"
