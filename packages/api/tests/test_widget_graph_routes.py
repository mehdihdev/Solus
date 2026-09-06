"""SOLUSDEV-246 (STORE ST2) — widgets in the graph, over HTTP.

Acceptance: install BOM → a BOM node appears under the workspace root beside
Live Bench; uninstall → gone, no dangling edges. The GET is a pure read (a
viewer may call it and it writes nothing); healing is `POST …/graph/reconcile`
behind the member floor and the install-write budget; enable/disable and a team
block mirror into the node; the Context Model list shows the layer; team B sees
nothing; the publish→install path stores the manifest as authored.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

from conftest import add_member, me
from fastapi import FastAPI
from fixtures.extensions import FULL_MANIFEST_TOML, build_zip, full_files, with_manifest
from fixtures.extensions.routes import (
    consent,
    events_of,
    ext_url,
    install,
    manifest_with,
    project_for,
    seed_extension,
    seed_policy,
)
from httpx import AsyncClient
from solus_api.models import (
    Extension,
    ExtensionReviewStatus,
    ExtensionVersion,
    GraphEdge,
    GraphEntity,
    utcnow,
)
from solus_api.widgets.graph_nodes import LIVE_BENCH_KIND, WIDGET_KIND, WORKSPACE_KIND
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

FULL_GRANTS = {"scopes": ["graph.read", "sources.read"], "network": ["https://api.octopart.com"]}
ABSENT: dict[str, Any] = {"root": None, "live_bench": None, "widgets": [], "edges": []}


def _graph_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/widgets/graph"


async def _graph(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.get(_graph_url(project_id), headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _reconcile(client: AsyncClient, headers: dict[str, str], project_id: str) -> Any:
    return await client.post(f"{_graph_url(project_id)}/reconcile", headers=headers)


async def _installed(
    client: AsyncClient, headers: dict[str, str], project_id: str, **kw: Any
) -> None:
    resp = await install(client, headers, project_id, "bom", grants=FULL_GRANTS, **kw)
    assert resp.status_code == 201, resp.text


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


async def _row_fingerprint(db: AsyncSession, project_id: str) -> tuple[Any, ...]:
    """Everything a write would change: row counts, live counts, version sums."""
    pid = uuid.UUID(project_id)
    live_entities = select(func.count()).where(
        GraphEntity.project_id == pid, GraphEntity.deleted_at.is_(None)
    )
    versions = select(func.coalesce(func.sum(GraphEntity.version), 0)).where(
        GraphEntity.project_id == pid
    )
    live_edges = select(func.count()).where(
        GraphEdge.project_id == pid, GraphEdge.deleted_at.is_(None)
    )
    return (
        await db.scalar(select(func.count()).where(GraphEntity.project_id == pid)),
        await db.scalar(live_entities),
        await db.scalar(versions),
        await db.scalar(select(func.count()).where(GraphEdge.project_id == pid)),
        await db.scalar(live_edges),
    )


# ------------------------------------------------------------- acceptance


async def test_install_bom_shows_a_bom_node_beside_live_bench_and_uninstall_removes_it(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    await consent(db, user["id"])
    _, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    assert await _graph(client, alice_headers, project_id) == ABSENT

    await _installed(client, alice_headers, project_id)
    graph = await _graph(client, alice_headers, project_id)
    assert graph["root"]["type"] == WORKSPACE_KIND and graph["root"]["domain"] == "workspace"
    assert graph["root"]["origin"] == "system" and graph["root"]["name"] == "Workspace"
    assert graph["live_bench"]["type"] == LIVE_BENCH_KIND
    assert [w["name"] for w in graph["widgets"]] == ["BOM"]
    bom = graph["widgets"][0]
    assert bom["type"] == WIDGET_KIND and bom["domain"] == "workspace"
    assert bom["origin"] == "system"
    assert bom["properties"] == {
        "slug": "bom",
        "version": "1.2.0",
        "enabled": True,
        "blocked": False,
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

    listed = await client.get(
        f"/api/v1/projects/{project_id}/entities",
        params={"domain": "workspace"},
        headers=alice_headers,
    )
    assert listed.status_code == 200, listed.text
    assert sorted(e["type"] for e in listed.json()["data"]) == [
        LIVE_BENCH_KIND,
        WIDGET_KIND,
        WORKSPACE_KIND,
    ]

    gone = await client.delete(ext_url(project_id, "bom"), headers=alice_headers)
    assert gone.status_code == 204, gone.text
    after = await _graph(client, alice_headers, project_id)
    assert after["widgets"] == [] and len(after["edges"]) == 1
    node = await db.get(GraphEntity, uuid.UUID(bom["id"]))
    assert node is not None and node.deleted_at is not None
    assert await _dangling(db, project_id) == 0
    uninstall_events = await events_of(db, "extension.uninstall")
    assert uninstall_events[-1].payload["graph_node_id"] == bom["id"]

    # Reinstall: a NEW node, the tombstone is never resurrected.
    await _installed(client, alice_headers, project_id)
    again = await _graph(client, alice_headers, project_id)
    assert len(again["widgets"]) == 1 and again["widgets"][0]["id"] != bom["id"]
    assert await _dangling(db, project_id) == 0


async def test_disable_enable_block_and_update_mirror_into_the_node(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    team_id, project_id = await project_for(client, alice_headers)
    catalog = await seed_extension(
        db, "bom", {"1.2.0": manifest_with("1.2.0"), "1.3.0": manifest_with("1.3.0")}
    )
    await _installed(client, alice_headers, project_id, version="1.2.0")

    async def props() -> dict[str, Any]:
        widgets = (await _graph(client, alice_headers, project_id))["widgets"]
        assert len(widgets) == 1
        return dict(widgets[0]["properties"])

    off = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=alice_headers
    )
    assert off.status_code == 200, off.text
    assert (await props())["enabled"] is False
    on = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": True}, headers=alice_headers
    )
    assert on.status_code == 200
    assert (await props())["enabled"] is True

    moved = await install(
        client, alice_headers, project_id, "bom", grants=FULL_GRANTS, version="1.3.0"
    )
    assert moved.status_code == 200, moved.text
    assert (await props())["version"] == "1.3.0"

    # A team block: the node stays, marked blocked and not enabled (visible after
    # a reconcile — policy writes live on the team routes and do not touch the layer).
    await seed_policy(db, team_id, catalog.extension_id, blocked=True)
    healed = await _reconcile(client, alice_headers, project_id)
    assert healed.status_code == 200, healed.text
    blocked = await props()
    assert blocked["blocked"] is True and blocked["enabled"] is False


# --------------------------------------------------- read is read, heal is gated


async def test_the_read_route_writes_nothing_even_for_a_viewer(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team_id, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    await _installed(client, alice_headers, project_id)
    # Tombstone the widget node behind the API's back: a pure read must NOT heal it.
    await db.execute(
        update(GraphEntity)
        .where(GraphEntity.project_id == uuid.UUID(project_id), GraphEntity.kind == WIDGET_KIND)
        .values(deleted_at=utcnow())
    )
    await db.commit()
    before = await _row_fingerprint(db, project_id)

    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    for headers in (bob_headers, alice_headers):
        read = await client.get(_graph_url(project_id), headers=headers)
        assert read.status_code == 200, read.text
        assert read.json()["data"]["widgets"] == []  # honest: the node is gone
    db.expire_all()
    assert await _row_fingerprint(db, project_id) == before


async def test_reconcile_heals_behind_the_member_floor_and_the_write_budget(
    client: AsyncClient,
    db: AsyncSession,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    user = await me(client, alice_headers)
    await consent(db, user["id"])
    team_id, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    await _installed(client, alice_headers, project_id)
    pid = uuid.UUID(project_id)
    # Simulate a pre-ST2 install: wipe the whole layer.
    for edge in (await db.scalars(select(GraphEdge).where(GraphEdge.project_id == pid))).all():
        await db.delete(edge)
    for node in (await db.scalars(select(GraphEntity).where(GraphEntity.project_id == pid))).all():
        await db.delete(node)
    await db.commit()

    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    viewer = await _reconcile(client, bob_headers, project_id)
    assert viewer.status_code == 403 and viewer.json()["error"]["code"] == "forbidden"
    assert await _graph(client, alice_headers, project_id) == ABSENT  # nothing happened

    healed = await _reconcile(client, alice_headers, project_id)
    assert healed.status_code == 200, healed.text
    data = healed.json()["data"]
    assert [w["properties"]["slug"] for w in data["widgets"]] == ["bom"]
    assert len(data["edges"]) == 2
    assert data["reconciled"]["created"] >= 1 and data["reconciled"]["pruned"] == 0
    assert await _dangling(db, project_id) == 0
    events = await events_of(db, "widget_bundle.graph_reconciled")
    assert len(events) == 1 and events[0].payload["created"] >= 1

    idle = await _reconcile(client, alice_headers, project_id)
    assert idle.json()["data"]["reconciled"] == {"created": 0, "refreshed": 0, "pruned": 0}
    assert len(await events_of(db, "widget_bundle.graph_reconciled")) == 1  # no-op → no event

    # The SHARED install-write budget: the install (1) and two reconciles (2, 3).
    app.state.settings.extension_install_writes_per_minute_per_user = 3
    over = await _reconcile(client, alice_headers, project_id)
    assert over.status_code == 429, over.text
    assert over.headers.get("retry-after") == "60"


# ---------------------------------------------------------------- isolation


async def test_team_b_cannot_read_team_a_layer_and_a_viewer_can(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team_id, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    await _installed(client, alice_headers, project_id)
    assert (await client.get(_graph_url(project_id), headers=bob_headers)).status_code == 404
    assert (await _reconcile(client, bob_headers, project_id)).status_code == 404
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    viewer = await client.get(_graph_url(project_id), headers=bob_headers)
    assert viewer.status_code == 200, viewer.text
    assert [w["name"] for w in viewer.json()["data"]["widgets"]] == ["BOM"]
    _, bobs_project = await project_for(client, bob_headers)
    assert await _graph(client, bob_headers, bobs_project) == ABSENT


async def test_the_layer_is_read_only_through_the_generic_entity_routes(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    """SOLUSDEV-242 added PATCH/DELETE on `/entities/{id}` for the manual Physical
    Robot subtype only; a `system`-origin workspace node must be refused (ADR-027:
    edit rights are an `origin == manual` allowlist), and the row must not move."""
    _, project_id = await project_for(client, alice_headers)
    await seed_extension(db, "bom")
    await _installed(client, alice_headers, project_id)
    root_id = (await _graph(client, alice_headers, project_id))["root"]["id"]
    url = f"/api/v1/projects/{project_id}/entities/{root_id}"
    patched = await client.patch(
        url, json={"name": "Renamed"}, headers={**alice_headers, "If-Match": "1"}
    )
    assert patched.status_code == 409, patched.text
    assert patched.json()["error"]["code"] == "conflict"
    deleted = await client.delete(url, headers={**alice_headers, "If-Match": "1"})
    assert deleted.status_code == 409, deleted.text
    still = await db.get(GraphEntity, uuid.UUID(root_id))
    assert still is not None and still.deleted_at is None and still.name == "Workspace"


# ----------------------------------------------------- publish → install e2e


async def test_a_published_v1_bundle_installs_and_registers_its_node_end_to_end(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """The path the STORE ST2 real run broke: publish (stores the manifest) →
    approve → install (re-parses the STORED manifest) → node. No seeded rows."""
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
