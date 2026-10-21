"""Seed helpers for team-installation tests (SOLUSDEV-216 S216-T3; reused by T4-T7).

Everything is written through the caller's session and flushed, never committed."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from typing import Any

from solus_api.connectors.github_app import installation_secret_ref
from solus_api.models import (
    Membership,
    PlanType,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Subscription,
    SubscriptionStatus,
    Team,
    TeamInstallation,
    TeamKind,
    User,
    default_limits,
)
from sqlalchemy.ext.asyncio import AsyncSession

_external_ids = itertools.count(7_000_000)


@dataclass
class SeededTeam:
    team: Team
    users: dict[Role, User]
    project: Project
    installation: TeamInstallation | None = None
    sources: list[Source] = field(default_factory=list)


async def seed_user(db: AsyncSession, name: str = "u", *, consent: bool = False) -> User:
    uid = uuid.uuid4()
    user = User(
        id=uid,
        supabase_user_id=f"sb-{uid}",
        email=f"{name}-{uid}@example.com",
        data_collection_consent=consent,
    )
    db.add(user)
    await db.flush()
    db.add(
        Subscription(
            user_id=uid,
            plan=PlanType.BASIC,
            status=SubscriptionStatus.TRIALING,
            limits=default_limits(PlanType.BASIC),
        )
    )
    await db.flush()
    return user


async def seed_team(
    db: AsyncSession, *, kind: TeamKind = TeamKind.COLLABORATIVE, name: str = "Org Team"
) -> SeededTeam:
    """A team with an owner and a member, plus one project."""
    team = Team(name=name, kind=kind)
    db.add(team)
    await db.flush()
    users: dict[Role, User] = {}
    for role in (Role.OWNER, Role.MEMBER):
        user = await seed_user(db, role.value)
        users[role] = user
        db.add(Membership(team_id=team.id, user_id=user.id, role=role))
    project = Project(team_id=team.id, name="P")
    db.add(project)
    await db.flush()
    return SeededTeam(team=team, users=users, project=project)


async def seed_installation(
    db: AsyncSession,
    seeded: SeededTeam,
    *,
    linked_by: User | None = None,
    external_id: int | None = None,
    login: str = "acme",
    **overrides: Any,
) -> TeamInstallation:
    inst = TeamInstallation(
        team_id=seeded.team.id,
        external_installation_id=external_id or next(_external_ids),
        account_login=login,
        account_external_id=next(_external_ids),
        account_type="Organization",
        repository_selection="all",
        linked_by=(linked_by or seeded.users[Role.OWNER]).id,
        **overrides,
    )
    db.add(inst)
    await db.flush()
    seeded.installation = inst
    return inst


async def seed_installation_source(
    db: AsyncSession,
    seeded: SeededTeam,
    *,
    repo: str = "acme/robot",
    status: SourceStatus = SourceStatus.CONNECTED,
    last_error: dict[str, str] | None = None,
    created_by: User | None = None,
) -> Source:
    inst = seeded.installation
    assert inst is not None, "seed_installation first"
    source = Source(
        project_id=seeded.project.id,
        team_id=seeded.team.id,
        type=SourceType.GITHUB,
        name=repo,
        status=status,
        config={"repo": repo, "branch": "main"},
        installation_id=inst.id,
        secret_ref=installation_secret_ref(inst.id),
        last_error=last_error,
        created_by=(created_by or seeded.users[Role.MEMBER]).id,
    )
    db.add(source)
    await db.flush()
    seeded.sources.append(source)
    return source


async def seed_plain_source(
    db: AsyncSession, seeded: SeededTeam, *, created_by: User, name: str = "own"
) -> Source:
    """A connection-less, installation-less source (the legacy per-source path)."""
    source = Source(
        project_id=seeded.project.id,
        team_id=seeded.team.id,
        type=SourceType.GITHUB,
        name=name,
        status=SourceStatus.CONNECTED,
        config={"repo": f"me/{name}"},
        secret_ref=f"source/{uuid.uuid4()}",
        created_by=created_by.id,
    )
    db.add(source)
    await db.flush()
    return source
