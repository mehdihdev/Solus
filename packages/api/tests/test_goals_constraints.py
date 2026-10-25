"""SOLUSDEV-320 P5-T5: a goal's `linked_run_ids` are mirrored as `verified_by` edges and a
status change lands in history; a compliance constraint feeds the sourcing rules; rulebook
PDFs file under `constraints/rules`."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import add_member, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import Activity, GraphEdge, GraphEntity
from solus_api.services.solus_payloads import ConstraintMeta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_edges_routes import RecordingGraphHub
from test_solus_config import _get, _post, _project, _upload
from test_solus_tree import _patch_payload


async def _seed_runs(db: AsyncSession, project_id: str, n: int) -> list[GraphEntity]:
    rows = [
        GraphEntity(
            project_id=uuid.UUID(project_id),
            kind="bench_run",
            domain="project",
            origin="manual",
            name=f"run {i}",
        )
        for i in range(n)
    ]
    db.add_all(rows)
    await db.commit()
    return rows


async def _goal_project(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str, dict[str, Any]]:
    project_id, team_id = await _project(client, headers)
    goal = (
        await _post(client, headers, project_id, "goals", {"kind": "text", "text": "48 V bus"})
    ).json()["data"]
    return project_id, team_id, goal


async def _verified_by(db: AsyncSession, goal_node: str) -> dict[uuid.UUID, GraphEdge]:
    rows = await db.scalars(
        select(GraphEdge).where(
            GraphEdge.src_id == uuid.UUID(goal_node), GraphEdge.relation_type == "verified_by"
        )
    )
    return {edge.dst_id: edge for edge in rows}


async def _status_rows(db: AsyncSession, project_id: str) -> list[Activity]:
    return list(
        await db.scalars(
            select(Activity)
            .where(
                Activity.project_id == uuid.UUID(project_id),
                Activity.type == "goal.status_changed",
            )
            .order_by(Activity.created_at)
        )
    )


async def test_linked_runs_sync_verified_by_edges_and_status_changes_record_history(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, goal = await _goal_project(client, alice_headers)
    alice = (await me(client, alice_headers))["id"]
    runs = await _seed_runs(db, project_id, 2)
    r1, r2 = runs[0].id, runs[1].id

    ok = await _patch_payload(
        client,
        alice_headers,
        project_id,
        goal["id"],
        {"status": "met", "linked_run_ids": [str(r1), str(r2)]},
    )
    assert ok.status_code == 200, ok.text
    edges = await _verified_by(db, goal["entity_id"])
    assert set(edges) == {r1, r2}
    for run in (r1, r2):
        edge = edges[run]
        assert edge.deleted_at is None and edge.origin == "manual" and edge.confidence == 1.0
        assert edge.attrs["evidence"] == [{"kind": "run", "ref": str(run), "detail": None}]
        assert edge.attrs["created_by"] == alice
    (changed,) = await _status_rows(db, project_id)
    assert changed.entity_ids == [goal["entity_id"]] and changed.why_ref is None
    assert changed.actor_id == uuid.UUID(alice) and changed.domain == "project"
    assert changed.payload == {"entry_id": goal["id"], "from": "open", "to": "met"}

    # Dropping a run retires its edge; the same status records nothing new.
    db.expire_all()
    ok = await _patch_payload(
        client,
        alice_headers,
        project_id,
        goal["id"],
        {"status": "met", "linked_run_ids": [str(r1)]},
    )
    assert ok.status_code == 200, ok.text
    edges = await _verified_by(db, goal["entity_id"])
    assert edges[r1].deleted_at is None and edges[r2].deleted_at is not None
    assert len(await _status_rows(db, project_id)) == 1

    # Re-linking revives the retired edge (one row per run, never a duplicate).
    db.expire_all()
    conversation = uuid.uuid4()
    ok = await _patch_payload(
        client,
        alice_headers,
        project_id,
        goal["id"],
        {
            "status": "dropped",
            "linked_run_ids": [str(r1), str(r2)],
            "linked_conversation_ids": [str(conversation)],
        },
    )
    assert ok.status_code == 200, ok.text
    edges = await _verified_by(db, goal["entity_id"])
    assert len(edges) == 2 and all(e.deleted_at is None for e in edges.values())
    rows = await _status_rows(db, project_id)
    assert len(rows) == 2 and rows[1].why_ref == str(conversation)
    assert rows[1].payload == {"entry_id": goal["id"], "from": "met", "to": "dropped"}

    # An unknown run (or another project's run) is 422 and changes nothing.
    db.expire_all()
    other_project, _ = await _project(client, alice_headers)
    (foreign,) = await _seed_runs(db, other_project, 1)
    for bad in (uuid.uuid4(), foreign.id):
        resp = await _patch_payload(
            client,
            alice_headers,
            project_id,
            goal["id"],
            {"status": "open", "linked_run_ids": [str(bad)]},
        )
        assert resp.status_code == 422, resp.text
        assert "run" in resp.json()["error"]["message"].lower()
    db.expire_all()
    listing = await _get(client, alice_headers, project_id)
    assert listing["sections"]["goals"][0]["payload"]["status"] == "dropped"
    assert len(await _verified_by(db, goal["entity_id"])) == 2
    assert len(await _status_rows(db, project_id)) == 2


def test_constraint_meta_is_quantified_all_or_none_plus_sourcing_lists() -> None:
    ConstraintMeta.model_validate({"excluded_suppliers": ["Acme"], "required_certifications": []})
    ConstraintMeta.model_validate({})
    ConstraintMeta.model_validate(
        {"quantity": "mass", "limit": 2.5, "unit": "kg", "comparator": "<="}
    )
    for half in (
        {"quantity": "mass"},
        {"quantity": "mass", "limit": 2.5, "unit": "kg"},
        {"limit": 1.0, "comparator": "<"},
    ):
        try:
            ConstraintMeta.model_validate(half)
        except ValueError:
            continue
        raise AssertionError(f"half-quantified constraint accepted: {half}")


async def test_compliance_entries_add_to_the_sourcing_rules_deduplicated(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    rules_url = f"/api/v1/projects/{project_id}/sourcing/rules"
    saved = await client.put(
        rules_url, json={"required_certifications": ["rohs"]}, headers=alice_headers
    )
    assert saved.status_code == 200, saved.text
    compliance = (
        await _post(
            client,
            alice_headers,
            project_id,
            "constraints",
            {
                "kind": "text",
                "text": "No Acme parts: export controlled\nSecond line is not the reason",
                "subsection": "compliance",
            },
        )
    ).json()["data"]
    style = (
        await _post(
            client,
            alice_headers,
            project_id,
            "constraints",
            {"kind": "text", "text": "style", "subsection": "style"},
        )
    ).json()["data"]
    for entry, payload in (
        (
            compliance,
            {
                "excluded_suppliers": ["Acme Motors", "acme motors", "Foo Parts"],
                "required_certifications": ["RoHS", "CE"],
            },
        ),
        (style, {"excluded_suppliers": ["Style Only"]}),  # style entries never reach sourcing
    ):
        resp = await _patch_payload(client, alice_headers, project_id, entry["id"], payload)
        assert resp.status_code == 200, resp.text

    rules = (await client.get(rules_url, headers=alice_headers)).json()["data"]
    assert rules["excluded_suppliers"] == [
        {"name": "Acme Motors", "reason": "No Acme parts: export controlled"},
        {"name": "Foo Parts", "reason": "No Acme parts: export controlled"},
    ]
    assert rules["required_certifications"] == ["rohs", "CE"]

    removed = await client.delete(
        f"/api/v1/projects/{project_id}/solus/entries/{compliance['id']}", headers=alice_headers
    )
    assert removed.status_code == 204
    rules = (await client.get(rules_url, headers=alice_headers)).json()["data"]
    assert rules["excluded_suppliers"] == [] and rules["required_certifications"] == ["rohs"]


async def test_rulebook_pdfs_file_under_constraints_rules(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    artifact_id = await _upload(client, alice_headers, project_id)
    resp = await _post(
        client,
        alice_headers,
        project_id,
        "constraints",
        {
            "kind": "artifact",
            "artifact_id": artifact_id,
            "name": "rules.pdf",
            "subsection": "rules",
        },
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()["data"]
    assert entry["kind"] == "artifact" and entry["subsection"] == "rules"
    listing = await _get(client, alice_headers, project_id)
    (row,) = listing["sections"]["constraints"]
    assert row["id"] == entry["id"] and row["subsection"] == "rules"
    assert row["artifact_id"] == artifact_id and row["name"] == "rules.pdf"


async def test_a_viewer_reads_goals_but_cannot_patch_a_status(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id, goal = await _goal_project(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    listing = await _get(client, bob_headers, project_id)
    assert [g["id"] for g in listing["sections"]["goals"]] == [goal["id"]]
    resp = await _patch_payload(client, bob_headers, project_id, goal["id"], {"status": "met"})
    assert resp.status_code == 403, resp.text


async def test_a_limit_edit_publishes_graph_changed_so_budgets_recompute(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    project_id, _ = await _project(client, alice_headers)
    rule = (
        await _post(
            client,
            alice_headers,
            project_id,
            "constraints",
            {"kind": "text", "text": "mass", "subsection": "rules"},
        )
    ).json()["data"]
    hub = RecordingGraphHub()
    app.state.graph_hub = hub
    payload = ConstraintMeta(quantity="mass", limit=1, unit="kg", comparator="<=").model_dump(
        mode="json"
    )
    resp = await _patch_payload(client, alice_headers, project_id, rule["id"], payload)
    assert resp.status_code == 200, resp.text
    assert [(str(p), f["type"]) for p, f in hub.frames] == [(project_id, "graph.changed")]
