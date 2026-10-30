"""routers/edges.py — docs/api/relations.md §3: candidates, confirm, decline (SOLUSDEV-320)."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.graph.edges import write_edge
from solus_api.models import Domain, GraphEdge, GraphEntity
from solus_contracts.relations import EdgeEvidence, EvidenceKind
from sqlalchemy.ext.asyncio import AsyncSession


class RecordingGraphHub:
    def __init__(self) -> None:
        self.frames: list[tuple[uuid.UUID, dict[str, Any]]] = []

    async def publish(self, project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        self.frames.append((project_id, frame))


async def seed_candidates(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession
) -> tuple[uuid.UUID, str, dict[str, GraphEntity], dict[str, GraphEdge]]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    pid = uuid.UUID(project["id"])
    entities = {}
    for name in ("code", "servo", "sensor"):
        row = GraphEntity(
            project_id=pid,
            kind="code_file" if name == "code" else "part",
            domain=Domain.CODE if name == "code" else Domain.ELECTRICAL,
            origin="manual",
            name=name,
        )
        db.add(row)
        entities[name] = row
    await db.flush()
    edges = {}
    for key, (src, dst, relation, confidence) in {
        "commands": ("code", "servo", "commands", 0.55),
        "reads": ("code", "sensor", "reads", 0.6),
        "fact": ("code", "servo", "wires", 1.0),
    }.items():
        edges[key] = await write_edge(
            db,
            project_id=pid,
            src_id=entities[src].id,
            dst_id=entities[dst].id,
            relation_type=relation,
            origin="inferred",
            confidence=confidence,
            evidence=[EdgeEvidence(kind=EvidenceKind.FIRMWARE_SYMBOL, ref="fw.ino:3")],
            created_by=None,
        )
    await db.commit()
    return pid, team["id"], entities, edges


def base(pid: uuid.UUID) -> str:
    return f"/api/v1/projects/{pid}/edges"


async def test_candidates_are_listed_scoped_and_filtered(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    pid, _, entities, edges = await seed_candidates(client, alice_headers, db)
    other_pid, _, _, _ = await seed_candidates(client, bob_headers, db)

    listed = await client.get(base(pid) + "/candidates", headers=alice_headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert [r["id"] for r in rows] == [str(edges["reads"].id), str(edges["commands"].id)]
    assert rows[1] == {
        "id": str(edges["commands"].id),
        "project_id": str(pid),
        "source_id": None,
        "origin": "inferred",
        "type": "commands",
        "from_entity_id": str(entities["code"].id),
        "to_entity_id": str(entities["servo"].id),
        "confidence": 0.55,
        "domain_pair": "code<->electrical",
        "properties": rows[1]["properties"],
        "created_at": rows[1]["created_at"],
    }
    assert rows[1]["properties"]["evidence"] == [
        {"kind": "firmware_symbol", "ref": "fw.ino:3", "detail": None}
    ]
    by_type = await client.get(base(pid) + "/candidates?relation_type=reads", headers=alice_headers)
    assert [r["id"] for r in by_type.json()["data"]] == [str(edges["reads"].id)]
    by_subject = await client.get(
        base(pid) + f"/candidates?subject={entities['servo'].id}", headers=alice_headers
    )
    assert [r["id"] for r in by_subject.json()["data"]] == [str(edges["commands"].id)]
    limited = await client.get(base(pid) + "/candidates?limit=1", headers=alice_headers)
    assert len(limited.json()["data"]) == 1
    assert (
        await client.get(base(pid) + "/candidates?limit=0", headers=alice_headers)
    ).status_code == 422
    # Non-member → 404 on the project; Bob's own project never shows Alice's rows.
    assert (await client.get(base(pid) + "/candidates", headers=bob_headers)).status_code == 404
    bobs = await client.get(base(other_pid) + "/candidates", headers=bob_headers)
    assert {r["project_id"] for r in bobs.json()["data"]} == {str(other_pid)}
    assert (await client.get(base(pid) + "/candidates")).status_code == 401


async def test_confirm_makes_the_edge_manual_and_publishes(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, _, _, edges = await seed_candidates(client, alice_headers, db)
    hub = RecordingGraphHub()
    app.state.graph_hub = hub
    user = await me(client, alice_headers)

    confirmed = await client.post(
        base(pid) + f"/{edges['commands'].id}/confirm", headers=alice_headers
    )
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()["data"]
    assert data["origin"] == "manual" and data["confidence"] == 1.0
    assert data["properties"]["confirmed_by"] == user["id"]
    assert {(e["kind"], e["ref"]) for e in data["properties"]["evidence"]} == {
        ("firmware_symbol", "fw.ino:3"),
        ("user_confirmed", user["id"]),
    }
    assert [(p, f["type"]) for p, f in hub.frames] == [(pid, "graph.changed")]
    listed = await client.get(base(pid) + "/candidates", headers=alice_headers)
    assert [r["id"] for r in listed.json()["data"]] == [str(edges["reads"].id)]
    # Confirmed once: it is no longer a candidate, so a second confirm is 404.
    again = await client.post(base(pid) + f"/{edges['commands'].id}/confirm", headers=alice_headers)
    assert again.status_code == 404
    assert (
        await client.post(base(pid) + f"/{edges['fact'].id}/confirm", headers=alice_headers)
    ).status_code == 404


async def test_decline_soft_deletes_and_is_not_reproposed(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, _, entities, edges = await seed_candidates(client, alice_headers, db)
    hub = RecordingGraphHub()
    app.state.graph_hub = hub
    user = await me(client, alice_headers)

    declined = await client.post(
        base(pid) + f"/{edges['reads'].id}/decline",
        headers=alice_headers,
        json={"reason": "wrong pin"},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["data"]["properties"]["declined_reason"] == "wrong pin"
    assert declined.json()["data"]["properties"]["declined_by"] == user["id"]
    assert [f["type"] for _, f in hub.frames] == ["graph.changed"]
    listed = await client.get(base(pid) + "/candidates", headers=alice_headers)
    assert [r["id"] for r in listed.json()["data"]] == [str(edges["commands"].id)]
    row = await db.get(GraphEdge, edges["reads"].id)
    assert row is not None
    await db.refresh(row)
    assert row.deleted_at is not None
    # A rerun with the same evidence does not re-propose it; new evidence does.
    same = await write_edge(
        db,
        project_id=pid,
        src_id=entities["code"].id,
        dst_id=entities["sensor"].id,
        relation_type="reads",
        origin="inferred",
        confidence=0.6,
        evidence=[EdgeEvidence(kind=EvidenceKind.FIRMWARE_SYMBOL, ref="fw.ino:3")],
        created_by=None,
    )
    assert same.id == row.id and same.deleted_at is not None
    fresh = await write_edge(
        db,
        project_id=pid,
        src_id=entities["code"].id,
        dst_id=entities["sensor"].id,
        relation_type="reads",
        origin="inferred",
        confidence=0.6,
        evidence=[EdgeEvidence(kind=EvidenceKind.FIRMWARE_SYMBOL, ref="fw.ino:9")],
        created_by=None,
    )
    assert fresh.id != row.id and fresh.deleted_at is None
    # Decline with no body at all is fine too.
    await db.commit()
    bare = await client.post(base(pid) + f"/{fresh.id}/decline", headers=alice_headers)
    assert bare.status_code == 200, bare.text
    assert bare.json()["data"]["properties"]["declined_reason"] is None
    assert (
        await client.post(
            base(pid) + f"/{fresh.id}/decline", headers=alice_headers, json={"reason": "again"}
        )
    ).status_code == 404


async def test_viewer_is_403_and_foreign_edges_are_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    pid, team_id, _, edges = await seed_candidates(client, alice_headers, db)
    other_pid, _, _, other_edges = await seed_candidates(client, bob_headers, db)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")

    assert (await client.get(base(pid) + "/candidates", headers=bob_headers)).status_code == 200
    for action, body in (("confirm", None), ("decline", {"reason": "no"})):
        resp = await client.post(
            base(pid) + f"/{edges['commands'].id}/{action}", headers=bob_headers, json=body
        )
        assert resp.status_code == 403, (action, resp.text)
    row = await db.get(GraphEdge, edges["commands"].id)
    assert row is not None and row.origin == "inferred" and row.deleted_at is None
    # Alice confirming Bob's edge through her own project: 404, never a cross-project write.
    foreign = await client.post(
        base(pid) + f"/{other_edges['commands'].id}/confirm", headers=alice_headers
    )
    assert foreign.status_code == 404
    unknown = await client.post(
        base(pid) + f"/{uuid.uuid4()}/decline", headers=alice_headers, json={}
    )
    assert unknown.status_code == 404
    assert (
        await client.post(
            base(other_pid) + f"/{other_edges['commands'].id}/confirm", headers=alice_headers
        )
    ).status_code == 404
    bad = await client.post(
        base(pid) + f"/{edges['commands'].id}/decline", headers=alice_headers, json={"reason": 7}
    )
    assert bad.status_code == 422
