"""SOLUSDEV-246 (STORE ST1) — first-party bundle capabilities over HTTP.

The guard on `/api/v1/projects/{id}/widgets/{slug}/…` (installed, enabled,
unblocked, routes declared — else 404 and a refusal event), team isolation, the
publish gate on `POST /extensions/publish`, `GET /sol/tools` reflecting installs,
and the "no orphans" uninstall through the real DELETE route.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from typing import Any

from conftest import API_DIR, add_member, me
from fastapi import FastAPI
from fixtures.extensions import CLEAN_HTML, CLEAN_JS, CLEAN_MD, VALID_ICON_SVG, build_zip
from fixtures.extensions.routes import (
    consent,
    events_of,
    ext_url,
    install,
    project_for,
    seed_extension,
    seed_policy,
)
from httpx import AsyncClient
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.models import GraphEntity, WidgetLayout
from solus_api.widgets.fixture_bundle import CAPABILITY as FIXTURE
from solus_contracts.extension_manifest import parse_extension_manifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

FIXTURES = API_DIR.parent / "shared-types" / "fixtures" / "extension-manifest"
V2: dict[str, Any] = json.loads(Path(FIXTURES / "manifest-v2-first-party.json").read_text())
SLUG = "fixture-bundle"
NOTE_KIND = "ext:fixture-bundle:note"
NO_GRANTS: dict[str, list[str]] = {"scopes": [], "network": []}

V2_TOML = """\
schema_version = 2

[extension]
id = "fixture-bundle"
name = "Fixture Bundle"
version = "0.1.0"
publisher = "Solus"
summary = "First-party fixture: page, backend routes, a graph kind and two SOL tools."

[views]
page = { entry = "page.html", icon = "icon.svg", label = "Fixture" }

[backend]
capability = "fixture-bundle"
routes = true

[graph]
kinds = [{ name = "note", domain = "code" }]

[tools]
names = ["add_note", "clear_notes"]

