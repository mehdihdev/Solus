"""SOLUSDEV-321 P6 (R131) — `agent/tools/ros_live.py`: a live ROS listing (`code.ros2_nodes`,
`code.ros2_topics`) reaches the model unchanged and then, never failing the call, raises only the
edges this project's graph already holds. Only the two composed names are wrapped, and only while
they are unconfirmed (docs/api/code-command-execution.md §12)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from solus_api.agent.tools import ros_live
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.graph.inference import ros_edges
from solus_api.models import DataEvent, GraphEdge, GraphEntity, Project, SourceType, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_inference_power_nets import names_of, seed_project, seed_source
from test_local_folder import ros_fixture_scan
from test_ros_edges import ros_edge_rows, sync_ros


class _Listing:
    """A bridge tool that answers one fixed listing."""

    def __init__(self, name: str, answer: dict[str, Any], *, gated: bool = False) -> None:
        self.descriptor = ToolDescriptor(
            name=name,
            description="a live listing",
            params={"type": "object"},
            returns={"type": "object"},
            requires_confirmation=gated,
        )
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(args)
        return self.answer


async def _ros_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project whose local source landed the `ros2_ws` fixture, inferred and committed."""
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.LOCAL)
    await sync_ros(db, source, ros_fixture_scan("ros2_ws"))
    await ros_edges.infer(db, pid)
    project = await db.get(Project, pid)
    assert project is not None
    return pid, project.team_id


async def _confidences(db: AsyncSession, project_id: uuid.UUID) -> dict[str, float]:
    db.expire_all()
    edges = await ros_edge_rows(db, project_id)
    names = await names_of(db, edges)
    return {names[edge.src_id]: edge.confidence for edge in edges}


async def _rows(db: AsyncSession, project_id: uuid.UUID) -> tuple[int, int]:
    counts = [
        await db.scalar(
            select(func.count()).select_from(model).where(model.project_id == project_id)
        )
        for model in (GraphEntity, GraphEdge)
    ]
    return int(counts[0] or 0), int(counts[1] or 0)


def _wrapped(
    engine: AsyncEngine, tool: _Listing, project: tuple[uuid.UUID, uuid.UUID], user: uuid.UUID
) -> Any:
    project_id, team_id = project
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return ros_live.live_graph_tool(tool, sessions, project_id, user_id=user, team_id=team_id)


def test_only_the_two_unconfirmed_live_reads_are_wrapped(engine: AsyncEngine) -> None:
    ids = (uuid.uuid4(), uuid.uuid4())
    other = _Listing("code.exec", {})
    gated = _Listing("code.ros2_nodes", {}, gated=True)
    assert _wrapped(engine, other, ids, uuid.uuid4()) is other
    assert _wrapped(engine, gated, ids, uuid.uuid4()) is gated
    for name in ("code.ros2_nodes", "code.ros2_topics"):
        live = _Listing(name, {})
        wrapped = _wrapped(engine, live, ids, uuid.uuid4())
        assert wrapped is not live and wrapped.descriptor is live.descriptor
    assert set(ros_live.LIVE_TOOLS) == {"code.ros2_nodes", "code.ros2_topics"}


async def test_a_live_listing_reaches_the_model_unchanged_and_raises_standing_edges_only(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    ours, theirs = await _ros_project(db), await _ros_project(db)
    user = User(supabase_user_id="ros-live", email="ros@example.com", data_collection_consent=True)
    db.add(user)
    await db.commit()
    user_id = user.id
    answer = {
        "ok": True,
        "nodes": ["/robot/talker", "/ghost", "bad name", "/robot/talker"],
        "truncated": False,
        "reason": None,
    }
    tool = _Listing("code.ros2_nodes", answer)
    before = await _rows(db, ours[0])

    got = await _wrapped(engine, tool, ours, user_id).invoke({"profile": "ros"})

    assert got is answer and tool.calls == [{"profile": "ros"}]
    assert await _confidences(db, ours[0]) == {"/robot/talker": 1.0, "/listener": 0.9}
    assert await _confidences(db, theirs[0]) == {"/robot/talker": 0.9, "/listener": 0.9}
    assert await _rows(db, ours[0]) == before  # nothing created, nothing for the ghost
    events = list(await db.scalars(select(DataEvent).where(DataEvent.project_id == ours[0])))
    assert [(e.event_type, e.payload) for e in events] == [
        ("ros.live_confirmed", {"tool": "code.ros2_nodes", "seen": 2, "bumped": 1})
    ]

    topics = {
        "ok": True,
        "topics": [{"name": "/robot/chatter", "type": "std_msgs/msg/String"}, {"name": 3}],
        "truncated": False,
        "reason": None,
    }
    await _wrapped(engine, _Listing("code.ros2_topics", topics), ours, user_id).invoke({})
    assert await _confidences(db, ours[0]) == {"/robot/talker": 1.0, "/listener": 1.0}


@pytest.mark.parametrize(
    "answer",
    [
        {"ok": False, "nodes": ["/robot/talker"], "truncated": False, "reason": "ros2 exited 1"},
        {"ok": True, "nodes": "/robot/talker", "truncated": False, "reason": None},
        {"ok": True, "nodes": [], "truncated": False, "reason": None},
    ],
    ids=["refused", "not-a-list", "empty"],
)
async def test_a_refused_or_malformed_listing_raises_nothing(
    db: AsyncSession, engine: AsyncEngine, answer: dict[str, Any]
) -> None:
    ours = await _ros_project(db)
    await db.commit()
    got = await _wrapped(engine, _Listing("code.ros2_nodes", answer), ours, uuid.uuid4()).invoke({})
    assert got is answer
    assert await _confidences(db, ours[0]) == {"/robot/talker": 0.9, "/listener": 0.9}


async def test_a_failing_raise_never_fails_the_call(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ours = await _ros_project(db)
    await db.commit()

    async def broken(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("the graph is away")

    monkeypatch.setattr(ros_edges, "confirm_live", broken)
    answer = {"ok": True, "nodes": ["/robot/talker"], "truncated": False, "reason": None}
    got = await _wrapped(engine, _Listing("code.ros2_nodes", answer), ours, uuid.uuid4()).invoke({})
    assert got is answer
