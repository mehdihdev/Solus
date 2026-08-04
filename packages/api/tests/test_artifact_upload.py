"""Integration tests for POST /artifacts (upload) — schema-valid `ArtifactRef`,
auth/authz, cross-tenant isolation, size caps, field validation, rate limiting,
and upload-time log hygiene (docs/api/artifacts.md §2/§4.4/§4.5)."""

import io
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from conftest import add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.models import Artifact, ProjectMembership
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    return project_id


def _files(data: bytes = b"hello artifact", filename: str = "export.zip") -> dict[str, Any]:
    return {"file": (filename, io.BytesIO(data), "application/octet-stream")}


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    data: bytes = b"hello artifact",
    media_type: str = "application/zip",
    filename: str = "export.zip",
    source_tool: str | None = None,
    call_id: str | None = None,
) -> Any:
    form: dict[str, Any] = {"media_type": media_type}
    if source_tool is not None:
        form["source_tool"] = source_tool
    if call_id is not None:
        form["call_id"] = call_id
    return await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data=form,
        files=_files(data, filename),
        headers=headers,
    )


async def test_upload_returns_schema_valid_artifact_ref(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await _upload(
        client, alice_headers, project_id, source_tool="kicad.export_project", call_id="call-1"
    )
    assert resp.status_code == 201, resp.text
    ref = resp.json()["data"]
    assert set(ref.keys()) == {
        "artifact_id",
        "uri",
        "media_type",
        "storage",
        "size_bytes",
        "summary",
    }
    assert ref["media_type"] == "application/zip"
    assert ref["storage"] == "local"
    assert ref["size_bytes"] == len(b"hello artifact")
    assert ref["summary"] is None
    assert ref["uri"] == f"/api/v1/projects/{project_id}/artifacts/{ref['artifact_id']}/content"


async def test_upload_unauthenticated_is_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/artifacts",
        data={"media_type": "application/zip"},
        files=_files(),
    )
    assert resp.status_code == 401


async def test_upload_non_member_project_is_404(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    await me(client, bob_headers)
    resp = await _upload(client, bob_headers, project_id)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_cross_team_cannot_upload_or_fetch(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """Highest-severity isolation case: team B (Bob) can neither upload into nor
    fetch anything from team A's (Alice's) project."""
    project_id = await _project(client, alice_headers)
    uploaded = await _upload(client, alice_headers, project_id)
    artifact_id = uploaded.json()["data"]["artifact_id"]
    await me(client, bob_headers)

    assert (await _upload(client, bob_headers, project_id)).status_code == 404
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/artifacts/{artifact_id}", headers=bob_headers
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=bob_headers
        )
    ).status_code == 404


