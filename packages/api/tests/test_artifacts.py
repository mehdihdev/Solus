"""The `artifacts` table + the pure access check (SOLUS-W0-04 addendum).

Scope defaults to PROJECT silently (most artifacts are machine byproducts); a user
can override an artifact to PRIVATE. The access rule is enforced in code, never via a
per-artifact prompt.
"""

import uuid

from solus_api.models import (
    Artifact,
    ArtifactScope,
    ArtifactStorage,
    Membership,
    Project,
    Role,
    Team,
    User,
    artifact_is_accessible,
)
from solus_api.schemas import ArtifactRead
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def test_artifact_round_trips_with_the_silent_project_default_scope(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user = User(supabase_user_id="sub-art", email="art@example.com")
    team = Team(name="Art")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="A", created_by=user.id)
    db.add(project)
    await db.flush()
    artifact = Artifact(
        project_id=project.id,
        uri="s3://bucket/frame.png",
        media_type="image/png",
        storage_location=ArtifactStorage.S3,
        created_by=user.id,
        source_tool="get_frame",
        size_bytes=2048,
    )
    db.add(artifact)
    await db.commit()
    artifact_id = artifact.id

    # Fresh session = a true DB round-trip (empty identity map).
    async with async_sessionmaker(engine, expire_on_commit=False)() as read:
        got = await read.get(Artifact, artifact_id)
        assert got is not None
        assert got.scope is ArtifactScope.PROJECT  # inherited silently, no prompt
        assert got.storage_location is ArtifactStorage.S3
        assert got.deleted_at is None  # soft-delete column present
        view = ArtifactRead.model_validate(got)
        assert view.uri == "s3://bucket/frame.png"
        assert view.source_tool == "get_frame"
        assert view.size_bytes == 2048


def test_project_scoped_artifact_follows_project_access() -> None:
    creator, other = uuid.uuid4(), uuid.uuid4()
    assert artifact_is_accessible(
        scope=ArtifactScope.PROJECT,
        created_by=creator,
        requester_id=other,
        requester_has_project_access=True,
    )
    assert not artifact_is_accessible(
        scope=ArtifactScope.PROJECT,
        created_by=creator,
        requester_id=other,
        requester_has_project_access=False,
    )


def test_private_artifact_is_creator_only_even_with_project_access() -> None:
    creator, other = uuid.uuid4(), uuid.uuid4()
    assert artifact_is_accessible(
        scope=ArtifactScope.PRIVATE,
        created_by=creator,
        requester_id=creator,
        requester_has_project_access=False,
    )
    # A non-creator cannot read a PRIVATE artifact even WITH project access:
    assert not artifact_is_accessible(
        scope=ArtifactScope.PRIVATE,
        created_by=creator,
        requester_id=other,
        requester_has_project_access=True,
    )
    # An orphaned private artifact (creator deleted → created_by NULL) is inaccessible:
    assert not artifact_is_accessible(
        scope=ArtifactScope.PRIVATE,
        created_by=None,
        requester_id=other,
        requester_has_project_access=True,
    )
