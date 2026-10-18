"""TeamInstallation uniqueness (live rows only) and OAuthState.team_id cascade."""

import uuid
from datetime import timedelta

import pytest
from solus_api.models import (
    InstallationStatus,
    OAuthState,
    Team,
    TeamInstallation,
    User,
    utcnow,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _installation(team_id: uuid.UUID, external_id: int = 1001, **kw: object) -> TeamInstallation:
    fields: dict[str, object] = {
        "team_id": team_id,
        "provider": "github",
        "external_installation_id": external_id,
        "account_login": "acme",
        "account_external_id": 77,
        "account_type": "Organization",
        "repository_selection": "all",
        "status": InstallationStatus.ACTIVE,
        "linked_at": utcnow(),
    }
    fields.update(kw)
    return TeamInstallation(**fields)


async def _teams(db: AsyncSession, n: int = 2) -> list[Team]:
    teams = [Team(name=f"T{i}") for i in range(n)]
    db.add_all(teams)
    await db.flush()
    return teams


def test_installation_status_values() -> None:
    assert [s.value for s in InstallationStatus] == ["active", "suspended", "revoked"]


async def test_defaults_and_nullable_columns(db: AsyncSession) -> None:
    (team,) = await _teams(db, 1)
    row = _installation(team.id)
    db.add(row)
    await db.flush()
    assert row.api_base_url == "https://api.github.com"
    assert row.web_base_url == "https://github.com"
    assert row.linked_by is None and row.account_avatar_url is None
    assert row.suspended_at is None and row.revoked_at is None and row.deleted_at is None


async def test_installation_id_unique_among_live_rows_and_reusable_after_soft_delete(
    db: AsyncSession,
) -> None:
    a, b = await _teams(db)
    first = _installation(a.id)
    db.add(first)
    await db.flush()
    db.add(_installation(b.id))
    with pytest.raises(IntegrityError, match="uq_team_installations_provider_external"):
        await db.flush()
    await db.rollback()

    a, b = await _teams(db)
    first = _installation(a.id)
    db.add(first)
    await db.flush()
    first.deleted_at = utcnow()
    await db.flush()
    db.add(_installation(b.id))
    await db.flush()


async def test_one_live_installation_per_team_per_provider(db: AsyncSession) -> None:
    (team,) = await _teams(db, 1)
    first = _installation(team.id, 1)
    db.add(first)
    await db.flush()
    db.add(_installation(team.id, 2))
    with pytest.raises(IntegrityError, match="uq_team_installations_team_provider"):
        await db.flush()
    await db.rollback()

    (team,) = await _teams(db, 1)
    first = _installation(team.id, 1)
    db.add(first)
    await db.flush()
    first.deleted_at = utcnow()
    await db.flush()
    db.add(_installation(team.id, 2))
    await db.flush()


async def test_linked_by_is_nulled_when_the_user_is_deleted(db: AsyncSession) -> None:
    (team,) = await _teams(db, 1)
    user = User(supabase_user_id="u-216", email="u216@example.com")
    db.add(user)
    await db.flush()
    row = _installation(team.id, linked_by=user.id)
    db.add(row)
    await db.flush()
    await db.execute(delete(User).where(User.id == user.id))
    await db.refresh(row)
    assert row.linked_by is None


async def test_oauth_state_team_id_cascades_with_the_team(db: AsyncSession) -> None:
    (team,) = await _teams(db, 1)
    db.add(
        OAuthState(
            state="s-216",
            provider="github",
            user_id=uuid.uuid4(),
            team_id=team.id,
            redirect_uri="https://x.example/cb",
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    await db.flush()
    await db.execute(delete(Team).where(Team.id == team.id))
    assert (await db.execute(select(OAuthState))).scalars().all() == []
