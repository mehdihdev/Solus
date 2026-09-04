"""Grants, widening and blocks (SOLUSDEV-235 EXT-09, docs/api/extensions.md
§6.2 / §7 / §13): grants ⊆ declared (422), widening bump → 409 with details,
re-grant succeeds, team block → 403, storage without `storage.own` → 403."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import me
from fastapi import FastAPI
from fixtures.extensions.routes import (
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
from solus_api.models import ExtensionInstall
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

WIDE_SCOPES = ["graph.read", "sources.read", "storage.own"]
WIDE_NETWORK = ["https://api.octopart.com", "https://api.mouser.com"]
WIDER = manifest_with("1.3.0", scopes=WIDE_SCOPES, network=WIDE_NETWORK)


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return installs_app(settings, engine)


# ---------------------------------------------------------- grants ⊆ declared
@pytest.mark.parametrize(
    ("grants", "undeclared"),
    [
        (
            {"scopes": ["graph.read", "sol.ask"], "network": []},
            {"scopes": ["sol.ask"], "network": []},
        ),
        (
            {"scopes": [], "network": ["https://evil.example"]},
            {"scopes": [], "network": ["https://evil.example"]},
        ),
        (
            {"scopes": ["not.a.scope"], "network": ["https://API.octopart.com"]},
            {"scopes": ["not.a.scope"], "network": ["https://API.octopart.com"]},
        ),
    ],
    ids=["undeclared-scope", "undeclared-origin", "unknown-scope-and-case-differs"],
)
async def test_grants_beyond_the_manifest_are_422_listing_the_undeclared(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    grants: dict[str, list[str]],
    undeclared: dict[str, list[str]],
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, grants=grants)

    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == [undeclared]
    assert (await db.scalars(select(ExtensionInstall))).all() == []


async def test_granting_fewer_than_declared_is_allowed(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id, grants={"scopes": [], "network": []})

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["granted_scopes"] == []
    assert resp.json()["data"]["granted_network"] == []


# ------------------------------------------------------ widening → 409 → retry
async def test_version_bump_that_widens_beyond_current_grants_is_409_with_details(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, versions={"1.2.0": manifest_with("1.2.0"), "1.3.0": WIDER})
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id, version="1.2.0")).status_code == 201

    # Retrying with the OLD grants: the new version declares more than we hold.
    resp = await install(client, alice_headers, project_id, version="1.3.0")

    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "grants_required"
    assert error["details"] == [{"scopes": ["storage.own"], "network": ["https://api.mouser.com"]}]
    stored = await db.scalar(select(ExtensionInstall))
    assert stored is not None
    listed = await client.get(ext_url(project_id), headers=alice_headers)
    assert listed.json()["data"][0]["version"]["version"] == "1.2.0"  # pin unchanged


async def test_regranting_the_widened_permissions_completes_the_update(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, versions={"1.2.0": manifest_with("1.2.0"), "1.3.0": WIDER})
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id, version="1.2.0")).status_code == 201

    resp = await install(
        client,
        alice_headers,
        project_id,
        version="1.3.0",
        grants={
            "scopes": ["graph.read", "sources.read", "storage.own"],
            "network": ["https://api.octopart.com", "https://api.mouser.com"],
        },
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["data"]
    assert item["version"]["version"] == "1.3.0"
    assert item["granted_scopes"] == ["graph.read", "sources.read", "storage.own"]
    assert item["granted_network"] == ["https://api.mouser.com", "https://api.octopart.com"]
    assert item["update_available"] is None
    events = await events_of(db, "extension.grants_changed")
    assert len(events) == 1
    assert events[0].payload["added_scopes"] == ["storage.own"]
    assert events[0].payload["added_network"] == ["https://api.mouser.com"]
    assert events[0].payload["removed_scopes"] == []


async def test_widening_that_was_already_granted_before_is_not_required_again(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Current grants already cover what the new version declares → no 409."""
    await seed_extension(
        db,
        versions={
            "1.2.0": WIDER,
            "1.3.0": WIDER | {"extension": WIDER["extension"] | {"version": "1.3.0"}},
        },
    )
    _, project_id = await project_for(client, alice_headers)
    full = {"scopes": WIDE_SCOPES, "network": WIDE_NETWORK}
    assert (
        await install(client, alice_headers, project_id, version="1.2.0", grants=full)
    ).status_code == 201

    resp = await install(client, alice_headers, project_id, version="1.3.0", grants=full)

    assert resp.status_code == 200, resp.text


