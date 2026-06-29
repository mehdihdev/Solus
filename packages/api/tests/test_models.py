"""ORM model defaults and constraints."""

import uuid

from solus_api.models import (
    Job,
    JobKind,
    JobStatus,
    Membership,
    Role,
    SolMode,
    Team,
    User,
)
from sqlalchemy import select
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
