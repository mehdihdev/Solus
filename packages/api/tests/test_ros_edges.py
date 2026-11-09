"""SOLUSDEV-321 P6 — `graph/inference/ros_edges.py`: what a ROS node's module declares becomes a
`publishes` / `subscribes` edge to the same source's topic at 0.9 (`origin=inferred`, evidence
`config` at the launch line, the declaring call in `detail`), a re-sync is idempotent and retires
what is no longer declared, and a live ROS graph only ever raises an edge that already stands
(`tests/fixtures/ros2_ws/`).
"""

from __future__ import annotations

import uuid
from typing import Any

from solus_api.connectors.contracts import SyncResult
from solus_api.connectors.local_folder import LocalFolderConnector, build_local_graph
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import apply_sync_result
from solus_api.graph.inference import InferenceReport, infer_after_sync, ros_edges
from solus_api.models import GraphEdge, GraphEntity, Source, SourceType
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_inference_power_nets import edge_rows, names_of, seed_project, seed_source
from test_local_folder import _scan, ros_fixture_scan


async def sync_ros(db: AsyncSession, source: Source, ros: list[dict[str, Any]]) -> None:
    entities, relations = build_local_graph(_scan(ros=ros), machine_name="m", gitlab_host=None)
    await apply_sync_result(db, source, SyncResult(entities=entities, relations=relations))


async def ros_edge_rows(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEdge]:
    return [
        *await edge_rows(db, project_id, "publishes"),
        *await edge_rows(db, project_id, "subscribes"),
    ]


async def test_declared_topics_become_inferred_edges_at_point_nine(db: AsyncSession) -> None:
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.LOCAL)
    await sync_ros(db, source, ros_fixture_scan("ros2_ws"))

    report = await ros_edges.infer(db, pid)

    edges = await ros_edge_rows(db, pid)
    names = await names_of(db, edges)
    by_pair = {(names[e.src_id], e.relation_type, names[e.dst_id]): e for e in edges}
    assert set(by_pair) == {
        ("/robot/talker", "publishes", "/robot/chatter"),
        ("/listener", "subscribes", "/robot/chatter"),
    }
    talker = by_pair[("/robot/talker", "publishes", "/robot/chatter")]
    assert (talker.origin, talker.confidence) == ("inferred", 0.9)
    assert talker.attrs["matrix_cell"] == "software->software"
    (evidence,) = talker.attrs["evidence"]
    assert evidence["kind"] == "config"
    assert evidence["ref"].startswith("src/talker_py/launch/talker.launch.py:")
    assert evidence["detail"].startswith("declared at src/talker_py/talker_py/talker.py:")
    assert report == InferenceReport("ros_edges", created=2, updated=0, skipped=0, candidates=0)

    again = await ros_edges.infer(db, pid)
    assert again == InferenceReport("ros_edges", created=0, updated=0, skipped=2, candidates=0)
    assert {e.id for e in await ros_edge_rows(db, pid)} == {e.id for e in edges}


async def test_a_topic_no_longer_declared_retires_its_inferred_edge(db: AsyncSession) -> None:
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.LOCAL)
    packages = ros_fixture_scan("ros2_ws")
    await sync_ros(db, source, packages)
    await ros_edges.infer(db, pid)

    for package in packages:
        for item in package["files"]:
            item["text"] = item["text"].replace("self.create_publisher", "self.make_nothing")
    await sync_ros(db, source, packages)
    await ros_edges.infer(db, pid)

    names = await names_of(db, edges := await ros_edge_rows(db, pid))
    assert [(names[e.src_id], e.relation_type) for e in edges] == [("/listener", "subscribes")]


async def test_a_node_joins_only_its_own_sources_topic(db: AsyncSession) -> None:
    """Two sources (a clone and another clone of the same workspace) land the same names: each
    node's edges stay inside its own source."""
    pid = await seed_project(db)
    first = await seed_source(db, pid, SourceType.LOCAL)
    second = await seed_source(db, pid, SourceType.LOCAL)
    await sync_ros(db, first, ros_fixture_scan("ros2_ws"))
    await sync_ros(db, second, ros_fixture_scan("ros2_ws"))

    await ros_edges.infer(db, pid)

    edges = await ros_edge_rows(db, pid)
    rows = await db.scalars(select(GraphEntity).where(GraphEntity.project_id == pid))
    source_of = {row.id: row.source_id for row in rows}
    assert len(edges) == 4
    assert all(source_of[e.src_id] == source_of[e.dst_id] for e in edges)


