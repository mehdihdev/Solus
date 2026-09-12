"""`fetch_artifact_bytes` (SOLUSDEV-252 P6) — the team/project-scoped, live-only,
size-capped byte read a server-side consumer (read_document) uses. Same 404
posture as every other artifact read: foreign, expired and unknown all collapse."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from solus_api.core.errors import APIError
from solus_api.models import Membership, Project, Role, Team, User, utcnow
from solus_api.services.artifacts import create_artifact, fetch_artifact_bytes
from solus_api.storage import LocalArtifactStore
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(db: AsyncSession, tag: str) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    team = Team(name=tag)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=tag, created_by=user.id)
    db.add(project)
    await db.flush()
    return project.id, user.id


async def test_fetch_returns_the_row_and_bytes_for_a_live_project_artifact(
    db: AsyncSession, tmp_path: Path
) -> None:
    store = LocalArtifactStore(str(tmp_path))
    project_id, user_id = await _project(db, "fetch-ok")
    created = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=user_id,
        data=b"%PDF-1.4 hello",
        media_type="application/pdf",
        source_tool="read_document",
        tool_call_id=None,
    )
    artifact, data = await fetch_artifact_bytes(
        db,
        store,
        project_id=project_id,
        artifact_id=created.id,
        requester_id=user_id,
        ttl_seconds=3600,
        max_bytes=1024,
    )
    assert artifact.id == created.id
    assert data == b"%PDF-1.4 hello"


async def test_a_foreign_project_and_an_expired_artifact_are_both_not_found(
    db: AsyncSession, tmp_path: Path
) -> None:
    store = LocalArtifactStore(str(tmp_path))
    project_id, user_id = await _project(db, "fetch-a")
    other_project, other_user = await _project(db, "fetch-b")
    created = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=user_id,
        data=b"%PDF-1.4",
        media_type="application/pdf",
        source_tool=None,
        tool_call_id=None,
    )
    with pytest.raises(APIError) as foreign:
        await fetch_artifact_bytes(
            db,
            store,
            project_id=other_project,
            artifact_id=created.id,
            requester_id=other_user,
            ttl_seconds=3600,
            max_bytes=1024,
        )
    assert foreign.value.status_code == 404

    created.created_at = utcnow() - timedelta(seconds=7200)
    await db.flush()
    with pytest.raises(APIError) as expired:
        await fetch_artifact_bytes(
            db,
            store,
            project_id=project_id,
            artifact_id=created.id,
            requester_id=user_id,
            ttl_seconds=3600,
            max_bytes=1024,
        )
    assert expired.value.status_code == 404


async def test_an_artifact_over_the_byte_cap_is_refused_before_it_is_read(
    db: AsyncSession, tmp_path: Path
) -> None:
    store = LocalArtifactStore(str(tmp_path))
    project_id, user_id = await _project(db, "fetch-big")
    created = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=user_id,
        data=b"%PDF-1.4" + b"x" * 100,
        media_type="application/pdf",
        source_tool=None,
        tool_call_id=None,
    )
    with pytest.raises(APIError) as too_big:
        await fetch_artifact_bytes(
            db,
            store,
            project_id=project_id,
            artifact_id=created.id,
            requester_id=user_id,
            ttl_seconds=3600,
            max_bytes=50,
        )
    assert too_big.value.status_code == 413