async def test_same_version_regrant_changes_grants_and_emits(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    resp = await install(
        client, alice_headers, project_id, grants={"scopes": ["graph.read"], "network": []}
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["granted_scopes"] == ["graph.read"]
    events = await events_of(db, "extension.grants_changed")
    assert [e.payload["removed_scopes"] for e in events] == [["sources.read"]]
    assert events[0].payload["removed_network"] == ["https://api.octopart.com"]


# ------------------------------------------------------------- team block
async def test_install_of_a_team_blocked_extension_is_403_and_writes_nothing(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    catalog = await seed_extension(db)
    team_id, project_id = await project_for(client, alice_headers)
    await seed_policy(db, team_id, catalog.extension_id, blocked=True)

    resp = await install(client, alice_headers, project_id)

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "extension_blocked"
    assert (await db.scalars(select(ExtensionInstall))).all() == []


async def test_enabling_a_team_blocked_install_is_403_but_disabling_is_allowed(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    catalog = await seed_extension(db)
    team_id, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201
    await seed_policy(db, team_id, catalog.extension_id, blocked=True)

    on = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": True}, headers=alice_headers
    )
    off = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )

    assert on.status_code == 403 and on.json()["error"]["code"] == "extension_blocked"
    assert off.status_code == 200 and off.json()["data"]["enabled"] is False


async def test_a_block_in_another_team_does_not_affect_this_project(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    catalog = await seed_extension(db)
    bob_team, _ = await project_for(client, bob_headers)
    await seed_policy(db, bob_team, catalog.extension_id, blocked=True)
    _, project_id = await project_for(client, alice_headers)

    resp = await install(client, alice_headers, project_id)

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["policy"]["blocked"] is False


# -------------------------------------------------------- storage.own gate
async def _installed_project(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession, *, scopes: list[str]
) -> tuple[str, Any]:
    catalog = await seed_extension(db, versions={"1.2.0": manifest_with(scopes=["storage.own"])})
    team_id, project_id = await project_for(client, headers)
    grants = {"scopes": scopes, "network": []}
    assert (await install(client, headers, project_id, grants=grants)).status_code == 201
    return project_id, (team_id, catalog)


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_storage_without_the_storage_scope_is_403_scope_denied_and_emits_refusal(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, method: str
) -> None:
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=[])

    resp = await client.request(
        method,
        ext_url(project_id, "bom") + "/storage/k",
        json={"v": 1} if method == "PUT" else None,
        headers=alice_headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "scope_denied"
    refused = await events_of(db, "extension.bridge_refused")
    assert [e.payload for e in refused] == [
        {"slug": "bom", "method": f"storage.{method.lower()}", "reason": "scope_not_granted"}
    ]


async def test_storage_on_a_disabled_install_is_403_with_reason_disabled(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])
    off = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )
    assert off.status_code == 200

    resp = await client.get(ext_url(project_id, "bom") + "/storage/k", headers=alice_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "scope_denied"
    refused = await events_of(db, "extension.bridge_refused")
    assert refused[0].payload["reason"] == "disabled"


async def test_storage_on_a_team_blocked_install_is_403_with_reason_blocked(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    project_id, (team_id, catalog) = await _installed_project(
        client, alice_headers, db, scopes=["storage.own"]
    )
    await seed_policy(db, team_id, catalog.extension_id, blocked=True)

    resp = await client.put(
        ext_url(project_id, "bom") + "/storage/k", json=1, headers=alice_headers
    )

    assert resp.status_code == 403
    refused = await events_of(db, "extension.bridge_refused")
    assert refused[0].payload["reason"] == "blocked"


async def test_storage_with_no_install_at_all_is_404(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)

    resp = await client.get(ext_url(project_id, "bom") + "/storage/k", headers=alice_headers)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    refused = await events_of(db, "extension.bridge_refused")
    assert refused[0].payload["reason"] == "not_installed"


async def test_storage_round_trip_with_the_scope_granted(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])
    url = ext_url(project_id, "bom") + "/storage/cache.v1"

    created = await client.put(url, json={"rows": [1, 2, 3]}, headers=alice_headers)
    replaced = await client.put(url, json="short", headers=alice_headers)
    got = await client.get(url, headers=alice_headers)
    gone = await client.delete(url, headers=alice_headers)
    missing = await client.get(url, headers=alice_headers)

    assert created.status_code == 201, created.text
    assert created.json()["data"]["key"] == "cache.v1"
    assert created.json()["data"]["value"] == {"rows": [1, 2, 3]}
    assert created.json()["data"]["size_bytes"] == len('{"rows":[1,2,3]}')
    assert replaced.status_code == 200
    assert got.json()["data"]["value"] == "short"
    assert got.json()["data"]["size_bytes"] == len('"short"')
    assert gone.status_code == 204
    assert missing.status_code == 404
    assert (await client.delete(url, headers=alice_headers)).status_code == 404


async def test_storage_read_rate_limit_is_429_per_user_with_retry_after(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: FastAPI
) -> None:
    """Phase 4 L3: `GET …/storage/{key}` rides a per-USER window (writes stay
    per-install); over budget → 429 + Retry-After, never a silent read."""
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])
    url = ext_url(project_id, "bom") + "/storage/cache.v1"
    assert (await client.put(url, json=1, headers=alice_headers)).status_code == 201
    app.state.settings.extension_storage_reads_per_minute_per_user = 1

    first = await client.get(url, headers=alice_headers)
    second = await client.get(url, headers=alice_headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert second.headers["Retry-After"] == "60"


@pytest.mark.parametrize("key", ["", "a b", "k/x", "k" * 65, "ü", "a:b"])
async def test_malformed_storage_key_is_422(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, key: str
) -> None:
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])

    resp = await client.put(
        ext_url(project_id, "bom") + f"/storage/{key}", json=1, headers=alice_headers
    )

    assert resp.status_code in (404, 422), resp.text  # "" collapses to a missing segment
    if resp.status_code == 422:
        assert resp.json()["error"]["code"] == "validation_error"


