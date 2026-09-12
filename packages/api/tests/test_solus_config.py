"""Project-level `.solus` (SOLUSDEV-240 / WORKSPACE W1, docs/api/solus.md).

Every project gets a `.solus` graph node at creation; five sections hold typed
text, SOL-filed text, and imported artifacts (which become `document` graph nodes
hanging off the `.solus` node so Impact can reach them). Retained artifacts are
exempt from the TTL sweep. The `add_solus_entry` tool lets SOL file entries.
"""

import io
import uuid
from typing import Any

from conftest import add_member, create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import Artifact, Domain, GraphEdge, GraphEntity, utcnow
from solus_api.services.artifacts import _is_expired, sweep_expired_artifacts
from solus_api.storage import LocalArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SECTIONS = ("hardware", "details", "errors", "docs", "code")


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


async def _upload(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data={"media_type": "application/pdf"},
        files={"file": ("rules.pdf", io.BytesIO(b"%PDF-1.4 rules"), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    artifact_id: str = resp.json()["data"]["artifact_id"]
    return artifact_id


async def _get(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/projects/{project_id}/solus", headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _post(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    section: str,
    body: dict[str, Any],
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project_id}/solus/{section}/entries", json=body, headers=headers
    )


async def _solus_node(db: AsyncSession, project_id: str) -> GraphEntity | None:
    node: GraphEntity | None = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project_id),
            GraphEntity.kind == "solus_config",
            GraphEntity.deleted_at.is_(None),
        )
    )
    return node


# --------------------------------------------------------------------- creation


