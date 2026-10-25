"""SOLUSDEV-320 P5-T7: `GET /projects/{id}/history` (docs/api/solus.md §9) and the emitters
that write one `activities` row with `entity_ids` + `why_ref` each."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from conftest import add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.checkers.interface import Severity
from solus_api.connectors.contracts import Domain as ConnectorDomain
from solus_api.connectors.contracts import EntityOut, RelationOut, SyncResult
from solus_api.connectors.runtime import run_sync
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.graph.findings import FindingSpec, raise_finding, resolve_finding
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.local_sources import LocalHardwareSources
from solus_api.hardware.store import put_entity_config, robot_root
from solus_api.models import Activity, Domain, GraphEntity
from solus_api.services.activity import record_activity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_edges_routes import RecordingGraphHub, seed_candidates
from test_hardware_router import _hw_url
from test_host_topology import setup_host
from test_runtime import ScriptedConnector, _seed_source
from test_topology_proposals import setup, url

ROW_KEYS = {
    "id",
    "type",
    "domain",
    "actor_id",
    "project_id",
    "payload",
    "entity_ids",
    "why_ref",
    "created_at",
}


def _history_url(project_id: str, query: str = "") -> str:
    return f"/api/v1/projects/{project_id}/history{query}"


async def _history_project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"], user["id"]


async def _history_rows(db: AsyncSession, project_id: uuid.UUID, kind: str) -> list[Activity]:
    return list(
        await db.scalars(
            select(Activity)
            .where(Activity.project_id == project_id, Activity.type == kind)
            .order_by(Activity.created_at)
        )
    )


async def _seed_history(
    db: AsyncSession, project_id: str, team_id: str, actor: str
) -> dict[str, Any]:
    pid, tid, uid = uuid.UUID(project_id), uuid.UUID(team_id), uuid.UUID(actor)
    part, other = uuid.uuid4(), uuid.uuid4()
    rows = {
        "sync": record_activity(
            db, team_id=tid, activity_type="sync.completed", project_id=pid, domain="code"
        ),
        "edge": record_activity(
            db,
            team_id=tid,
            activity_type="edge.confirmed",
            actor_id=uid,
            project_id=pid,
            domain="electrical",
            entity_ids=[part, other],
            why_ref="conv-1",
        ),
        "config": record_activity(
            db,
            team_id=tid,
            activity_type="config.bumped",
            project_id=pid,
            domain="electrical",
            entity_ids=[part],
        ),
    }
    rows["sync"].created_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()
    return {"part": part, "other": other, **rows}


# ------------------------------------------------------------------- the route


async def test_history_rows_carry_entity_ids_and_filters_narrow_within_the_project(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, team_id, alice = await _history_project(client, alice_headers)
    seeded = await _seed_history(db, project_id, team_id, alice)
    other_project, other_team, bob = await _history_project(client, bob_headers)
    await _seed_history(db, other_project, other_team, bob)

    resp = await client.get(_history_url(project_id), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body["data"]
    # The project's own `project.created` row (API-made) sits in the feed too.
    assert [r["type"] for r in rows] == [
        "config.bumped",
        "edge.confirmed",
        "project.created",
        "sync.completed",
    ]
    assert all(set(r) == ROW_KEYS and r["project_id"] == project_id for r in rows)
    edge = rows[1]
    assert edge["entity_ids"] == [str(seeded["part"]), str(seeded["other"])]
    assert edge["why_ref"] == "conv-1" and edge["actor_id"] == alice
    assert rows[3]["entity_ids"] == [] and rows[3]["why_ref"] is None
    assert body["meta"]["has_next"] is False and body["meta"]["next_cursor"] is None

    by_entity = await client.get(
        _history_url(project_id, f"?entity={seeded['other']}"), headers=alice_headers
    )
    assert [r["type"] for r in by_entity.json()["data"]] == ["edge.confirmed"]
    both = await client.get(
        _history_url(project_id, f"?entity={seeded['part']}"), headers=alice_headers
    )
    assert [r["type"] for r in both.json()["data"]] == ["config.bumped", "edge.confirmed"]
    by_domain = await client.get(_history_url(project_id, "?domain=code"), headers=alice_headers)
    assert [r["type"] for r in by_domain.json()["data"]] == ["sync.completed"]
    by_actor = await client.get(_history_url(project_id, f"?actor={alice}"), headers=alice_headers)
    assert [r["type"] for r in by_actor.json()["data"]] == ["edge.confirmed", "project.created"]
    since = quote((datetime.now(UTC) - timedelta(hours=1)).isoformat())  # `+00:00` must encode
    recent = await client.get(_history_url(project_id, f"?since={since}"), headers=alice_headers)
    assert [r["type"] for r in recent.json()["data"]] == [
        "config.bumped",
        "edge.confirmed",
        "project.created",
    ]
    naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    assert (
        await client.get(
            _history_url(project_id, f"?since={naive.isoformat()}"), headers=alice_headers
        )
    ).json()["data"] == recent.json()["data"]
    # Tenancy: a non-member is 404; a viewer reads; a member of another project never sees
    # these rows.
    assert (await client.get(_history_url(project_id), headers=bob_headers)).status_code == 404
    bob_user = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob_user, team_id, role="viewer")
    viewed = await client.get(_history_url(project_id), headers=bob_headers)
    assert viewed.status_code == 200 and len(viewed.json()["data"]) == 4
    bobs = await client.get(_history_url(other_project), headers=bob_headers)
    assert {r["project_id"] for r in bobs.json()["data"]} == {other_project}
    assert (await client.get(_history_url(project_id))).status_code == 401
    assert (
        await client.get(_history_url(project_id, "?entity=nope"), headers=alice_headers)
    ).status_code == 422


async def test_history_cursor_pagination_and_limit_bounds(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, team_id, alice = await _history_project(client, alice_headers)
    await _seed_history(db, project_id, team_id, alice)

    first = await client.get(_history_url(project_id, "?limit=2"), headers=alice_headers)
    body = first.json()
    assert [r["type"] for r in body["data"]] == ["config.bumped", "edge.confirmed"]
    assert body["meta"]["has_next"] is True and body["meta"]["next_cursor"]
    rest = await client.get(
        _history_url(project_id, f"?limit=2&cursor={body['meta']['next_cursor']}"),
        headers=alice_headers,
    )
    assert [r["type"] for r in rest.json()["data"]] == ["project.created", "sync.completed"]
    assert rest.json()["meta"]["has_next"] is False
    assert (
        await client.get(_history_url(project_id, "?limit=201"), headers=alice_headers)
    ).status_code == 422
    assert (
        await client.get(_history_url(project_id, "?limit=0"), headers=alice_headers)
    ).status_code == 422
    assert (
        await client.get(_history_url(project_id, "?cursor=%%%"), headers=alice_headers)
    ).status_code == 400


# ---------------------------------------------------------------- the emitters


async def test_edge_confirm_and_decline_record_one_row_each(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, _, entities, edges = await seed_candidates(client, alice_headers, db)
    app.state.graph_hub = RecordingGraphHub()
    user = await me(client, alice_headers)
    base = f"/api/v1/projects/{pid}/edges"

    assert (
        await client.post(f"{base}/{edges['commands'].id}/confirm", headers=alice_headers)
    ).status_code == 200
    assert (
        await client.post(
            f"{base}/{edges['reads'].id}/decline", headers=alice_headers, json={"reason": "no"}
        )
    ).status_code == 200

    (confirmed,) = await _history_rows(db, pid, "edge.confirmed")
    assert confirmed.entity_ids == [str(entities["code"].id), str(entities["servo"].id)]
    assert confirmed.actor_id == uuid.UUID(user["id"]) and confirmed.why_ref is None
    assert confirmed.payload["edge_id"] == str(edges["commands"].id)
    assert confirmed.payload["relation_type"] == "commands"
    (declined,) = await _history_rows(db, pid, "edge.declined")
    assert declined.entity_ids == [str(entities["code"].id), str(entities["sensor"].id)]
    assert declined.payload["reason"] == "no"


async def test_config_bump_records_the_subject(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, alice = await _history_project(client, alice_headers)
    pid = uuid.UUID(project_id)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=alice_headers,
        json={"type": "physical_robot", "name": "Bench arm"},
    )
    robot_id = uuid.UUID(resp.json()["data"]["id"])
    robot = await robot_root(db, pid, robot_id)
    config = EntityHardwareConfig.model_validate(
        {"schema_version": 2, "entity_id": str(robot_id), "provenance": {}}
    )
    entry = await put_entity_config(
        db, pid, robot, config, expected_version=0, created_by=uuid.UUID(alice)
    )
    await db.commit()

    (row,) = await _history_rows(db, pid, "config.bumped")
    assert row.entity_ids == [str(robot_id)] and row.actor_id == uuid.UUID(alice)
    assert row.payload == {"entry_id": str(entry.id), "config_version": 1}
    assert row.domain == robot.domain.value


async def test_finding_resolve_records_the_fix_as_why(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, alice = await _history_project(client, alice_headers)
    pid, user_id = uuid.UUID(project_id), uuid.UUID(alice)
    subject = GraphEntity(project_id=pid, kind="component", domain=Domain.ELECTRICAL, name="U1")
    fix = GraphEntity(project_id=pid, kind="code_file", domain=Domain.CODE, name="fix.ino")
    db.add_all([subject, fix])
    await db.flush()
    finding = await raise_finding(
        db,
        pid,
        FindingSpec(
            rule_id="i2c_address_conflict",
            severity=Severity.WARNING,
            source="checker",
            headline="0x68 used twice",
            subjects=[subject.id],
            domain=Domain.ELECTRICAL,
        ),
    )
    await resolve_finding(db, pid, finding.id, user_id, note="moved to 0x69", fix_ref=fix.id)
    await db.commit()

    (row,) = await _history_rows(db, pid, "finding.resolved")
    assert row.entity_ids == [str(finding.id), str(subject.id)]
    assert row.why_ref == str(fix.id) and row.actor_id == user_id
    assert row.payload["rule_id"] == "i2c_address_conflict"
    assert row.domain == "electrical"


async def test_sync_completed_names_the_source_root_entity(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    repo = EntityOut(source_key="octo/r", type="code_repo", domain=ConnectorDomain.CODE, name="r")
    file = EntityOut(source_key="a.py", type="code_file", domain=ConnectorDomain.CODE, name="a.py")
    result = SyncResult(
        entities=[repo, file],
        relations=[RelationOut(from_key="octo/r", to_key="a.py", type="contains")],
        cursor={"sha": "abc"},
    )

    sync_id = await run_sync(
        source_id=source.id,
        sessionmaker=maker,
        connector=ScriptedConnector([result]),
        secret_store=store,
    )

    async with maker() as db:
        (row,) = await _history_rows(db, source.project_id, "sync.completed")
        root = await db.scalar(
            select(GraphEntity).where(
                GraphEntity.source_id == source.id, GraphEntity.kind == "code_repo"
            )
        )
        assert root is not None and row.entity_ids == [str(root.id)]
        assert row.team_id == source.team_id and row.domain == "code"
        assert row.payload["source_id"] == str(source.id)
        assert row.payload["sync_id"] == str(sync_id)


async def test_topology_confirm_records_the_robot_and_reviewed_rows(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.hardware.topology_acceptance import ExtractionConfirm, TopologyAcceptanceService

    project, _, robot, body, _, _ = await setup(client, alice_headers, app, tmp_path, monkeypatch)
    proposal = (await client.post(url(project, robot), headers=alice_headers, json=body)).json()[
        "data"
    ]
    user = (await me(client, alice_headers))["id"]
    service = TopologyAcceptanceService(
        db,
        uuid.UUID(project),
        uuid.UUID(user),
        LocalHardwareSources.for_local_runner(app.state.bench_local),
    )
    request = ExtractionConfirm.model_validate(
        {
            **body,
            "proposal_digest": proposal["proposal_digest"],
            "operation_id": str(uuid.uuid4()),
            "selections": [{"row_index": 0, "name": "Reviewed elbow"}],
        }
    )
    result, _ = await service.confirm(uuid.UUID(robot), request)
    replay, replayed = await service.confirm(uuid.UUID(robot), request)
    await db.commit()
    assert replayed

    (row,) = await _history_rows(db, uuid.UUID(project), "topology.confirmed")
    assert row.entity_ids == [robot, body["brain_id"], *map(str, result.entity_ids)]
    assert row.actor_id == uuid.UUID(user) and row.domain == "electrical"
    assert row.payload["operation_id"] == str(request.operation_id)


async def test_host_confirm_records_the_robot_and_machine(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    base = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(base + "/propose", headers=alice_headers, json=body)
    payload = {**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]}
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    assert (await client.post(base + "/confirm", headers=headers, json=payload)).status_code == 200
    assert (await client.post(base + "/confirm", headers=headers, json=payload)).status_code == 200

    (row,) = await _history_rows(db, uuid.UUID(project), "host.confirmed")
    assert row.entity_ids == [robot, body["endpoint_id"], body["software_entity_id"]]
    assert row.payload["machine_id"] == body["machine_id"]
    assert row.domain == "runtime"
