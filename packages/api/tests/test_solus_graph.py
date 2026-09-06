"""SOLUSDEV-242: real .solus navigation identities and legacy data repair."""

import asyncio
import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from conftest import add_member, me
from httpx import AsyncClient
from solus_api.models import (
    Artifact,
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    utcnow,
)
from sqlalchemy import delete, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from test_solus_config import SECTIONS, _get, _post, _project, _upload


async def _graph(db: AsyncSession, project_id: str) -> tuple[list[GraphEntity], list[GraphEdge]]:
    pid = uuid.UUID(project_id)
    nodes = list(
        await db.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == pid, GraphEntity.deleted_at.is_(None)
            )
        )
    )
    edges = list(
        await db.scalars(
            select(GraphEdge).where(GraphEdge.project_id == pid, GraphEdge.deleted_at.is_(None))
        )
    )
    return nodes, edges


async def test_creation_is_one_root_with_five_real_section_children(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    nodes, edges = await _graph(db, project_id)
    assert len(nodes) == 6
    root = next(node for node in nodes if node.kind == "solus_config")
    sections = {node.attrs["section"]: node for node in nodes if node.kind == "solus_section"}
    assert set(sections) == set(SECTIONS)
    assert all(node.domain == Domain.PROJECT and node.origin == "manual" for node in nodes)
    assert {(edge.src_id, edge.dst_id, edge.relation_type) for edge in edges} == {
        (root.id, node.id, "contains") for node in sections.values()
    }
    assert {node.id for node in nodes} - {edge.dst_id for edge in edges} == {root.id}


@pytest.mark.parametrize("section,kind", [("details", "solus_note"), ("errors", "solus_error")])
async def test_note_edit_keeps_identity_and_delete_only_removes_its_node_and_edges(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, section: str, kind: str
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await _post(
        client,
        alice_headers,
        project_id,
        section,
        {
            "kind": "text",
            "text": "  A long note\n" + "sensitive data " * 150,
        },
    )
    assert response.status_code == 201, response.text
    entry = response.json()["data"]
    assert entry["entity_id"] is not None
    node_id = uuid.UUID(entry["entity_id"])
    node = await db.get(GraphEntity, node_id)
    assert node is not None and node.kind == kind
    assert node.attrs == {"solus_entry_id": entry["id"], "section": section}
    assert 0 < len(node.name) <= 120 and "\n" not in node.name
    before, edges = await _graph(db, project_id)
    container = next(
        n for n in before if n.kind == "solus_section" and n.attrs["section"] == section
    )
    assert any(
        e.src_id == container.id and e.dst_id == node.id and e.relation_type == "contains"
        for e in edges
    )
    other = (
        await _post(client, alice_headers, project_id, section, {"kind": "text", "text": "Keep me"})
    ).json()["data"]
    cross = GraphEdge(
        project_id=uuid.UUID(project_id),
        src_id=node.id,
        dst_id=uuid.UUID(other["entity_id"]),
        relation_type="references",
        domain_pair="project<->project",
        origin="manual",
    )
    db.add(cross)
    await db.commit()
    patched = await client.patch(
        f"/api/v1/projects/{project_id}/solus/entries/{entry['id']}",
        json={"text": "Updated error diagnosis"},
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["entity_id"] == entry["entity_id"]
    await db.refresh(node)
    assert node.name == "Updated error diagnosis"
    assert node.attrs == {"solus_entry_id": entry["id"], "section": section}
    removed = await client.delete(
        f"/api/v1/projects/{project_id}/solus/entries/{entry['id']}", headers=alice_headers
    )
    assert removed.status_code == 204, removed.text
    nodes, remaining_edges = await _graph(db, project_id)
    assert {n.id for n in nodes} == {n.id for n in before if n.id != node_id} | {
        uuid.UUID(other["entity_id"])
    }
    assert all(e.src_id != node_id and e.dst_id != node_id for e in remaining_edges)
    assert (await _get(client, alice_headers, project_id))["sections"][section][0]["id"] == other[
        "id"
    ]


async def _legacy_entries(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession, project_id: str
) -> tuple[SolusEntry, dict[str, Any], str]:
    artifact_id = await _upload(client, headers, project_id)
    document = (
        await _post(
            client,
            headers,
            project_id,
            "docs",
            {
                "kind": "artifact",
                "artifact_id": artifact_id,
                "name": "rules.pdf",
            },
        )
    ).json()["data"]
    # Reconstruct W1 storage: no section nodes or note identities, document retained.
    legacy_document = await db.get(GraphEntity, uuid.UUID(document["entity_id"]))
    assert legacy_document is not None
    legacy_document.attrs = {
        key: value for key, value in legacy_document.attrs.items() if key != "solus_entry_id"
    }
    await db.execute(
        delete(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project_id), GraphEntity.kind == "solus_section"
        )
    )
    note = SolusEntry(
        project_id=uuid.UUID(project_id),
        section=SolusSection.ERRORS,
        kind=SolusEntryKind.SOL,
        text="Legacy failure\nDetails remain intact",
        author="sol",
    )
    deleted = SolusEntry(
        project_id=uuid.UUID(project_id),
        section=SolusSection.DOCS,
        kind=SolusEntryKind.TEXT,
        text="Deleted entry",
        author="user",
        deleted_at=utcnow(),
    )
    db.add_all([note, deleted])
    await db.commit()
    return note, document, artifact_id


async def test_concurrent_get_backfills_legacy_once_preserving_artifact_identity_and_bytes(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    note, document, artifact_id = await _legacy_entries(client, alice_headers, db, project_id)
    replies = await asyncio.gather(*[_get(client, alice_headers, project_id) for _ in range(6)])
    assert len({reply["entity_id"] for reply in replies}) == 1
    assert all(reply["sections"]["errors"][0]["entity_id"] is not None for reply in replies)
    assert len({reply["sections"]["errors"][0]["entity_id"] for reply in replies}) == 1
    await db.refresh(note)
    assert note.text == "Legacy failure\nDetails remain intact"
    nodes, edges = await _graph(db, project_id)
    assert len(nodes) == 8 and len(edges) == 8
    document_node = next(node for node in nodes if str(node.id) == document["entity_id"])
    assert document_node.attrs["solus_entry_id"] == document["id"]
    assert replies[0]["sections"]["docs"][0]["entity_id"] == document["entity_id"]
    artifact = await db.get(Artifact, uuid.UUID(artifact_id))
    assert artifact is not None and artifact.retained
    content = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=alice_headers
    )
    assert content.status_code == 200 and content.content == b"%PDF-1.4 rules"
    graph = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": replies[0]["entity_id"], "depth": 1},
        headers=alice_headers,
    )
    assert document["entity_id"] in {e["id"] for e in graph.json()["data"]["entities"]}
    assert str(note.entity_id) not in {e["id"] for e in graph.json()["data"]["entities"]}
    nested = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": replies[0]["entity_id"], "depth": 2},
        headers=alice_headers,
    )
    assert nested.status_code == 200
    assert str(note.entity_id) in {e["id"] for e in nested.json()["data"]["entities"]}


