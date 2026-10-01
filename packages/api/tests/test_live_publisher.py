"""ADR-037 §3 — frames queue on the DB session and publish only after commit."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from solus_api.core.db import build_sessionmaker
from solus_api.graph.live import HUB_INFO_KEY, Channel
from solus_api.graph.live_publisher import drain_pending_publishes, install, queue_frame
from solus_api.models import (
    Activity,
    Invite,
    InviteStatus,
    Job,
    JobKind,
    JobStatus,
    Membership,
    MembershipStatus,
    Notification,
    NotificationType,
    Project,
    ProjectMembership,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
    WorkspaceLayout,
    utcnow,
)
from solus_contracts.live_events import AccessRevoked, TeamUpdated
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Published = list[tuple[Channel, dict[str, Any]]]


class RecordingHub:
    def __init__(self, *, fail: bool = False) -> None:
        self.published: Published = []
        self.fail = fail

    async def publish_to(self, target: Channel, frame: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("redis exploded")
        self.published.append((target, frame))

    def seen(self) -> list[tuple[str, str]]:
        return [(c.kind, f["type"]) for c, f in self.published]

    def find(self, kind: str, frame_type: str) -> list[dict[str, Any]]:
        return [f for c, f in self.published if c.kind == kind and f["type"] == frame_type]


@pytest.fixture
async def hub() -> RecordingHub:
    return RecordingHub()


@pytest.fixture
async def maker(engine: AsyncEngine, hub: RecordingHub) -> async_sessionmaker[AsyncSession]:
    return build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]


@pytest.fixture
def plain_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def commit_then_drain(session: AsyncSession) -> None:
    await session.commit()
    await drain_pending_publishes()


class World:
    """A team with an owner membership and one project, created WITHOUT frames."""

    team: Team
    owner: User
    member: User
    project: Project


@pytest.fixture
async def world(plain_maker: async_sessionmaker[AsyncSession]) -> World:
    w = World()
    async with plain_maker() as s:
        w.team = Team(name="T")
        w.owner = User(supabase_user_id="o", email="o@x.io")
        w.member = User(supabase_user_id="m", email="m@x.io")
        s.add_all([w.team, w.owner, w.member])
        await s.flush()
        w.project = Project(team_id=w.team.id, name="P")
        s.add_all([Membership(team_id=w.team.id, user_id=w.owner.id, role=Role.OWNER), w.project])
        await s.commit()
    return w


def test_install_is_idempotent() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    install()
    install()
    install()
    from solus_api.graph import live_publisher

    listeners = [
        fn for fn in (live_publisher._on_after_flush,) if event.contains(Session, "after_flush", fn)
    ]
    assert len(listeners) == 1


def test_the_sessionmaker_carries_the_hub_in_session_info(
    engine: AsyncEngine, hub: RecordingHub
) -> None:
    session = build_sessionmaker(engine, hub=hub)()  # type: ignore[arg-type]
    assert session.info[HUB_INFO_KEY] is hub
    assert HUB_INFO_KEY not in build_sessionmaker(engine)().info


# ------------------------------------------------------------------- mapping


async def test_activity_insert_publishes_team_activity(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(
            Activity(
                team_id=world.team.id,
                project_id=world.project.id,
                actor_id=world.owner.id,
                type="x",
            )
        )
        await commit_then_drain(s)

    [(chan, frame)] = hub.published
    assert chan == Channel.team(world.team.id)
    assert frame["type"] == "team.activity"
    assert frame["project_id"] == str(world.project.id)
    assert frame["actor_id"] == str(world.owner.id)
    assert frame["at"]


async def test_frames_publish_only_after_commit(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(Activity(team_id=world.team.id, type="x"))
        await s.flush()
        await drain_pending_publishes()
        assert hub.published == [], "published before commit"
        await commit_then_drain(s)
    assert hub.seen() == [("team", "team.activity")]


async def test_notification_insert_publishes_to_the_recipient_only(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(
            Notification(user_id=world.member.id, type=NotificationType.MEMBER_LEFT, title="secret")
        )
        await commit_then_drain(s)

    [(chan, frame)] = hub.published
    assert chan == Channel.user(world.member.id)
    assert frame["type"] == "notification.created"
    assert "secret" not in str(frame), "a frame must carry ids only, never content"


async def test_team_update_publishes_team_updated(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        team = await s.get(Team, world.team.id)
        assert team is not None
        team.name = "Renamed"
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.updated")]


async def test_team_soft_delete_publishes_updated_and_access_revoked(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        team = await s.get(Team, world.team.id)
        assert team is not None
        team.deleted_at = utcnow()
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.updated"), ("team", "access.revoked")]
    assert hub.find("team", "access.revoked")[0]["team_id"] == str(world.team.id)


async def test_team_hard_delete_publishes_updated_and_access_revoked(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, plain_maker: Any
) -> None:
    async with plain_maker() as s:
        team = Team(name="Doomed")
        s.add(team)
        await s.commit()
    async with maker() as s:
        row = await s.get(Team, team.id)
        assert row is not None
        await s.delete(row)
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.updated"), ("team", "access.revoked")]


async def test_membership_insert_publishes_members_changed_and_membership_changed(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(Membership(team_id=world.team.id, user_id=world.member.id, role=Role.MEMBER))
        await commit_then_drain(s)

    assert Channel.team(world.team.id) in [c for c, _ in hub.published]
    assert hub.seen() == [("team", "team.members_changed"), ("user", "membership.changed")]
    changed = hub.find("user", "membership.changed")[0]
    assert changed["user_id"] == str(world.member.id)
    assert changed["team_id"] == str(world.team.id)
    assert changed["project_id"] is None
    assert hub.published[1][0] == Channel.user(world.member.id)


async def test_membership_role_change_publishes_both_frames(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        membership = await s.scalar(select(Membership).where(Membership.team_id == world.team.id))
        assert membership is not None
        membership.role = Role.ADMIN
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.members_changed"), ("user", "membership.changed")]


async def test_membership_status_change_publishes_both_frames(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        membership = await s.scalar(select(Membership).where(Membership.team_id == world.team.id))
        assert membership is not None
        membership.status = next(v for v in MembershipStatus if v != membership.status)
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.members_changed"), ("user", "membership.changed")]


async def test_membership_soft_delete_revokes_the_user(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        membership = await s.scalar(select(Membership).where(Membership.team_id == world.team.id))
        assert membership is not None
        membership.deleted_at = utcnow()
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.members_changed"), ("user", "access.revoked")]
    revoked = hub.find("user", "access.revoked")[0]
    assert revoked["user_id"] == str(world.owner.id)
    assert revoked["team_id"] == str(world.team.id)
    assert revoked["project_id"] is None
    assert hub.published[1][0] == Channel.user(world.owner.id)


async def test_membership_hard_delete_revokes_the_user(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        membership = await s.scalar(select(Membership).where(Membership.team_id == world.team.id))
        assert membership is not None
        await s.delete(membership)
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.members_changed"), ("user", "access.revoked")]


async def test_project_membership_insert_and_delete(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        share = ProjectMembership(project_id=world.project.id, user_id=world.member.id)
        s.add(share)
        await commit_then_drain(s)
    [(chan, frame)] = hub.published
    assert chan == Channel.user(world.member.id)
    assert frame["type"] == "membership.changed"
    assert frame["project_id"] == str(world.project.id)
    assert frame["team_id"] is None

    hub.published.clear()
    async with maker() as s:
        row = await s.get(ProjectMembership, share.id)
        assert row is not None
        row.deleted_at = utcnow()
        await commit_then_drain(s)
    [(chan, frame)] = hub.published
    assert chan == Channel.user(world.member.id)
    assert frame["type"] == "access.revoked"
    assert frame["project_id"] == str(world.project.id)
    assert frame["user_id"] == str(world.member.id)

    hub.published.clear()
    async with maker() as s:
        row = await s.get(ProjectMembership, share.id)
        assert row is not None
        await s.delete(row)
        await commit_then_drain(s)
    assert hub.seen() == [("user", "access.revoked")]


async def test_invite_insert_and_status_change_publish_invites_changed(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        invite = Invite(
            team_id=world.team.id,
            email="new@x.io",
            expires_at=utcnow() + timedelta(days=1),
        )
        s.add(invite)
        await commit_then_drain(s)
    assert hub.seen() == [("team", "team.invites_changed")]
    assert "new@x.io" not in str(hub.published) and invite.token not in str(hub.published)

    hub.published.clear()
    async with maker() as s:
        row = await s.get(Invite, invite.id)
        assert row is not None
        row.status = InviteStatus.ACCEPTED
        await commit_then_drain(s)
    assert hub.seen() == [("team", "team.invites_changed")]


async def test_project_insert_publishes_team_projects_changed(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        project = Project(team_id=world.team.id, name="New")
        s.add(project)
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.projects_changed")]
    assert hub.published[0][1]["project_id"] == str(project.id)
    assert hub.published[0][0] == Channel.team(world.team.id)


@pytest.mark.parametrize("column", ["name", "description", "archived_at"])
async def test_project_update_publishes_team_and_project_frames(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World, column: str
) -> None:
    async with maker() as s:
        project = await s.get(Project, world.project.id)
        assert project is not None
        setattr(project, column, utcnow() if column == "archived_at" else "changed")
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.projects_changed"), ("project", "project.updated")]
    assert hub.published[1][0] == Channel.project(world.project.id)
    assert hub.published[1][1]["team_id"] == str(world.team.id)


async def test_project_soft_delete_revokes_the_project(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        project = await s.get(Project, world.project.id)
        assert project is not None
        project.deleted_at = utcnow()
        await commit_then_drain(s)

    assert hub.seen() == [
        ("team", "team.projects_changed"),
        ("project", "project.updated"),
        ("project", "access.revoked"),
    ]
    assert hub.find("project", "access.revoked")[0]["project_id"] == str(world.project.id)


async def test_project_hard_delete_revokes_the_project(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        project = await s.get(Project, world.project.id)
        assert project is not None
        await s.delete(project)
        await commit_then_drain(s)

    assert ("project", "access.revoked") in hub.seen()


def _source(world: World) -> Source:
    return Source(
        project_id=world.project.id,
        team_id=world.team.id,
        type=SourceType.GITHUB,
        name="s",
        status=SourceStatus.PENDING,
    )


async def test_source_insert_status_change_and_delete_publish_sources_changed(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        source = _source(world)
        s.add(source)
        await commit_then_drain(s)
    assert hub.seen() == [("project", "sources.changed")]
    assert hub.published[0][1]["source_id"] == str(source.id)
    assert hub.published[0][0] == Channel.project(world.project.id)

    for mutate in (
        lambda r: setattr(r, "status", SourceStatus.CONNECTED),
        lambda r: setattr(r, "name", "renamed"),
        lambda r: setattr(r, "last_synced_at", utcnow()),
        lambda r: setattr(r, "last_error", {"code": "x", "message": "y"}),
    ):
        hub.published.clear()
        async with maker() as s:
            row = await s.get(Source, source.id)
            assert row is not None
            mutate(row)
            await commit_then_drain(s)
        assert hub.seen() == [("project", "sources.changed")]

    hub.published.clear()
    async with maker() as s:
        row = await s.get(Source, source.id)
        assert row is not None
        await s.delete(row)
        await commit_then_drain(s)
    assert hub.seen() == [("project", "sources.changed")]


async def test_cursor_or_config_only_source_update_publishes_nothing(
    maker: async_sessionmaker[AsyncSession],
    plain_maker: async_sessionmaker[AsyncSession],
    hub: RecordingHub,
    world: World,
) -> None:
    async with plain_maker() as s:
        source = _source(world)
        s.add(source)
        await s.commit()
    async with maker() as s:
        row = await s.get(Source, source.id)
        assert row is not None
        row.cursor = {"rev": "abc"}
        row.config = {"documents": ["d"]}
        await commit_then_drain(s)

    assert hub.published == []


async def test_layout_insert_and_version_change_publish_layout_changed(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(WorkspaceLayout(project_id=world.project.id, version=1, positions={}))
        await commit_then_drain(s)
    assert hub.seen() == [("project", "layout.changed")]
    assert hub.published[0][1]["version"] == 1

    hub.published.clear()
    async with maker() as s:
        row = await s.get(WorkspaceLayout, world.project.id)
        assert row is not None
        row.version = 2
        await commit_then_drain(s)
    assert hub.seen() == [("project", "layout.changed")]
    assert hub.published[0][1]["version"] == 2

    hub.published.clear()
    async with maker() as s:  # positions-only edit at the same version is not a new version
        row = await s.get(WorkspaceLayout, world.project.id)
        assert row is not None
        row.positions = {"a": {"x": 1.0, "y": 2.0}}
        await commit_then_drain(s)
    assert hub.published == []


def _job(world: World) -> Job:
    return Job(project_id=world.project.id, team_id=world.team.id, kind=next(iter(JobKind)))


async def test_job_insert_and_status_change_publish_job_updated_but_progress_does_not(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        job = _job(world)
        s.add(job)
        await commit_then_drain(s)
    assert hub.seen() == [("project", "job.updated")]
    assert hub.published[0][1]["job_id"] == str(job.id)
    assert hub.published[0][1]["status"] == "queued"

    hub.published.clear()
    async with maker() as s:
        row = await s.get(Job, job.id)
        assert row is not None
        row.progress = 50
        await commit_then_drain(s)
    assert hub.published == [], "progress-only updates must not publish"

    async with maker() as s:
        row = await s.get(Job, job.id)
        assert row is not None
        row.status = JobStatus.RUNNING
        await commit_then_drain(s)
    assert hub.seen() == [("project", "job.updated")]
    assert hub.published[0][1]["status"] == "running"


# ---------------------------------------------------------------- transactions


async def test_rollback_publishes_nothing(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(Activity(team_id=world.team.id, type="x"))
        await s.flush()
        await s.rollback()
        await s.commit()
        await drain_pending_publishes()

    assert hub.published == []


async def test_an_exception_before_commit_publishes_nothing(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    with pytest.raises(RuntimeError):
        async with maker() as s:
            s.add(Activity(team_id=world.team.id, type="x"))
            await s.flush()
            raise RuntimeError("boom")
    await drain_pending_publishes()

    assert hub.published == []


async def test_a_closed_uncommitted_session_leaks_no_frames_into_its_next_use(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    s = maker()
    s.add(Activity(team_id=world.team.id, type="stale"))
    await s.flush()
    await s.close()
    s.add(Activity(team_id=world.team.id, type="fresh", actor_id=world.owner.id))
    await commit_then_drain(s)
    await s.close()

    assert hub.seen() == [("team", "team.activity")]


async def test_a_rolled_back_savepoint_drops_only_its_own_frames(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add(Activity(team_id=world.team.id, type="outer", actor_id=world.owner.id))
        await s.flush()
        nested = await s.begin_nested()
        s.add(Notification(user_id=world.member.id, type=NotificationType.MEMBER_LEFT, title="n"))
        await s.flush()
        await nested.rollback()
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.activity")]


async def test_a_released_savepoint_publishes_only_at_the_outer_commit(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        async with s.begin_nested():
            s.add(Activity(team_id=world.team.id, type="inner"))
        await drain_pending_publishes()
        assert hub.published == [], "a savepoint release is not a commit"
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.activity")]


async def test_a_released_savepoint_is_dropped_if_the_outer_transaction_rolls_back(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        async with s.begin_nested():
            s.add(Activity(team_id=world.team.id, type="inner"))
        await s.rollback()
        await drain_pending_publishes()

    assert hub.published == []


async def test_duplicate_changes_in_one_transaction_coalesce(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        for _ in range(3):
            s.add(Activity(team_id=world.team.id, project_id=world.project.id, type="x"))
        source = _source(world)
        s.add(source)
        await s.flush()
        row = await s.get(Source, source.id)
        assert row is not None
        row.status = SourceStatus.CONNECTED
        await s.flush()
        row.name = "again"
        await commit_then_drain(s)

    assert hub.seen().count(("team", "team.activity")) == 1
    assert hub.seen().count(("project", "sources.changed")) == 1


async def test_a_job_status_walk_in_one_transaction_publishes_the_latest_status_once(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        job = _job(world)
        s.add(job)
        await s.flush()
        job.status = JobStatus.RUNNING
        await s.flush()
        job.status = JobStatus.SUCCEEDED
        await commit_then_drain(s)

    [(_, frame)] = hub.published
    assert frame["status"] == "succeeded"


async def test_different_scopes_do_not_coalesce(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    other = uuid.uuid4()
    async with maker() as s:
        s.add(Activity(team_id=world.team.id, type="x"))
        s.add(Activity(team_id=other, type="x"))
        await commit_then_drain(s)

    assert {c.scope_id for c, _ in hub.published} == {world.team.id, other}


# ------------------------------------------------------------------- resilience


async def test_a_session_without_a_hub_commits_without_error(
    plain_maker: async_sessionmaker[AsyncSession], world: World
) -> None:
    async with plain_maker() as s:
        s.add(Activity(team_id=world.team.id, type="x"))
        queue_frame(s, Channel.team(world.team.id), TeamUpdated(team_id=world.team.id, at="t"))
        await s.commit()
    await drain_pending_publishes()


async def test_a_failing_hub_never_fails_the_commit(
    engine: AsyncEngine, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    broken = RecordingHub(fail=True)
    maker = build_sessionmaker(engine, hub=broken)  # type: ignore[arg-type]
    async with maker() as s:
        s.add(Activity(team_id=world.team.id, type="persisted"))
        await s.commit()
        await drain_pending_publishes()
        persisted = await s.scalar(select(Activity).where(Activity.type == "persisted"))
    assert persisted is not None
    assert any("live publish failed" in r.message for r in caplog.records)


async def test_queue_frame_publishes_after_commit_and_validates_the_shape(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        queue_frame(
            s,
            Channel.user(world.member.id),
            AccessRevoked(user_id=world.member.id, team_id=None, project_id=None, at="t"),
        )
        await s.flush()
        await drain_pending_publishes()
        assert hub.published == []
        await commit_then_drain(s)

    [(chan, frame)] = hub.published
    assert chan == Channel.user(world.member.id)
    assert frame == {
        "type": "access.revoked",
        "user_id": str(world.member.id),
        "team_id": None,
        "project_id": None,
        "at": "t",
    }


async def test_bulk_statements_bypass_orm_events_so_callers_queue_frames_explicitly(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    """Documents WHY routers/users.py queues explicit frames for its bulk deletes."""
    async with maker() as s:
        await s.execute(delete(Membership).where(Membership.team_id == world.team.id))
        await s.execute(update(Project).where(Project.id == world.project.id).values(name="z"))
        await commit_then_drain(s)

    assert hub.published == []


async def test_many_changes_in_one_transaction_stay_bounded(
    maker: async_sessionmaker[AsyncSession], hub: RecordingHub, world: World
) -> None:
    async with maker() as s:
        s.add_all(Activity(team_id=world.team.id, type="x") for _ in range(2_000))
        await commit_then_drain(s)

    assert hub.seen() == [("team", "team.activity")]
