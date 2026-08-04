"""Retention semantics — one-shot consumption (including the concurrent-race
guarantee), the TTL sweep, and post-expiry/post-consume 404s
(docs/api/artifacts.md §4.2/§4.3)."""

import asyncio
import io
import uuid
from datetime import timedelta
from typing import Any

from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import Artifact, utcnow
from solus_api.services.artifacts import sweep_expired_artifacts
from solus_api.storage import LocalArtifactStore
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    return project_id


async def _upload(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data={"media_type": "application/zip"},
        files={"file": ("export.zip", io.BytesIO(b"cad bytes"), "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def test_content_fetch_is_non_destructive_and_repeatable(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Phase 4 H1/M3 fix: a plain member GET of the content route must NEVER
    destroy the artifact — one-shot consumption is exclusive to
    `consume_tool_artifact` (the bridge acquirer's internal path), never the
    generic HTTP route. A member can read the same artifact repeatedly."""
    project_id = await _project(client, alice_headers)
    ref = await _upload(client, alice_headers, project_id)
    artifact_id = ref["artifact_id"]

    first = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=alice_headers
    )
    assert first.status_code == 200
    assert first.content == b"cad bytes"
    assert first.headers["content-type"] == "application/zip"

    second = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=alice_headers
    )
    assert second.status_code == 200  # still live: reads never consume
    assert second.content == b"cad bytes"

    metadata = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}", headers=alice_headers
    )
    assert metadata.status_code == 200


async def test_concurrent_reads_both_succeed(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Companion to the non-destructive-read test: concurrent member reads of
    the SAME artifact must both succeed (no row-lock contention/soft-delete
    race exists anymore on this route — that guarantee lives exclusively in
    `consume_tool_artifact`, covered by `test_mcp_acquire_artifact.py`'s
    `test_replayed_artifact_is_consumed_exactly_once` /
    `test_consume_tool_artifact_is_one_shot`)."""
    project_id = await _project(client, alice_headers)
    ref = await _upload(client, alice_headers, project_id)
    artifact_id = ref["artifact_id"]
    url = f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content"

    results = await asyncio.gather(
        client.get(url, headers=alice_headers),
        client.get(url, headers=alice_headers),
    )
    assert [r.status_code for r in results] == [200, 200]
    assert all(r.content == b"cad bytes" for r in results)


async def test_expired_artifact_is_404_on_metadata_and_content(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: FastAPI
) -> None:
    project_id = await _project(client, alice_headers)
    ref = await _upload(client, alice_headers, project_id)
    artifact_id = uuid.UUID(ref["artifact_id"])

    # Force expiry without waiting out the real TTL: push created_at into the past.
    app.state.settings.artifact_ttl_seconds = 1
    artifact = await db.get(Artifact, artifact_id)
    assert artifact is not None
    artifact.created_at = utcnow() - timedelta(seconds=10)
    await db.commit()

    metadata = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}", headers=alice_headers
    )
    assert metadata.status_code == 404

    content = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=alice_headers
    )
    assert content.status_code == 404


async def test_sweep_removes_expired_bytes_and_marks_row_deleted(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: FastAPI
) -> None:
    project_id = await _project(client, alice_headers)
    ref = await _upload(client, alice_headers, project_id)
    artifact_id = uuid.UUID(ref["artifact_id"])

    artifact = await db.get(Artifact, artifact_id)
    assert artifact is not None
    artifact.created_at = utcnow() - timedelta(hours=2)
    await db.commit()

    store: LocalArtifactStore = app.state.artifact_store
    assert (store.root / str(artifact_id)).exists()

    processed = await sweep_expired_artifacts(db, store, ttl_seconds=3600)
    assert processed == 1
    assert not (store.root / str(artifact_id)).exists()

    refreshed = await db.get(Artifact, artifact_id)
    assert refreshed is not None
    assert refreshed.deleted_at is not None


async def test_sweep_ignores_live_artifacts(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: FastAPI
) -> None:
    project_id = await _project(client, alice_headers)
    await _upload(client, alice_headers, project_id)
    store: LocalArtifactStore = app.state.artifact_store
    processed = await sweep_expired_artifacts(db, store, ttl_seconds=3600)
    assert processed == 0