async def test_storage_value_over_64_kib_is_413_payload_too_large(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])

    resp = await client.put(
        ext_url(project_id, "bom") + "/storage/big", json="x" * (64 * 1024), headers=alice_headers
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_storage_total_over_256_kib_is_413_quota_exceeded_with_details(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])
    chunk = "x" * (60 * 1024)  # 61 442 bytes encoded, ×4 = 245 768
    for i in range(4):
        put = await client.put(
            ext_url(project_id, "bom") + f"/storage/k{i}", json=chunk, headers=alice_headers
        )
        assert put.status_code == 201, put.text

    resp = await client.put(
        ext_url(project_id, "bom") + "/storage/k4", json=chunk, headers=alice_headers
    )

    assert resp.status_code == 413, resp.text
    error = resp.json()["error"]
    assert error["code"] == "storage_quota_exceeded"
    assert error["details"] == [{"used_bytes": 5 * (60 * 1024 + 2), "limit_bytes": 256 * 1024}]
    # Replacing an existing key counts only the delta — this one fits.
    replace = await client.put(
        ext_url(project_id, "bom") + "/storage/k0", json=chunk, headers=alice_headers
    )
    assert replace.status_code == 200


async def test_storage_rejects_a_body_that_is_not_json(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _installed_project(client, alice_headers, db, scopes=["storage.own"])

    resp = await client.put(
        ext_url(project_id, "bom") + "/storage/k",
        content=b"{not json",
        headers={**alice_headers, "content-type": "application/json"},
    )

    assert resp.status_code == 422