async def test_viewer_role_forbidden_from_uploading(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(
        client, alice_headers, bob_headers, {"email": "bob@example.com"}, team["id"], role="viewer"
    )
    resp = await _upload(client, bob_headers, project["id"])
    assert resp.status_code == 403


async def test_over_cap_upload_rejected_and_nothing_stored(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    settings: Settings,
    db: AsyncSession,
) -> None:
    project_id = await _project(client, alice_headers)
    oversized = b"x" * (settings.artifact_max_bytes + 1)
    resp = await _upload(client, alice_headers, project_id, data=oversized)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"

    count = await db.scalar(select(func.count()).select_from(Artifact))
    assert count == 0

    store = app.state.artifact_store
    assert list(store.root.iterdir()) == []


async def test_declared_content_length_lie_cannot_overshoot_cap(
    client: AsyncClient, alice_headers: dict[str, str], settings: Settings
) -> None:
    """A client that under-reports Content-Length cannot sneak an over-cap
    upload past the pre-check — the streamed read still enforces the cap."""
    project_id = await _project(client, alice_headers)
    oversized = b"x" * (settings.artifact_max_bytes + 1)
    boundary = "testboundary123solus"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="media_type"\r\n\r\n'
            "application/zip\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="x.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + oversized
        + f"\r\n--{boundary}--\r\n".encode()
    )

    headers = {
        **alice_headers,
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-length": "5",  # lies: the real body is far larger than the cap
    }
    request = client.build_request(
        "POST", f"/api/v1/projects/{project_id}/artifacts", content=body, headers=headers
    )
    resp = await client.send(request)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_invalid_media_type_rejected(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await _upload(client, alice_headers, project_id, media_type="not-a-mime-type")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_missing_file_rejected(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data={"media_type": "application/zip"},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_unknown_form_field_rejected(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data={"media_type": "application/zip", "unexpected": "nope"},
        files=_files(),
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_client_filename_never_used_as_storage_path(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await _upload(client, alice_headers, project_id, filename="../../etc/passwd")
    assert resp.status_code == 201, resp.text
    artifact_id = resp.json()["data"]["artifact_id"]
    store = app.state.artifact_store
    stored_names = {p.name for p in store.root.iterdir()}
    assert stored_names == {artifact_id}  # storage key is the server UUID, never the filename


async def test_upload_rate_limit_exceeded_returns_429(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    project_id = await _project(client, alice_headers)
    app.state.settings.artifact_uploads_per_minute_per_user = 1
    first = await _upload(client, alice_headers, project_id)
    assert first.status_code == 201
    second = await _upload(client, alice_headers, project_id)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in second.headers


async def test_upload_never_logs_bytes_or_paths(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_id = await _project(client, alice_headers)
    sentinel = b"TOP-SECRET-CAD-BYTES-0xFEED"
    with caplog.at_level(logging.DEBUG):
        resp = await _upload(client, alice_headers, project_id, data=sentinel)
    assert resp.status_code == 201, resp.text
    artifact_id = resp.json()["data"]["artifact_id"]
    store = app.state.artifact_store
    storage_path = str(Path(store.root) / artifact_id)

    assert sentinel.decode() not in caplog.text
    assert storage_path not in caplog.text


# --------------------------------------- Phase 4 H1/M3: content GET role gate


async def test_viewer_role_forbidden_from_content_get(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """The content route is now role-gated to member+ (Phase 4 H1/M3) — a
    viewer must be refused, never allowed to read (and, pre-fix, silently
    destroy) a design export."""
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(
        client,
        alice_headers,
        bob_headers,
        {"email": "bob@example.com"},
        team["id"],
        role="viewer",
    )
    uploaded = await _upload(client, alice_headers, project["id"])
    artifact_id = uploaded.json()["data"]["artifact_id"]

    resp = await client.get(
        f"/api/v1/projects/{project['id']}/artifacts/{artifact_id}/content", headers=bob_headers
    )
    assert resp.status_code == 403

    # Never destroyed by the refused attempt.
    still_there = await client.get(
        f"/api/v1/projects/{project['id']}/artifacts/{artifact_id}/content",
        headers=alice_headers,
    )
    assert still_there.status_code == 200


async def test_share_only_user_forbidden_from_content_get(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A share-only user (ADR-025 direct `ProjectMembership`, no team role —
    `ProjectContext.membership is None`) is also refused: `require_role`
    treats a `None` membership the same as an under-ranked one."""
    project_id = await _project(client, alice_headers)
    uploaded = await _upload(client, alice_headers, project_id)
    artifact_id = uploaded.json()["data"]["artifact_id"]
    bob = await me(client, bob_headers)

    db.add(ProjectMembership(project_id=uuid.UUID(project_id), user_id=uuid.UUID(bob["id"])))
    await db.commit()

    resp = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=bob_headers
    )
    assert resp.status_code == 403

    still_there = await client.get(
        f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content", headers=alice_headers
    )
    assert still_there.status_code == 200


# ------------------------------------------------- Phase 4 M1: chunked bodies


async def test_upload_without_content_length_is_rejected_before_parsing(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """A chunked (no `Content-Length`) body must be rejected UP FRONT, before
    `request.form()` ever spools it to disk/memory with no cap of its own."""
    project_id = await _project(client, alice_headers)
    boundary = "testboundary123solus"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="media_type"\r\n\r\n'
        "application/zip\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="x.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
        "hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    async def _chunks() -> AsyncIterator[bytes]:
        yield body

    headers = {**alice_headers, "content-type": f"multipart/form-data; boundary={boundary}"}
    request = client.build_request(
        "POST", f"/api/v1/projects/{project_id}/artifacts", content=_chunks(), headers=headers
    )
    assert "content-length" not in request.headers
    resp = await client.send(request)
    assert resp.status_code == 411
    assert resp.json()["error"]["code"] == "length_required"
