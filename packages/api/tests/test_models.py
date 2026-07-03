"""ORM model defaults and constraints."""

import uuid

import pytest
from solus_api.models import (
    Entity,
    Job,
    JobKind,
    JobStatus,
    Membership,
    Project,
    Relation,
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
    user = User(auth_id="auth-sub-1", email="u@example.com")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.sol_mode == SolMode.GUIDE
    assert user.data_collection_consent is False
    assert user.created_at is not None


async def test_membership_links_user_and_team(db: AsyncSession) -> None:
    user = User(auth_id="auth-sub-2", email="m@example.com")
    team = Team(name="T", is_personal=False)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(user_id=user.id, team_id=team.id, role=Role.OWNER))
    await db.commit()

    row = await db.scalar(select(Membership).where(Membership.user_id == user.id))
    assert row is not None
    assert row.role == Role.OWNER


async def test_job_defaults(db: AsyncSession) -> None:
    user = User(auth_id="auth-sub-3", email="j@example.com")
    team = Team(name="T2", is_personal=False)
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
    team = Team(name=f"T-{suffix}", is_personal=False)
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
        Entity(
            project_id=project.id,
            source_id=source.id,
            source_key="src/main.py",
            type="code_file",
            domain="software",
            name="main.py",
        )
    )
    await db.commit()

    db.add(
        Entity(
            project_id=project.id,
            source_id=source.id,
            source_key="src/main.py",
            type="code_file",
            domain="software",
            name="main.py",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_entity_defaults_origin_and_version(db: AsyncSession) -> None:
    project = await _project(db, "ent2")
    entity = Entity(
        project_id=project.id,
        source_key="manual:motor-1",
        type="motor",
        domain="mechanical",
        name="Drive motor",
    )
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    assert entity.origin == "connector"
    assert entity.version == 1
    assert entity.properties == {}


async def test_relation_links_entities(db: AsyncSession) -> None:
    project = await _project(db, "rel")
    a = Entity(
        project_id=project.id, source_key="pkg", type="code_module", domain="software", name="pkg"
    )
    b = Entity(
        project_id=project.id, source_key="a.py", type="code_file", domain="software", name="a.py"
    )
    db.add_all([a, b])
    await db.flush()
    relation = Relation(
        project_id=project.id, from_entity_id=a.id, to_entity_id=b.id, type="contains"
    )
    db.add(relation)
    await db.commit()
    await db.refresh(relation)
    assert relation.type == "contains"
    assert relation.properties == {}


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