async def test_a_resync_without_its_last_ros_package_retires_the_edges(db: AsyncSession) -> None:
    """m4 (the pin moved from "runs only when ROS kinds landed"): the pass runs whenever a
    STRUCTURE source lands code or ROS kinds, so a re-sync that removes the last ROS package, and
    tombstones its nodes and topics, retires their inferred edges too."""
    registry = ConnectorRegistry()
    registry.register("local", LocalFolderConnector)
    pid = await seed_project(db)
    workspace = await seed_source(db, pid, SourceType.LOCAL)
    await sync_ros(db, workspace, ros_fixture_scan("ros2_ws"))

    reports = await infer_after_sync(db, pid, source_id=workspace.id, registry=registry)
    assert [report for report in reports if report.module == "ros_edges"] == [
        InferenceReport("ros_edges", created=2, updated=0, skipped=0, candidates=0)
    ]

    await sync_ros(db, workspace, [])  # the clone still lands; no ROS kind does
    again = await infer_after_sync(db, pid, source_id=workspace.id, registry=registry)
    assert "ros_edges" in [report.module for report in again]
    assert await ros_edge_rows(db, pid) == []


async def _counts(db: AsyncSession, project_id: uuid.UUID) -> tuple[int, int]:
    entities = await db.scalar(
        select(func.count()).select_from(GraphEntity).where(GraphEntity.project_id == project_id)
    )
    edges = await db.scalar(
        select(func.count()).select_from(GraphEdge).where(GraphEdge.project_id == project_id)
    )
    return int(entities or 0), int(edges or 0)


def test_live_names_are_ros_graph_names_only() -> None:
    """R131: the R3 grammar (at most 256 characters) before any writer sees a name; nothing else
    from a live listing is ever used."""
    too_long = "/" + "a" * 256
    listed = ["/talker", "/talker", "/robot/listener", "/talker\n", "not a name", 7, too_long]
    assert ros_edges.live_names(listed) == ["/talker", "/robot/listener"]


async def test_live_confirmation_bumps_existing_edges_only(db: AsyncSession) -> None:
    """R131: a live listing raises an existing inferred edge to 1.0 through `annotate_edge`
    (evidence `bus_enumeration`, the listing as `ref`); a topic's live type must agree with the
    declared one; a name that no edge carries writes nothing — no entity, no edge, ever, since any
    DDS participant on the network can announce one."""
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.LOCAL)
    await sync_ros(db, source, ros_fixture_scan("ros2_ws"))
    await ros_edges.infer(db, pid)
    before = await _counts(db, pid)
    seen = ros_edges.live_names(["/robot/talker", "/ghost", "/rosout"])

    raised = await ros_edges.confirm_live(db, pid, ref="ros2 node list", nodes=seen)

    edges = await ros_edge_rows(db, pid)
    names = await names_of(db, edges)
    by_pair = {(names[e.src_id], e.relation_type, names[e.dst_id]): e for e in edges}
    talker = by_pair[("/robot/talker", "publishes", "/robot/chatter")]
    listener = by_pair[("/listener", "subscribes", "/robot/chatter")]
    assert raised == 1 and (talker.origin, talker.confidence) == ("inferred", 1.0)
    assert talker.attrs["evidence"][-1] == {
        "kind": "bus_enumeration",
        "ref": "ros2 node list",
        "detail": "seen live: /robot/talker",
    }
    assert listener.confidence == 0.9

    disagreeing = {"/robot/chatter": "std_msgs/msg/Int32"}
    assert await ros_edges.confirm_live(db, pid, ref="ros2 topic list", topics=disagreeing) == 0
    agreeing = {"/robot/chatter": "std_msgs/msg/String", "/ghost": None}
    assert await ros_edges.confirm_live(db, pid, ref="ros2 topic list", topics=agreeing) == 1
    assert listener.confidence == 1.0  # the talker's edge already stood at 1.0
    assert await _counts(db, pid) == before  # nothing created, nothing for the ghost


async def test_confirm_live_applies_the_grammar_itself(db: AsyncSession) -> None:
    """m3: `confirm_live` is public, so it applies the R3 grammar itself and never trusts its
    caller: a name outside it raises nothing, even when an entity carries that very name."""
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.LOCAL)
    await sync_ros(db, source, ros_fixture_scan("ros2_ws"))
    await ros_edges.infer(db, pid)
    odd = {"/robot/talker": "/robot/talker; seen", "/robot/chatter": "/robot/chatter seen"}
    for entity in await db.scalars(
        select(GraphEntity).where(GraphEntity.project_id == pid, GraphEntity.name.in_(odd))
    ):
        entity.name = odd[entity.name]  # as though another path had landed it
    await db.flush()

    nodes, topics = [odd["/robot/talker"]], {odd["/robot/chatter"]: None}
    assert await ros_edges.confirm_live(db, pid, ref="ros2 node list", nodes=nodes) == 0
    assert await ros_edges.confirm_live(db, pid, ref="ros2 topic list", topics=topics) == 0
    assert [e.confidence for e in await ros_edge_rows(db, pid)] == [0.9, 0.9]