[store]
overview = "OVERVIEW.md"
"""


def _widgets(project_id: str, path: str = "notes") -> str:
    return f"/api/v1/projects/{project_id}/widgets/{SLUG}/{path}"


def _v2_zip(toml: str = V2_TOML) -> bytes:
    return build_zip(
        {
            "extension.toml": toml.encode(),
            "page.html": CLEAN_HTML,
            "app.js": CLEAN_JS,
            "icon.svg": VALID_ICON_SVG,
            "OVERVIEW.md": CLEAN_MD,
        }
    )


async def _seed_and_install(
    client: AsyncClient, db: AsyncSession, headers: dict[str, str]
) -> tuple[str, str, uuid.UUID]:
    """(team_id, project_id, extension_id) with the fixture bundle installed."""
    team_id, project_id = await project_for(client, headers)
    catalog = await seed_extension(db, SLUG, {"0.1.0": V2})
    installed = await install(client, headers, project_id, SLUG, grants=NO_GRANTS)
    assert installed.status_code == 201, installed.text
    return team_id, project_id, catalog.extension_id


async def _add_note(engine: AsyncEngine, project_id: str, text: str) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = build_sol_registry(
        factory,
        uuid.UUID(project_id),
        bundle_capabilities=[(FIXTURE, parse_extension_manifest(V2))],
    )
    result = await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": text}))
    assert result.ok and result.value is not None, result.error
    return str(result.value["id"])


# ------------------------------------------------------------------- the guard


async def test_routes_answer_only_for_an_installed_enabled_bundle(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    await consent(db, user["id"])
    team_id, project_id = await project_for(client, alice_headers)
    await seed_extension(db, SLUG, {"0.1.0": V2})

    missing = await client.get(_widgets(project_id), headers=alice_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    assert (
        await install(client, alice_headers, project_id, SLUG, grants=NO_GRANTS)
    ).status_code == 201
    ok = await client.get(_widgets(project_id), headers=alice_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"] == {"slug": SLUG, "notes": []}

    disabled = await client.patch(
        ext_url(project_id, SLUG), json={"enabled": False}, headers=alice_headers
    )
    assert disabled.status_code == 200, disabled.text
    assert (await client.get(_widgets(project_id), headers=alice_headers)).status_code == 404

    refusals = await events_of(db, "widget_bundle.route_refused")
    assert sorted(e.payload["reason"] for e in refusals) == ["disabled", "not_installed"]
    assert all(e.payload["slug"] == SLUG for e in refusals)


async def test_a_team_block_wins_over_an_install(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    team_id, project_id, extension_id = await _seed_and_install(client, db, alice_headers)
    await seed_policy(db, team_id, extension_id, blocked=True)
    blocked = await client.get(_widgets(project_id), headers=alice_headers)
    assert blocked.status_code == 404


async def test_a_bundle_without_routes_declared_has_no_routes(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    no_routes = json.loads(json.dumps(V2))
    no_routes["backend"] = {"capability": SLUG, "routes": False}
    await seed_extension(db, SLUG, {"0.1.0": no_routes})
    assert (
        await install(client, alice_headers, project_id, SLUG, grants=NO_GRANTS)
    ).status_code == 201
    assert (await client.get(_widgets(project_id), headers=alice_headers)).status_code == 404


async def test_an_unknown_capability_path_is_a_plain_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/widgets/nope/notes", headers=alice_headers
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------- isolation


async def test_team_b_cannot_read_team_a_notes_and_a_viewer_can(
    client: AsyncClient,
    db: AsyncSession,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team_id, project_id, _ = await _seed_and_install(client, db, alice_headers)
    await _add_note(engine, project_id, "A's secret note")

    # Bob, on no team of Alice's: the project does not exist for him.
    stranger = await client.get(_widgets(project_id), headers=bob_headers)
    assert stranger.status_code == 404

    # Bob as a viewer: reads are exempt from the member floor (extensions.md §3).
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    viewer = await client.get(_widgets(project_id), headers=bob_headers)
    assert viewer.status_code == 200, viewer.text
    assert [n["name"] for n in viewer.json()["data"]["notes"]] == ["A's secret note"]

    # Bob's own project (other team) sees nothing of Alice's even with the bundle installed.
    _, bobs_project = await project_for(client, bob_headers)
    assert (
        await install(client, bob_headers, bobs_project, SLUG, grants=NO_GRANTS)
    ).status_code == 201
    own = await client.get(_widgets(bobs_project), headers=bob_headers)
    assert own.status_code == 200 and own.json()["data"]["notes"] == []


# --------------------------------------------------------------- SOL tools


async def test_sol_tools_follow_the_install(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    await seed_extension(db, SLUG, {"0.1.0": V2})
    tools_url = f"/api/v1/projects/{project_id}/sol/tools"

    def names(resp: Any) -> list[str]:
        assert resp.status_code == 200, resp.text
        return [t["name"] for t in resp.json()["data"]]

    before = names(await client.get(tools_url, headers=alice_headers))
    assert not any(n.startswith(f"{SLUG}.") for n in before)

    assert (
        await install(client, alice_headers, project_id, SLUG, grants=NO_GRANTS)
    ).status_code == 201
    during = names(await client.get(tools_url, headers=alice_headers))
    assert f"{SLUG}.add_note" in during and f"{SLUG}.clear_notes" in during
    clear = next(
        t
        for t in (await client.get(tools_url, headers=alice_headers)).json()["data"]
        if t["name"] == f"{SLUG}.clear_notes"
    )
    assert clear["requires_confirmation"] is True

    assert (
        await client.delete(ext_url(project_id, SLUG), headers=alice_headers)
    ).status_code == 204
    after = names(await client.get(tools_url, headers=alice_headers))
    assert not any(n.startswith(f"{SLUG}.") for n in after)


# ---------------------------------------------------------------- uninstall


async def test_uninstall_leaves_no_trace(
    client: AsyncClient,
    db: AsyncSession,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    user = await me(client, alice_headers)
    await consent(db, user["id"])
    team_id, project_id, _ = await _seed_and_install(client, db, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="member")

    note_id = await _add_note(engine, project_id, "remove me")
    layout = {
        "layout": [
            {"ref": "builtin:livebench", "size": "wide"},
            {"ref": f"ext:{SLUG}", "size": "standard"},
        ]
    }
    for headers in (alice_headers, bob_headers):
        put = await client.put(
            f"/api/v1/projects/{project_id}/widget-layout", json=layout, headers=headers
        )
        assert put.status_code == 200, put.text
    stored = await client.put(
        f"{ext_url(project_id, SLUG)}/storage/k", json={"value": "v"}, headers=alice_headers
    )
    assert stored.status_code in (200, 201, 403), (
        stored.text
    )  # storage.own not granted → 403 is fine

    gone = await client.delete(ext_url(project_id, SLUG), headers=alice_headers)
    assert gone.status_code == 204, gone.text

    row = await db.get(GraphEntity, uuid.UUID(note_id))
    assert row is not None and row.deleted_at is not None
    layouts = (
        await db.scalars(
            select(WidgetLayout).where(WidgetLayout.project_id == uuid.UUID(project_id))
        )
    ).all()
    assert len(layouts) == 2
    assert all(row.layout == [{"ref": "builtin:livebench", "size": "wide"}] for row in layouts)
    assert (await client.get(_widgets(project_id), headers=alice_headers)).status_code == 404

    events = await events_of(db, "extension.uninstall")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["slug"] == SLUG
    assert payload["entities_soft_deleted"] == 1
    assert payload["layout_slots_pruned"] == 2

    # Reinstall starts clean: the old note does not come back.
    assert (
        await install(client, alice_headers, project_id, SLUG, grants=NO_GRANTS)
    ).status_code == 201
    fresh = await client.get(_widgets(project_id), headers=alice_headers)
    assert fresh.status_code == 200 and fresh.json()["data"]["notes"] == []


# ------------------------------------------------------------- publish gate


async def _publish(client: AsyncClient, headers: dict[str, str], data: bytes, key: str) -> Any:
    return await client.post(
        "/api/v1/extensions/publish",
        files={"bundle": ("bundle.zip", io.BytesIO(data), "application/zip")},
        headers={**headers, "Idempotency-Key": key},
    )


async def test_publish_refuses_first_party_tables_from_non_staff_and_accepts_staff(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    # The first-party gate runs before the publisher row is touched, so a
    # community account learns about the tables, not about the reserved name.
    refused = await _publish(client, alice_headers, _v2_zip(), "k-1")
    assert refused.status_code == 422, refused.text
    body = refused.json()["error"]
    assert body["code"] == "bundle_invalid"
    assert body["details"] == ["backend: first-party only (publisher is not Solus staff)"]

    alice = await me(client, alice_headers)
    app.state.settings.staff_user_ids = alice["id"]
    accepted = await _publish(client, alice_headers, _v2_zip(), "k-2")
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["data"]["version"]["slug"] == SLUG


async def test_publish_refuses_a_first_party_claim_without_an_in_repo_capability(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    app.state.settings.staff_user_ids = alice["id"]
    toml = V2_TOML.replace('id = "fixture-bundle"', 'id = "ghost-bundle"').replace(
        'capability = "fixture-bundle"', 'capability = "ghost-bundle"'
    )
    refused = await _publish(client, alice_headers, _v2_zip(toml), "k-3")
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"] == [
        "backend.capability: no in-repo capability named ghost-bundle"
    ]


async def test_a_v2_community_manifest_publishes_for_anyone(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    community = V2_TOML.replace('id = "fixture-bundle"', 'id = "hello-two"').replace(
        'publisher = "Solus"', 'publisher = "Ada Lovelace"'
    )
    toml = "\n".join(
        line
        for line in community.splitlines()
        if not line.startswith(
            ("[backend]", "capability", "routes", "[graph]", "kinds", "[tools]", "names")
        )
    )
    accepted = await _publish(client, alice_headers, _v2_zip(toml), "k-4")
    assert accepted.status_code == 202, accepted.text
