"""ORM model defaults and constraints."""

import uuid

import pytest
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Job,
    JobKind,
    JobStatus,
    Membership,
    Project,
    Role,
    SolMode,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    SyncTrigger,
    Team,
    User,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def test_user_defaults(db: AsyncSession) -> None:
    user = User(supabase_user_id="auth-sub-1", email="u@example.com")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.sol_mode == SolMode.GUIDE
    assert user.data_collection_consent is False
    assert user.created_at is not None


async def test_membership_links_user_and_team(db: AsyncSession) -> None:
    user = User(supabase_user_id="auth-sub-2", email="m@example.com")
    team = Team(name="T")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(user_id=user.id, team_id=team.id, role=Role.OWNER))
    await db.commit()

    row = await db.scalar(select(Membership).where(Membership.user_id == user.id))
    assert row is not None
    assert row.role == Role.OWNER


async def test_job_defaults(db: AsyncSession) -> None:
    user = User(supabase_user_id="auth-sub-3", email="j@example.com")
    team = Team(name="T2")
    db.add_all([user, team])
    await db.flush()
    from solus_api.models import Project

    project = Project(team_id=team.id, name="P")
    db.add(project)
    await db.flush()
    job = Job(project_id=project.id, team_id=team.id, kind=JobKind.SYNC)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    assert job.status == JobStatus.QUEUED
    assert job.progress == 0
    assert job.finished_at is None


async def _project(db: AsyncSession, suffix: str) -> Project:
    team = Team(name=f"T-{suffix}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"P-{suffix}")
    db.add(project)
    await db.flush()
    return project


async def test_source_defaults(db: AsyncSession) -> None:
    project = await _project(db, "src")
    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name="octocat/strider-fw",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    assert source.status == SourceStatus.PENDING
    assert source.config == {}
    assert source.cursor == {}
    assert source.secret_ref is None
    assert source.last_synced_at is None


async def test_entity_unique_per_source_key(db: AsyncSession) -> None:
    project = await _project(db, "ent")
    source = Source(
        project_id=project.id, team_id=project.team_id, type=SourceType.GITHUB, name="r"
    )
    db.add(source)
    await db.flush()
    db.add(
        GraphEntity(
            project_id=project.id,
            source_id=source.id,
            external_ref="src/main.py",
            kind="code_file",
            domain=Domain.CODE,
            name="main.py",
        )
    )
    await db.commit()

    db.add(
        GraphEntity(
            project_id=project.id,
            source_id=source.id,
            external_ref="src/main.py",
            kind="code_file",
            domain=Domain.CODE,
            name="main.py",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_entity_defaults_origin_and_version(db: AsyncSession) -> None:
    project = await _project(db, "ent2")
    entity = GraphEntity(
        project_id=project.id,
        external_ref="manual:motor-1",
        kind="motor",
        domain=Domain.MECHANICAL,
        name="Drive motor",
    )
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    assert entity.origin == "connector"
    assert entity.version == 1
    assert entity.attrs == {}


async def test_relation_links_entities(db: AsyncSession) -> None:
    project = await _project(db, "rel")
    a = GraphEntity(
        project_id=project.id,
        external_ref="pkg",
        kind="code_module",
        domain=Domain.CODE,
        name="pkg",
    )
    b = GraphEntity(
        project_id=project.id,
        external_ref="a.py",
        kind="code_file",
        domain=Domain.CODE,
        name="a.py",
    )
    db.add_all([a, b])
    await db.flush()
    relation = GraphEdge(
        project_id=project.id,
        src_id=a.id,
        dst_id=b.id,
        relation_type="contains",
        domain_pair="code<->code",
    )
    db.add(relation)
    await db.commit()
    await db.refresh(relation)
    assert relation.relation_type == "contains"
    assert relation.attrs == {}


async def test_sync_defaults(db: AsyncSession) -> None:
    project = await _project(db, "sync")
    source = Source(
        project_id=project.id, team_id=project.team_id, type=SourceType.GITHUB, name="r"
    )
    db.add(source)
    await db.flush()
    sync = Sync(source_id=source.id, project_id=project.id, trigger=SyncTrigger.MANUAL)
    db.add(sync)
    await db.commit()
    await db.refresh(sync)
    assert sync.status == JobStatus.QUEUED
    assert sync.entities_created == 0
    assert sync.entities_updated == 0
    assert sync.relations_created == 0
    assert sync.errors == []


async def test_oauth_state_persists(db: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    from solus_api.models import OAuthState

    project = await _project(db, "oauth")
    source = Source(
        project_id=project.id, team_id=project.team_id, type=SourceType.GITHUB, name="r"
    )
    db.add(source)
    await db.flush()
    state = OAuthState(
        state="rand-state",
        provider="github",
        source_id=source.id,
        user_id=uuid.uuid4(),
        redirect_uri="http://localhost:8000/cb",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(state)
    await db.commit()
    row = await db.get(OAuthState, "rand-state")
    assert row is not None
    assert row.source_id == source.id
