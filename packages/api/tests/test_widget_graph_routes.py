"""SOLUSDEV-246 (STORE ST2) — widgets in the graph, over HTTP.

Acceptance: install BOM → a BOM node appears under the workspace root beside
Live Bench; uninstall → gone, no dangling edges. Plus: enable/disable mirrors
into the node, the read route heals installs that predate the layer, the
Context Model list shows the layer with its own domain, and team B sees nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from conftest import add_member, me
from fixtures.extensions.routes import (
    consent,
    events_of,
    ext_url,
    install,
    project_for,
    seed_extension,
)
from httpx import AsyncClient
from solus_api.models import GraphEdge, GraphEntity
from solus_api.widgets.graph_nodes import LIVE_BENCH_KIND, WIDGET_KIND, WORKSPACE_KIND
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

FULL_GRANTS = {"scopes": ["graph.read", "sources.read"], "network": ["https://api.octopart.com"]}


def _graph_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/widgets/graph"


async def _graph(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.get(_graph_url(project_id), headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _dangling(db: AsyncSession, project_id: str) -> int:
    pid = uuid.UUID(project_id)
    live_ids = set(
        await db.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == pid, GraphEntity.deleted_at.is_(None)
            )
        )
    )
    edges = await db.scalars(
        select(GraphEdge).where(GraphEdge.project_id == pid, GraphEdge.deleted_at.is_(None))
    )
    return sum(1 for e in edges.all() if e.src_id not in live_ids or e.dst_id not in live_ids)


async def test_install_bom_shows_a_bom_node_beside_live_bench_and_uninstall_removes_it(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    await consent(db, user["id"])
    _, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")

    empty = await _graph(client, alice_headers, project_id)
    assert empty["root"]["type"] == WORKSPACE_KIND and empty["root"]["domain"] == "workspace"
    assert empty["live_bench"]["type"] == LIVE_BENCH_KIND
    assert empty["widgets"] == []
    assert len(empty["edges"]) == 1  # root → live bench

    installed = await install(client, alice_headers, project_id, "bom", grants=FULL_GRANTS)
    assert installed.status_code == 201, installed.text
    graph = await _graph(client, alice_headers, project_id)
    assert [w["name"] for w in graph["widgets"]] == ["BOM"]
    bom = graph["widgets"][0]
    assert bom["type"] == WIDGET_KIND and bom["domain"] == "workspace" and bom["origin"] == "system"
    assert bom["properties"] == {
        "slug": "bom",
        "version": "1.2.0",
        "enabled": True,
        "publisher": "Solus",
        "views": ["widget", "page", "window"],
    }
    edge_targets = {(e["from_entity_id"], e["to_entity_id"], e["type"]) for e in graph["edges"]}
    assert edge_targets == {
        (graph["root"]["id"], graph["live_bench"]["id"], "contains"),
        (graph["root"]["id"], bom["id"], "contains"),
    }
    install_events = await events_of(db, "extension.install")
    assert install_events and install_events[-1].payload["graph_node_id"] == bom["id"]

    # The Context Model list (GET /entities) shows the layer with its own domain.
    listed = await client.get(
        f"/api/v1/projects/{project_id}/entities",
        params={"domain": "workspace"},
        headers=alice_headers,
    )
    assert listed.status_code == 200, listed.text
    kinds = sorted(e["type"] for e in listed.json()["data"])
    assert kinds == [LIVE_BENCH_KIND, WIDGET_KIND, WORKSPACE_KIND]

    gone = await client.delete(ext_url(project_id, "bom"), headers=alice_headers)
    assert gone.status_code == 204, gone.text
    after = await _graph(client, alice_headers, project_id)
    assert after["widgets"] == []
    assert len(after["edges"]) == 1
    node = await db.get(GraphEntity, uuid.UUID(bom["id"]))
    assert node is not None and node.deleted_at is not None
    assert await _dangling(db, project_id) == 0
    uninstall_events = await events_of(db, "extension.uninstall")
    assert uninstall_events[-1].payload["graph_node_id"] == bom["id"]


async def test_disable_enable_and_update_mirror_into_the_node(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    from fixtures.extensions.routes import manifest_with

    _, project_id = await project_for(client, alice_headers)
    await seed_extension(
        db, "bom", {"1.2.0": manifest_with("1.2.0"), "1.3.0": manifest_with("1.3.0")}
    )
    assert (
        await install(client, alice_headers, project_id, "bom", grants=FULL_GRANTS, version="1.2.0")
    ).status_code == 201

    off = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )
    assert off.status_code == 200, off.text
    assert (await _graph(client, alice_headers, project_id))["widgets"][0]["properties"][
        "enabled"
    ] is False

    on = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": True}, headers=alice_headers
    )
    assert on.status_code == 200
    assert (await _graph(client, alice_headers, project_id))["widgets"][0]["properties"][
        "enabled"
    ] is True

    moved = await install(
        client, alice_headers, project_id, "bom", grants=FULL_GRANTS, version="1.3.0"
    )
    assert moved.status_code == 200, moved.text
    widgets = (await _graph(client, alice_headers, project_id))["widgets"]
    assert len(widgets) == 1 and widgets[0]["properties"]["version"] == "1.3.0"


async def test_the_read_route_heals_installs_that_predate_the_layer(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    assert (
        await install(client, alice_headers, project_id, "bom", grants=FULL_GRANTS)
    ).status_code == 201
    # Simulate a pre-ST2 install: wipe the layer behind the API's back.
    pid = uuid.UUID(project_id)
    for edge in (await db.scalars(select(GraphEdge).where(GraphEdge.project_id == pid))).all():
        await db.delete(edge)
    for node in (await db.scalars(select(GraphEntity).where(GraphEntity.project_id == pid))).all():
        await db.delete(node)
    await db.commit()

    healed = await _graph(client, alice_headers, project_id)
    assert [w["properties"]["slug"] for w in healed["widgets"]] == ["bom"]
    assert len(healed["edges"]) == 2
    assert await _dangling(db, project_id) == 0


async def test_team_b_cannot_read_team_a_layer_and_a_viewer_can(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team_id, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    assert (
        await install(client, alice_headers, project_id, "bom", grants=FULL_GRANTS)
    ).status_code == 201
    stranger = await client.get(_graph_url(project_id), headers=bob_headers)
    assert stranger.status_code == 404
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    viewer = await client.get(_graph_url(project_id), headers=bob_headers)
    assert viewer.status_code == 200, viewer.text
    assert [w["name"] for w in viewer.json()["data"]["widgets"]] == ["BOM"]
    # Bob's own project has its own, separate layer.
    _, bobs_project = await project_for(client, bob_headers)
    own = await _graph(client, bob_headers, bobs_project)
    assert own["widgets"] == [] and own["root"]["id"] != viewer.json()["data"]["root"]["id"]


async def test_the_layer_is_read_only_through_the_generic_entity_routes(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    graph = await _graph(client, alice_headers, project_id)
    root_id = graph["root"]["id"]
    patched = await client.patch(
        f"/api/v1/projects/{project_id}/entities/{root_id}",
        json={"name": "Renamed"},
        headers={**alice_headers, "If-Match": "1"},
    )
    assert patched.status_code in (403, 405, 409, 422), patched.text
    deleted = await client.delete(
        f"/api/v1/projects/{project_id}/entities/{root_id}", headers=alice_headers
    )
    assert deleted.status_code in (403, 405, 409, 422), deleted.text
    still = await db.get(GraphEntity, uuid.UUID(root_id))
    assert still is not None and still.deleted_at is None and still.name == "Workspace"


async def test_a_published_v1_bundle_installs_and_registers_its_node_end_to_end(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """The path the STORE ST2 real run broke: publish (stores the manifest) →
    approve → install (re-parses the STORED manifest) → node. No seeded rows."""
    import io

    from fixtures.extensions import FULL_MANIFEST_TOML, build_zip, full_files, with_manifest
    from solus_api.models import Extension, ExtensionReviewStatus, ExtensionVersion, utcnow

    published = await client.post(
        "/api/v1/extensions/publish",
        files={
            "bundle": (
                "bom.zip",
                io.BytesIO(build_zip(with_manifest(full_files(), FULL_MANIFEST_TOML))),
                "application/zip",
            )
        },
        headers={**bob_headers, "Idempotency-Key": "e2e-bom"},
    )
    assert published.status_code == 202, published.text
    version = await db.scalar(select(ExtensionVersion).where(ExtensionVersion.version == "1.2.0"))
    assert version is not None
    assert not ({"backend", "graph", "tools"} & set(version.manifest))  # stored as authored
    version.review_status = ExtensionReviewStatus.APPROVED
    version.published_at = utcnow()
    extension = await db.get(Extension, version.extension_id)
    assert extension is not None
    extension.latest_approved_version_id = version.id
    await db.commit()

    _, project_id = await project_for(client, alice_headers)
    installed = await install(
        client, alice_headers, project_id, "bom", grants={"scopes": ["graph.read"], "network": []}
    )
    assert installed.status_code == 201, installed.text
    graph = await _graph(client, alice_headers, project_id)
    assert [w["properties"]["slug"] for w in graph["widgets"]] == ["bom"]
    assert graph["widgets"][0]["properties"]["publisher"] == "Ada Lovelace"