async def test_concurrent_get_creates_a_missing_hierarchy_once(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    await db.execute(delete(GraphEntity).where(GraphEntity.project_id == uuid.UUID(project_id)))
    await db.commit()
    replies = await asyncio.gather(*[_get(client, alice_headers, project_id) for _ in range(6)])
    assert len({reply["entity_id"] for reply in replies}) == 1
    nodes, edges = await _graph(db, project_id)
    assert len(nodes) == 6 and len(edges) == 5


def _run_migration(connection: Connection) -> None:
    paths = list(
        (Path(__file__).parents[1] / "migrations" / "versions").glob("*solusdev_242_solus_graph.py")
    )
    assert len(paths) == 1, "The graph data migration must exist"
    spec = importlib.util.spec_from_file_location("solus_graph_migration", paths[0])
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "a3f242b9c610"
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


async def test_data_migration_backfills_idempotently_without_rewriting_legacy_content(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    note, document, artifact_id = await _legacy_entries(client, alice_headers, db, project_id)
    connection = await db.connection()
    await connection.run_sync(_run_migration)
    await db.commit()
    await db.refresh(note)
    assert note.entity_id is not None
    first_nodes, first_edges = await _graph(db, project_id)
    assert len(first_nodes) == 8 and len(first_edges) == 8
    connection = await db.connection()
    await connection.run_sync(_run_migration)
    await db.commit()
    second_nodes, second_edges = await _graph(db, project_id)
    assert {n.id for n in first_nodes} == {n.id for n in second_nodes}
    assert {e.id for e in first_edges} == {e.id for e in second_edges}
    assert note.text == "Legacy failure\nDetails remain intact"
    assert uuid.UUID(document["entity_id"]) in {n.id for n in second_nodes}
    content = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=alice_headers
    )
    assert content.status_code == 200 and content.content == b"%PDF-1.4 rules"


async def test_section_limit_is_serialized_for_concurrent_writes(
    client: AsyncClient, alice_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("solus_api.services.solus_config.MAX_ENTRIES_PER_SECTION", 1)
    project_id, _ = await _project(client, alice_headers)
    responses = await asyncio.gather(
        *[
            _post(client, alice_headers, project_id, "docs", {"kind": "text", "text": "One slot"})
            for _ in range(4)
        ]
    )
    assert sorted(r.status_code for r in responses) == [201, 422, 422, 422]
    data = await _get(client, alice_headers, project_id)
    assert len(data["sections"]["docs"]) == 1


async def test_entry_mutations_enforce_viewer_and_foreign_project_boundaries(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    alice_project, team_id = await _project(client, alice_headers)
    bob_project, _ = await _project(client, bob_headers)
    entry = (
        await _post(
            client,
            alice_headers,
            alice_project,
            "errors",
            {
                "kind": "text",
                "text": "Private failure details",
            },
        )
    ).json()["data"]
    for project_id, headers, status in [
        (alice_project, bob_headers, 404),
        (bob_project, bob_headers, 404),
    ]:
        url = f"/api/v1/projects/{project_id}/solus/entries/{entry['id']}"
        assert (
            await client.patch(url, json={"text": "overwrite"}, headers=headers)
        ).status_code == status
        assert (await client.delete(url, headers=headers)).status_code == status
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    url = f"/api/v1/projects/{alice_project}/solus/entries/{entry['id']}"
    assert (
        await client.patch(url, json={"text": "overwrite"}, headers=bob_headers)
    ).status_code == 403
    assert (await client.delete(url, headers=bob_headers)).status_code == 403
    current = (await _get(client, alice_headers, alice_project))["sections"]["errors"][0]
    assert (
        current["text"] == "Private failure details" and current["entity_id"] == entry["entity_id"]
    )


async def test_malformed_foreign_entry_reference_cannot_delete_other_projects_graph(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    alice_project, _ = await _project(client, alice_headers)
    bob_project, _ = await _project(client, bob_headers)
    alice_entry = (
        await _post(
            client, alice_headers, alice_project, "errors", {"kind": "text", "text": "Alice"}
        )
    ).json()["data"]
    bob_entry = (
        await _post(client, bob_headers, bob_project, "errors", {"kind": "text", "text": "Bob"})
    ).json()["data"]
    row = await db.get(SolusEntry, uuid.UUID(bob_entry["id"]))
    assert row is not None
    row.entity_id = uuid.UUID(alice_entry["entity_id"])
    await db.commit()
    response = await client.delete(
        f"/api/v1/projects/{bob_project}/solus/entries/{bob_entry['id']}", headers=bob_headers
    )
    assert response.status_code == 404
    nodes, edges = await _graph(db, alice_project)
    assert len(nodes) == 7 and len(edges) == 6
    assert uuid.UUID(alice_entry["entity_id"]) in {n.id for n in nodes}
    await db.refresh(row)
    assert row.deleted_at is None


async def test_migration_repairs_missing_root_but_skips_deleted_projects(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    live_project, _ = await _project(client, alice_headers)
    deleted_project, _ = await _project(client, bob_headers)
    for project_id in (live_project, deleted_project):
        await db.execute(delete(GraphEntity).where(GraphEntity.project_id == uuid.UUID(project_id)))
    deleted = await db.get(Project, uuid.UUID(deleted_project))
    assert deleted is not None
    deleted.deleted_at = utcnow()
    await db.commit()
    connection = await db.connection()
    await connection.run_sync(_run_migration)
    await db.commit()
    live_nodes, live_edges = await _graph(db, live_project)
    assert len(live_nodes) == 6 and len(live_edges) == 5
    assert await _graph(db, deleted_project) == ([], [])


async def test_maximum_text_and_rejected_edit_leave_the_original_identity(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    created = await _post(
        client, alice_headers, project_id, "details", {"kind": "text", "text": "x" * 4000}
    )
    assert created.status_code == 201
    entry = created.json()["data"]
    for text in (" ", "x" * 4001):
        response = await client.patch(
            f"/api/v1/projects/{project_id}/solus/entries/{entry['id']}",
            json={"text": text},
            headers=alice_headers,
        )
        assert response.status_code == 422
    nodes, _ = await _graph(db, project_id)
    assert len(nodes) == 7
    current = (await _get(client, alice_headers, project_id))["sections"]["details"][0]
    assert current["entity_id"] == entry["entity_id"] and current["text"] == "x" * 4000
