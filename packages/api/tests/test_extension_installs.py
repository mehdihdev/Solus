"""Project install routes — docs/api/extensions.md §6.1–§6.4 (SOLUSDEV-235 EXT-09).

Install (201) / update (200) / version pin / `update_available` / list paging /
PATCH enable + settings / uninstall clearing storage. The seeding helpers here
live in `fixtures/extensions/routes.py`, shared with the sibling EXT-09 suites.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from fixtures.extensions.routes import (
    MANIFEST,
    consent,
    events_of,
    ext_url,
    install,
    installs_app,
    manifest_with,
    project_for,
    seed_extension,
    seed_policy,
)
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.models import (
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionStorage,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return installs_app(settings, engine)


# ------------------------------------------------------------- §6.2 install
async def test_first_install_is_201_with_the_item_shape_and_seeded_defaults(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    catalog = await seed_extension(db)
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id)

    assert resp.status_code == 201, resp.text
    item = resp.json()["data"]
    assert item["extension"] == {
        "slug": "bom",
        "name": "BOM",
        "verified": False,
        "publisher": {"display_name": "Solus"},
    }
    assert item["version"]["version"] == "1.2.0"
    assert item["version"]["bundle_url"] == "/api/v1/extensions/bom/versions/1.2.0/bundle"
    assert item["version"]["manifest"]["extension"]["id"] == "bom"
    assert item["enabled"] is True
    # Manifest defaults; `vendor` has no default and is absent.
    assert item["settings"] == {"refresh": "every_sync", "flag_eol": True, "max_rows": 100}
    assert item["granted_scopes"] == ["graph.read", "sources.read"]
    assert item["granted_network"] == ["https://api.octopart.com"]
    assert item["update_available"] is None
    assert item["policy"] == {"blocked": False, "default_installed": False}
    assert item["installed_by"] == alice["id"]
    assert item["installed_at"] and item["updated_at"]

    extension = await db.get(Extension, catalog.extension_id)
    assert extension is not None
    await db.refresh(extension)
    assert extension.install_count == 1
    events = await events_of(db, "extension.install")
    assert len(events) == 1
    assert events[0].payload == {
        "slug": "bom",
        "version": "1.2.0",
        "granted_scopes": ["graph.read", "sources.read"],
        "granted_network": ["https://api.octopart.com"],
    }
    assert events[0].project_id == uuid.UUID(project_id)


async def test_reinstall_of_the_same_version_is_200_and_does_not_recount(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    catalog = await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    again = await install(client, alice_headers, project_id)

    assert again.status_code == 200, again.text
    extension = await db.get(Extension, catalog.extension_id)
    assert extension is not None
    await db.refresh(extension)
    assert extension.install_count == 1


async def test_install_seeds_settings_from_team_policy_defaults_then_manifest(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """§6.2: policy `default_settings` win for declared, type-valid keys; unknown
    keys and wrong-typed values are dropped; manifest defaults fill the rest."""
    catalog = await seed_extension(db)
    team_id, project_id = await project_for(client, alice_headers)
    await seed_policy(
        db,
        team_id,
        catalog.extension_id,
        default_installed=True,
        default_settings={"refresh": "daily", "max_rows": "many", "bogus": 1, "vendor": "Digi"},
    )

    resp = await install(client, alice_headers, project_id)

    assert resp.status_code == 201, resp.text
    item = resp.json()["data"]
    assert item["settings"] == {
        "refresh": "daily",
        "flag_eol": True,
        "max_rows": 100,
        "vendor": "Digi",
    }
    assert item["policy"] == {"blocked": False, "default_installed": True}


async def test_install_pins_the_requested_version_and_reports_update_available(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(
        db,
        versions={
            "1.0.0": manifest_with("1.0.0"),
            "1.2.0": manifest_with("1.2.0", scopes=["graph.read", "sources.read", "sol.ask"]),
        },
    )
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, version="1.0.0")

    assert resp.status_code == 201, resp.text
    item = resp.json()["data"]
    assert item["version"]["version"] == "1.0.0"
    # The latest declares `sol.ask`, which the current grants lack → widens.
    assert item["update_available"] == {"version": "1.2.0", "widens_permissions": True}


async def test_update_available_does_not_widen_when_latest_declares_no_more(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(
        db, versions={"1.0.0": manifest_with("1.0.0"), "1.1.0": manifest_with("1.1.0")}
    )
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, version="1.0.0")

    assert resp.json()["data"]["update_available"] == {
        "version": "1.1.0",
        "widens_permissions": False,
    }


async def test_update_to_a_narrower_version_intersects_grants_and_carries_settings(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(
        db,
        versions={
            "1.2.0": manifest_with("1.2.0"),
            "2.0.0": manifest_with(
                "2.0.0",
                scopes=["graph.read"],
                network=[],
                settings_fields=[MANIFEST["settings"]["fields"][0]],  # only `refresh`
            ),
        },
    )
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id, version="1.2.0")).status_code == 201
    patched = await client.patch(
        ext_url(project_id, "bom"), json={"settings": {"refresh": "hourly"}}, headers=alice_headers
    )
    assert patched.status_code == 200, patched.text

    resp = await install(
        client,
        alice_headers,
        project_id,
        grants={"scopes": ["graph.read"], "network": []},
        version="2.0.0",
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["data"]
    assert item["version"]["version"] == "2.0.0"
    assert item["granted_scopes"] == ["graph.read"]
    assert item["granted_network"] == []
    # `flag_eol`/`max_rows` are no longer declared → dropped; `refresh` survives.
    assert item["settings"] == {"refresh": "hourly"}
    assert item["update_available"] is None
    events = await events_of(db, "extension.grants_changed")
    assert len(events) == 1
    assert events[0].payload == {
        "slug": "bom",
        "scope": "project",
        "added_scopes": [],
        "removed_scopes": ["sources.read"],
        "added_network": [],
        "removed_network": ["https://api.octopart.com"],
        "changed_keys": ["flag_eol", "max_rows"],
    }


async def test_update_keeps_the_stored_enabled_flag(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(
        db, versions={"1.0.0": manifest_with("1.0.0"), "1.2.0": manifest_with("1.2.0")}
    )
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id, version="1.0.0")).status_code == 201
    disabled = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )
    assert disabled.status_code == 200

    resp = await install(client, alice_headers, project_id, version="1.2.0")

    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False


@pytest.mark.parametrize(
    ("slug", "version"),
    [("nope", None), ("bom", "9.9.9"), ("bom", "1.5.0"), ("bom", "0.1.0")],
    ids=["unknown-slug", "unknown-version", "pending-version", "other-extensions-version"],
)
async def test_unknown_slug_or_uninstallable_version_is_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    slug: str,
    version: str | None,
) -> None:
    await seed_extension(db, pending=("1.5.0",))
    await seed_extension(db, slug="other", versions={"0.1.0": manifest_with("0.1.0", slug="other")})
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, slug=slug, version=version)

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "not_found"


async def test_extension_without_an_approved_version_is_404(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    publisher = ExtensionPublisher(display_name="Solus")
    db.add(publisher)
    await db.flush()
    db.add(Extension(slug="draft", publisher_id=publisher.id, name="Draft", summary="x"))
    await db.commit()
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, slug="draft")

    assert resp.status_code == 404


@pytest.mark.parametrize("slug", ["-bom", "1bom", "a", "bom_x", "b" * 65, "constructor"])
async def test_malformed_slug_is_422_before_any_lookup(
    client: AsyncClient, alice_headers: dict[str, str], slug: str
) -> None:
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, slug=slug)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"grants": {"scopes": []}, "extra": 1},
        {"grants": {"scopes": [], "network": [], "other": []}},
        {"grants": {"scopes": [], "network": []}, "version": "not-semver"},
    ],
    ids=["no-grants", "unknown-top-level", "unknown-grants-key", "bad-version"],
)
async def test_malformed_install_body_is_422(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, body: dict[str, Any]
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)

    resp = await client.put(ext_url(project_id, "bom"), json=body, headers=alice_headers)

    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------- §6.1 list
async def test_list_returns_installed_extensions_newest_first_with_paging(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, slug="bom")
    await seed_extension(db, slug="scope", versions={"0.1.0": manifest_with("0.1.0", slug="scope")})
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id, slug="bom")).status_code == 201
    assert (await install(client, alice_headers, project_id, slug="scope")).status_code == 201

    first = await client.get(ext_url(project_id) + "?limit=1", headers=alice_headers)

    assert first.status_code == 200, first.text
    body = first.json()
    assert [i["extension"]["slug"] for i in body["data"]] == ["scope"]
    assert body["meta"]["has_next"] is True
    rest = await client.get(
        ext_url(project_id) + f"?limit=1&cursor={body['meta']['next_cursor']}",
        headers=alice_headers,
    )
    assert [i["extension"]["slug"] for i in rest.json()["data"]] == ["bom"]
    assert rest.json()["meta"]["has_next"] is False
    assert rest.json()["meta"]["next_cursor"] is None


async def test_list_is_empty_for_a_project_with_no_installs(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)

    resp = await client.get(ext_url(project_id), headers=alice_headers)

    assert resp.status_code == 200
    assert resp.json() == {
        "data": [],
        "meta": {"limit": 50, "has_next": False, "next_cursor": None},
    }


async def test_list_rejects_limit_above_the_cap(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)

    resp = await client.get(ext_url(project_id) + "?limit=201", headers=alice_headers)

    assert resp.status_code == 422


async def test_list_reports_a_team_blocked_install_as_disabled(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    catalog = await seed_extension(db)
    team_id, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201
    await seed_policy(db, team_id, catalog.extension_id, blocked=True)

    resp = await client.get(ext_url(project_id), headers=alice_headers)

    item = resp.json()["data"][0]
    assert item["enabled"] is False
    assert item["policy"] == {"blocked": True, "default_installed": False}
    stored = await db.scalar(select(ExtensionInstall))
    assert stored is not None and stored.enabled is True  # the flag itself is untouched


# --------------------------------------------------------------- §6.3 patch
async def test_patch_enabled_toggles_and_emits_disable_then_enable(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    off = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )
    on = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": True}, headers=alice_headers
    )

    assert off.status_code == 200 and off.json()["data"]["enabled"] is False
    assert on.status_code == 200 and on.json()["data"]["enabled"] is True
    disable = await events_of(db, "extension.disable")
    enable = await events_of(db, "extension.enable")
    assert [e.payload for e in disable] == [{"slug": "bom", "version": "1.2.0", "reason": "user"}]
    assert [e.payload for e in enable] == [{"slug": "bom", "version": "1.2.0"}]


async def test_patch_settings_replaces_the_object_and_emits_changed_keys_only(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    resp = await client.patch(
        ext_url(project_id, "bom"),
        json={"settings": {"refresh": "hourly", "vendor": "Mouser"}},
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text
    # Missing declared keys fall back to manifest defaults.
    assert resp.json()["data"]["settings"] == {
        "refresh": "hourly",
        "flag_eol": True,
        "max_rows": 100,
        "vendor": "Mouser",
    }
    events = await events_of(db, "extension.settings_changed")
    assert len(events) == 1
    assert events[0].payload == {
        "slug": "bom",
        "version": "1.2.0",
        "changed_keys": ["refresh", "vendor"],
    }
    assert "hourly" not in json.dumps(events[0].payload)  # never values


@pytest.mark.parametrize(
    "body", [{}, {"enabled": "yes"}, {"enabled": True, "bogus": 1}, {"settings": []}]
)
async def test_patch_body_shape_violations_are_422(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, body: dict[str, Any]
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    resp = await client.patch(ext_url(project_id, "bom"), json=body, headers=alice_headers)

    assert resp.status_code == 422, resp.text


async def test_patch_of_an_uninstalled_extension_is_404(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)

    resp = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )

    assert resp.status_code == 404


# ----------------------------------------------------------- §6.4 uninstall
async def test_uninstall_deletes_the_install_and_its_storage_and_decrements(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    catalog = await seed_extension(db, versions={"1.2.0": manifest_with(scopes=["storage.own"])})
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)
    grants = {"scopes": ["storage.own"], "network": []}
    assert (await install(client, alice_headers, project_id, grants=grants)).status_code == 201
    for key in ("a", "b"):
        put = await client.put(
            ext_url(project_id, "bom") + f"/storage/{key}", json={"k": key}, headers=alice_headers
        )
        assert put.status_code == 201, put.text

    resp = await client.delete(ext_url(project_id, "bom"), headers=alice_headers)

    assert resp.status_code == 204
    assert (await db.scalars(select(ExtensionInstall))).all() == []
    assert (await db.scalars(select(ExtensionStorage))).all() == []
    extension = await db.get(Extension, catalog.extension_id)
    assert extension is not None
    await db.refresh(extension)
    assert extension.install_count == 0
    events = await events_of(db, "extension.uninstall")
    # SOLUSDEV-246 widened the payload with the "no orphans" sweep counts.
    assert [e.payload for e in events] == [
        {
            "slug": "bom",
            "version": "1.2.0",
            "storage_rows_deleted": 2,
            "entities_soft_deleted": 0,
            "layout_slots_pruned": 0,
        }
    ]
    again = await client.delete(ext_url(project_id, "bom"), headers=alice_headers)
    assert again.status_code == 404


async def test_uninstall_leaves_other_projects_storage_alone(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, versions={"1.2.0": manifest_with(scopes=["storage.own"])})
    team = await create_team(client, alice_headers)
    p1 = (await create_project(client, alice_headers, team["id"], "P1"))["id"]
    p2 = (await create_project(client, alice_headers, team["id"], "P2"))["id"]
    grants = {"scopes": ["storage.own"], "network": []}
    for pid in (p1, p2):
        assert (await install(client, alice_headers, pid, grants=grants)).status_code == 201
        put = await client.put(ext_url(pid, "bom") + "/storage/k", json=1, headers=alice_headers)
        assert put.status_code == 201

    assert (await client.delete(ext_url(p1, "bom"), headers=alice_headers)).status_code == 204

    remaining = (await db.scalars(select(ExtensionStorage))).all()
    assert [str(r.project_id) for r in remaining] == [p2]
