"""`bench.view_changed` is derived from the committed bench_views row and published
only after commit (ADR-037 §3, docs/api/bench-view.md §3.4)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from solus_api.core.db import build_sessionmaker
from solus_api.core.errors import APIError
from solus_api.graph.live import Channel
from solus_api.graph.live_publisher import drain_pending_publishes
from solus_api.livebench.view.schemas import parse_ops
from solus_api.livebench.view.service import BenchViewService
from solus_api.models import Membership, Project, Role, Team, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

PIN = [
    {
        "kind": "set_display",
        "target": {"kind": "signal", "device_id": "d", "signal": "s"},
        "patch": {"pinned": True},
    }
]


class RecordingHub:
    def __init__(self) -> None:
        self.published: list[tuple[Channel, dict[str, Any]]] = []

    async def publish_to(self, target: Channel, frame: dict[str, Any]) -> None:
        self.published.append((target, frame))

    def frames(self) -> list[dict[str, Any]]:
        return [f for _, f in self.published if f["type"] == "bench.view_changed"]


@pytest.fixture
def hub() -> RecordingHub:
    return RecordingHub()


@pytest.fixture
def maker(engine: AsyncEngine, hub: RecordingHub) -> async_sessionmaker[AsyncSession]:
    return build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]


@pytest.fixture
async def world(engine: AsyncEngine) -> tuple[Team, User, Project]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        team = Team(name="T")
        user = User(supabase_user_id="u", email="u@x.io")
        s.add_all([team, user])
        await s.flush()
        project = Project(team_id=team.id, name="P")
        s.add_all([Membership(team_id=team.id, user_id=user.id, role=Role.MEMBER), project])
        await s.commit()
        return team, user, project


async def _apply(s: AsyncSession, world: tuple[Team, User, Project], version: int) -> Any:
    team, user, project = world
    return await BenchViewService(s).apply(
        project_id=project.id,
        team_id=team.id,
        user=user,
        role=Role.MEMBER,
        ops=parse_ops(PIN),
        expected_version=version,
    )


async def test_frame_is_published_after_commit_with_project_and_version_only(
    maker: async_sessionmaker[AsyncSession],
    hub: RecordingHub,
    world: tuple[Team, User, Project],
) -> None:
    async with maker() as s:
        await _apply(s, world, 0)
        await s.flush()
        await drain_pending_publishes()
        assert hub.frames() == []  # flushed but not committed: nothing yet
        await s.commit()
        await drain_pending_publishes()
    (frame,) = hub.frames()
    channel = next(c for c, f in hub.published if f is frame)
    assert channel == Channel.project(world[2].id)
    assert set(frame) == {"type", "project_id", "version", "at"}
    assert frame["project_id"] == str(world[2].id) and frame["version"] == 1

    async with maker() as s:  # an update (existing row) publishes the new version
        await _apply(s, world, 1)
        await s.commit()
        await drain_pending_publishes()
    assert [f["version"] for f in hub.frames()] == [1, 2]


async def test_rollback_publishes_nothing(
    maker: async_sessionmaker[AsyncSession],
    hub: RecordingHub,
    world: tuple[Team, User, Project],
) -> None:
    async with maker() as s:
        await _apply(s, world, 0)
        await s.rollback()
        await drain_pending_publishes()
    assert hub.frames() == []


async def test_conflict_publishes_nothing(
    maker: async_sessionmaker[AsyncSession],
    hub: RecordingHub,
    world: tuple[Team, User, Project],
) -> None:
    async with maker() as s:
        await _apply(s, world, 0)
        await s.commit()
        await drain_pending_publishes()
    hub.published.clear()
    async with maker() as s:
        with pytest.raises(APIError) as caught:
            await _apply(s, world, 0)
        assert caught.value.status_code == 409
        await s.rollback()
        await drain_pending_publishes()
    assert hub.frames() == []


async def test_frame_carries_no_view_content(
    maker: async_sessionmaker[AsyncSession],
    hub: RecordingHub,
    world: tuple[Team, User, Project],
) -> None:
    async with maker() as s:
        await _apply(s, world, 0)
        await s.commit()
        await drain_pending_publishes()
    blob = repr(hub.published)
    assert '"s"' not in blob and "pinned" not in blob
    assert uuid.UUID(hub.frames()[0]["project_id"]) == world[2].id
