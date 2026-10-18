"""ADR-037 §3: TeamInstallation changes publish a team.updated hint (ids only)."""

import pytest
from solus_api.core.db import build_sessionmaker
from solus_api.graph.live import Channel
from solus_api.graph.live_publisher import drain_pending_publishes
from solus_api.models import InstallationStatus, Team, TeamInstallation, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_live_publisher import RecordingHub, hub, plain_maker  # noqa: F401,F811

pytestmark = pytest.mark.usefixtures("hub")


@pytest.fixture
async def maker(engine: AsyncEngine, hub: RecordingHub) -> async_sessionmaker[AsyncSession]:  # noqa: F811
    return build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]


async def _seed(plain_maker: async_sessionmaker[AsyncSession]) -> tuple[Team, TeamInstallation]:  # noqa: F811
    async with plain_maker() as s:
        team = Team(name="T")
        s.add(team)
        await s.flush()
        row = TeamInstallation(
            team_id=team.id,
            provider="github",
            external_installation_id=9,
            account_login="acme",
            account_external_id=3,
            account_type="Organization",
            repository_selection="all",
            status=InstallationStatus.ACTIVE,
            linked_at=utcnow(),
        )
        s.add(row)
        await s.commit()
    return team, row


async def _commit(s: AsyncSession) -> None:
    await s.commit()
    await drain_pending_publishes()


def _assert_team_updated(
    hub: RecordingHub,  # noqa: F811
    team: Team,
) -> None:
    [(chan, frame)] = hub.published
    assert chan == Channel.team(team.id)
    assert frame["type"] == "team.updated"
    assert frame["team_id"] == str(team.id)
    assert frame["at"]
    assert set(frame) == {"type", "team_id", "at"}, "frame must carry ids only"


async def test_insert_publishes_team_updated(
    maker: async_sessionmaker[AsyncSession],
    hub: RecordingHub,  # noqa: F811
) -> None:
    async with maker() as s:
        team = Team(name="T")
        s.add(team)
        await s.flush()
        s.add(
            TeamInstallation(
                team_id=team.id,
                provider="github",
                external_installation_id=1,
                account_login="acme",
                account_external_id=3,
                account_type="Organization",
                repository_selection="all",
                status=InstallationStatus.ACTIVE,
                linked_at=utcnow(),
            )
        )
        await _commit(s)
    frames = [f for c, f in hub.published if f["type"] == "team.updated"]
    assert [f["team_id"] for f in frames] == [str(team.id)]
    assert all(set(f) == {"type", "team_id", "at"} for f in frames)
    assert all(c == Channel.team(team.id) for c, _ in hub.published)


async def test_update_publishes_team_updated(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    plain_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    hub: RecordingHub,  # noqa: F811
) -> None:
    team, row = await _seed(plain_maker)
    async with maker() as s:
        live = (
            await s.execute(select(TeamInstallation).where(TeamInstallation.id == row.id))
        ).scalar_one()
        live.status = InstallationStatus.SUSPENDED
        await _commit(s)
    _assert_team_updated(hub, team)


async def test_soft_delete_publishes_team_updated(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    plain_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    hub: RecordingHub,  # noqa: F811
) -> None:
    team, row = await _seed(plain_maker)
    async with maker() as s:
        live = (
            await s.execute(select(TeamInstallation).where(TeamInstallation.id == row.id))
        ).scalar_one()
        live.deleted_at = utcnow()
        await _commit(s)
    _assert_team_updated(hub, team)