async def test_project_creation_creates_the_solus_node(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    node = await _solus_node(db, project_id)
    assert node is not None
    assert node.name == ".solus"
    assert node.domain == Domain.PROJECT
    assert node.origin == "manual"


async def test_get_returns_five_empty_sections_and_the_node_id(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    data = await _get(client, alice_headers, project_id)
    node = await _solus_node(db, project_id)
    assert node is not None
    assert data["entity_id"] == str(node.id)
    assert set(data["sections"].keys()) == set(SECTIONS)
    assert all(data["sections"][s] == [] for s in SECTIONS)


async def test_get_self_heals_a_project_without_a_node(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    node = await _solus_node(db, project_id)
    assert node is not None
    node.deleted_at = utcnow()
    await db.commit()
    data = await _get(client, alice_headers, project_id)
    assert data["entity_id"] != str(node.id)
    assert await _solus_node(db, project_id) is not None


# ----------------------------------------------------------------------- entries


async def test_type_it_persists_a_text_entry(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    resp = await _post(
        client, alice_headers, project_id, "details", {"kind": "text", "text": "Spec: 48 V bus"}
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()["data"]
    assert entry["kind"] == "text"
    assert entry["author"] == "user"
    assert entry["text"] == "Spec: 48 V bus"
    data = await _get(client, alice_headers, project_id)
    assert [e["id"] for e in data["sections"]["details"]] == [entry["id"]]


async def test_import_files_an_artifact_as_a_document_node_under_solus(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    artifact_id = await _upload(client, alice_headers, project_id)
    resp = await _post(
        client,
        alice_headers,
        project_id,
        "details",
        {"kind": "artifact", "artifact_id": artifact_id, "name": "FSAE Rules 2027.pdf"},
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()["data"]
    assert entry["kind"] == "artifact"
    assert entry["artifact_id"] == artifact_id
    assert entry["name"] == "FSAE Rules 2027.pdf"
    assert entry["media_type"] == "application/pdf"

    document = await db.get(GraphEntity, uuid.UUID(entry["entity_id"]))
    assert document is not None
    assert document.kind == "document"
    assert document.domain == Domain.PROJECT
    assert document.attrs["artifact_id"] == artifact_id
    node = await _solus_node(db, project_id)
    assert node is not None
    edge = await db.scalar(
        select(GraphEdge).where(GraphEdge.src_id == node.id, GraphEdge.dst_id == document.id)
    )
    assert edge is not None
    assert edge.relation_type == "references"
    artifact = await db.get(Artifact, uuid.UUID(artifact_id))
    assert artifact is not None
    assert artifact.retained is True

    # Impact/focus reach it through the ONE traversal.
    graph = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": str(node.id), "depth": 1},
        headers=alice_headers,
    )
    assert graph.status_code == 200, graph.text
    ids = {e["id"] for e in graph.json()["data"]["entities"]}
    assert str(document.id) in ids


async def test_filing_a_foreign_or_unknown_artifact_is_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    alice_project, _ = await _project(client, alice_headers)
    bob_project, _ = await _project(client, bob_headers)
    alice_artifact = await _upload(client, alice_headers, alice_project)
    resp = await _post(
        client,
        bob_headers,
        bob_project,
        "docs",
        {"kind": "artifact", "artifact_id": alice_artifact, "name": "x.pdf"},
    )
    assert resp.status_code == 404
    resp = await _post(
        client,
        alice_headers,
        alice_project,
        "docs",
        {"kind": "artifact", "artifact_id": str(uuid.uuid4()), "name": "x.pdf"},
    )
    assert resp.status_code == 404


async def test_validation_rejects_bad_section_unknown_fields_and_long_text(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    assert (
        await _post(client, alice_headers, project_id, "secrets", {"kind": "text", "text": "x"})
    ).status_code == 404
    assert (
        await _post(
            client, alice_headers, project_id, "docs", {"kind": "text", "text": "x", "evil": 1}
        )
    ).status_code == 422
    assert (
        await _post(client, alice_headers, project_id, "docs", {"kind": "text", "text": "x" * 4001})
    ).status_code == 422
    assert (
        await _post(client, alice_headers, project_id, "docs", {"kind": "text", "text": "   "})
    ).status_code == 422


async def test_edit_and_delete_entries(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    text = (
        await _post(client, alice_headers, project_id, "errors", {"kind": "text", "text": "old"})
    ).json()["data"]
    patched = await client.patch(
        f"/api/v1/projects/{project_id}/solus/entries/{text['id']}",
        json={"text": "new"},
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["text"] == "new"

    artifact_id = await _upload(client, alice_headers, project_id)
    art = (
        await _post(
            client,
            alice_headers,
            project_id,
            "docs",
            {"kind": "artifact", "artifact_id": artifact_id, "name": "a.pdf"},
        )
    ).json()["data"]
    assert (
        await client.patch(
            f"/api/v1/projects/{project_id}/solus/entries/{art['id']}",
            json={"text": "nope"},
            headers=alice_headers,
        )
    ).status_code == 409

    deleted = await client.delete(
        f"/api/v1/projects/{project_id}/solus/entries/{art['id']}", headers=alice_headers
    )
    assert deleted.status_code == 204
    data = await _get(client, alice_headers, project_id)
    assert data["sections"]["docs"] == []
    document = await db.get(GraphEntity, uuid.UUID(art["entity_id"]))
    assert document is not None and document.deleted_at is not None
    artifact = await db.get(Artifact, uuid.UUID(artifact_id))
    assert artifact is not None and artifact.deleted_at is not None
    assert (
        await client.delete(
            f"/api/v1/projects/{project_id}/solus/entries/{art['id']}", headers=alice_headers
        )
    ).status_code == 404


# ------------------------------------------------------------------ authz / tenancy


async def test_requires_auth(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id, _ = await _project(client, alice_headers)
    assert (await client.get(f"/api/v1/projects/{project_id}/solus")).status_code == 401


async def test_other_team_cannot_read_or_write(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    await me(client, bob_headers)
    assert (
        await client.get(f"/api/v1/projects/{project_id}/solus", headers=bob_headers)
    ).status_code == 404
    assert (
        await _post(client, bob_headers, project_id, "docs", {"kind": "text", "text": "x"})
    ).status_code == 404


async def test_viewer_reads_but_cannot_write(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    assert (
        await client.get(f"/api/v1/projects/{project_id}/solus", headers=bob_headers)
    ).status_code == 200
    assert (
        await _post(client, bob_headers, project_id, "docs", {"kind": "text", "text": "x"})
    ).status_code == 403


# ---------------------------------------------------------------------- retention


async def test_retained_artifacts_survive_the_sweep(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, tmp_path: Any
) -> None:
    project_id, _ = await _project(client, alice_headers)
    kept = await _upload(client, alice_headers, project_id)
    swept = await _upload(client, alice_headers, project_id)
    await _post(
        client,
        alice_headers,
        project_id,
        "docs",
        {"kind": "artifact", "artifact_id": kept, "name": "keep.pdf"},
    )
    store = LocalArtifactStore(tmp_path)
    removed = await sweep_expired_artifacts(db, store, ttl_seconds=0)
    assert removed == 1
    kept_row = await db.get(Artifact, uuid.UUID(kept))
    swept_row = await db.get(Artifact, uuid.UUID(swept))
    assert kept_row is not None and kept_row.deleted_at is None
    assert swept_row is not None and swept_row.deleted_at is not None
    assert _is_expired(kept_row, ttl_seconds=0) is False


async def test_selected_revision_does_not_override_shared_widget_defaults(db: AsyncSession) -> None:
    import json
    from pathlib import Path

    from solus_api.graph.read_scope import GraphReadScope, bind_scope
    from solus_api.models import Project, Source, SourceType, Team
    from solus_api.widgets.solus_config import SOLUS_CONFIG_KIND, read_bundle_config
    from solus_contracts.extension_manifest import parse_extension_manifest

    manifest_data = json.loads(
        (
            Path(__file__).parents[2]
            / "shared-types"
            / "fixtures"
            / "extension-manifest"
            / "manifest-v2-first-party.json"
        ).read_text()
    )
    manifest_data["settings"] = {
        "fields": [{"key": "limit", "type": "number", "label": "Limit", "default": 1}]
    }
    manifest = parse_extension_manifest(manifest_data)
    team = Team(name="T")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="P")
    db.add(project)
    await db.flush()
    base = Source(project_id=project.id, team_id=team.id, type=SourceType.GITHUB, name="base")
    db.add(base)
    await db.flush()
    snapshot = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.GITHUB,
        name="snapshot",
        revision_base_source_id=base.id,
    )
    db.add(snapshot)
    await db.flush()
    for source, value in ((base, 2), (snapshot, 99)):
        db.add(
            GraphEntity(
                project_id=project.id,
                source_id=source.id,
                kind=SOLUS_CONFIG_KIND,
                domain=Domain.CODE,
                origin="connector",
                name="project.toml",
                attrs={"ext": {"fixture-bundle": {"limit": value}}},
                updated_at=utcnow(),
            )
        )
        await db.flush()
    with bind_scope(GraphReadScope(project.id, ((base.id, snapshot.id),))):
        assert await read_bundle_config(db, project.id, "fixture-bundle", manifest) == {"limit": 2}
