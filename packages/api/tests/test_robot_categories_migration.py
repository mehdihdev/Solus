"""a32600000001 (SOLUSDEV-326): `robot_category` nodes retire; a robot contains its parts.

The frozen sibling `migrations/robot_categories_retire.py` moves every manual `contains` edge
of an owned category, live and tombstoned, to the robot root (keeping the category label on
the edge), retires duplicates, robot → category edges, impostors and the category nodes,
backfills `attrs.robot_id`, and refuses to finish when an owned (robot, part) pair is lost.
The readers switched in the same commit then see the same parts.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from solus_api.hardware.ownership import current_parent
from solus_api.hardware.store import unassigned_parts_stmt
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    Source,
    SourceType,
    Team,
    utcnow,
)
from solus_api.services.physical_robots import orphaned_robot_part_filter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from test_hardware_data_migration import MigrationDatabase
from test_hardware_data_migration import migration_db as migration_db

API_DIR = Path(__file__).resolve().parents[1]
REV = "a32600000001"
PREVIOUS = "a32200000004"
KEYS = ("sensors", "actuators", "controllers", "end_effectors", "power", "structure", "wiring")
#: What the robot holds after the move: every live, category-owned part, plus the direct one.
OWNED = ("imu", "motor", "shared", "direct", "battery", "bracket")


def _module() -> Any:
    name = "solus_robot_categories_retire_326_test"
    spec = spec_from_file_location(name, API_DIR / "migrations" / "robot_categories_retire.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class OldWorld:
    project: uuid.UUID
    robot: uuid.UUID
    gone: uuid.UUID
    categories: dict[str, uuid.UUID]
    old_sensors: uuid.UUID
    impostor: uuid.UUID
    parts: dict[str, uuid.UUID]
    edges: dict[str, uuid.UUID]


async def _seed_old_world(db: AsyncSession) -> OldWorld:
    """What `PhysicalRobotService.create` and the category-era writers left behind: a robot,
    its seven categories and their parts (one part under two categories, one also held
    directly, a connector part, a manual part missing `robot_id`, a tombstoned edge), a
    deleted robot whose tombstoned edge is orphan evidence, and an impostor category that no
    robot edge owns."""
    team = Team(name="categories")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="categories")
    db.add(project)
    await db.flush()
    source = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.ONSHAPE,
        name="CAD",
        config={},
        status="connected",
    )
    db.add(source)
    await db.flush()
    pid, now = project.id, utcnow()

    def node(kind: str, name: str, **extra: Any) -> GraphEntity:
        return GraphEntity(
            project_id=pid, kind=kind, domain=Domain.PROJECT, origin="manual", name=name, **extra
        )

    robot = node("physical_robot", "Rover")
    gone = node("physical_robot", "Old rover", deleted_at=now)
    db.add_all([robot, gone])
    await db.flush()
    owner = {"robot_id": str(robot.id)}
    categories = {
        key: node("robot_category", key, attrs={**owner, "category": key}) for key in KEYS
    }
    old_sensors = node(
        "robot_category",
        "Sensors",
        attrs={"robot_id": str(gone.id), "category": "sensors"},
        deleted_at=now,
    )
    impostor = node("robot_category", "Sensors", attrs={**owner, "category": "sensors"})
    parts = {
        "imu": node("part", "IMU", attrs={**owner, "category": "sensors"}),
        "motor": node("part", "Motor", attrs={**owner, "category": "actuators"}),
        "shared": node("part", "Shared", attrs=dict(owner)),
        "direct": node("part", "Direct", attrs=dict(owner)),
        "battery": node("battery", "Battery"),
        "bracket": GraphEntity(
            project_id=pid,
            kind="part",
            domain=Domain.MECHANICAL,
            origin="connector",
            source_id=source.id,
            source_connector="onshape",
            external_ref="doc:1",
            name="Bracket",
        ),
        "removed": node("part", "Removed", attrs=dict(owner)),
        "spare": node("part", "Spare"),
        "stray": node("part", "Stray"),
    }
    db.add_all([*categories.values(), old_sensors, impostor, *parts.values()])
    await db.flush()

    def edge(src: uuid.UUID, dst: uuid.UUID, **extra: Any) -> GraphEdge:
        return GraphEdge(
            project_id=pid,
            src_id=src,
            dst_id=dst,
            relation_type="contains",
            domain_pair="project<->project",
            origin="manual",
            attrs={"evidence": [{"kind": "config", "ref": "user"}]},
            **extra,
        )

    cat, part = categories, {key: row.id for key, row in parts.items()}
    edges = {
        **{f"own:{key}": edge(robot.id, row.id) for key, row in cat.items()},
        "own:old": edge(gone.id, old_sensors.id, deleted_at=now),
        "imu": edge(cat["sensors"].id, part["imu"]),
        "motor": edge(cat["actuators"].id, part["motor"]),
        # Two categories of one robot hold the same part: the older edge moves.
        "shared": edge(cat["sensors"].id, part["shared"], created_at=now - timedelta(seconds=2)),
        "shared:dup": edge(
            cat["actuators"].id, part["shared"], created_at=now - timedelta(seconds=1)
        ),
        "direct": edge(robot.id, part["direct"]),
        "direct:dup": edge(cat["actuators"].id, part["direct"]),
        "battery": edge(cat["power"].id, part["battery"]),
        "bracket": edge(cat["structure"].id, part["bracket"]),
        "removed": edge(cat["wiring"].id, part["removed"], deleted_at=now),
        "spare": edge(old_sensors.id, part["spare"], deleted_at=now),
        "stray": edge(impostor.id, part["stray"]),
    }
    db.add_all(edges.values())
    await db.flush()
    return OldWorld(
        project=pid,
        robot=robot.id,
        gone=gone.id,
        categories={key: row.id for key, row in cat.items()},
        old_sensors=old_sensors.id,
        impostor=impostor.id,
        parts=part,
        edges={key: row.id for key, row in edges.items()},
    )


async def _run(db: AsyncSession, module: Any) -> dict[str, int]:
    def run(session: Session) -> dict[str, int]:
        return dict(module.retire_categories(session.connection()))

    counts = await db.run_sync(run)
    db.expire_all()
    return counts


async def _edge(db: AsyncSession, edge_id: uuid.UUID) -> GraphEdge:
    row = await db.scalar(select(GraphEdge).where(GraphEdge.id == edge_id))
    assert row is not None
    return row


async def test_retire_moves_owned_edges_to_the_robot_and_retires_the_rest(
    db: AsyncSession,
) -> None:
    module = _module()
    world = await _seed_old_world(db)

    counts = await _run(db, module)

    assert counts == {
        "owned_pairs": 6,
        "edges_moved": 7,
        "edges_retired": 10,
        "categories_retired": 8,
        "parts_backfilled": 1,
    }
    for key, category in (
        ("imu", "sensors"),
        ("motor", "actuators"),
        ("shared", "sensors"),
        ("battery", "power"),
        ("bracket", "structure"),
    ):
        moved = await _edge(db, world.edges[key])
        assert (moved.src_id, moved.deleted_at) == (world.robot, None), key
        assert moved.attrs["moved_from"] == str(world.categories[category])
        assert moved.attrs["moved_by"] == REV and moved.attrs["category"] == category
        assert moved.attrs["evidence"] == [{"kind": "config", "ref": "user"}]  # kept
    # Tombstones move too, and stay tombstones: removal evidence keeps its root.
    removed = await _edge(db, world.edges["removed"])
    assert removed.src_id == world.robot and removed.deleted_at is not None
    spare = await _edge(db, world.edges["spare"])
    assert spare.src_id == world.gone and spare.deleted_at is not None
    assert spare.attrs["moved_from"] == str(world.old_sensors)
    # Duplicates, robot → category edges and the impostor's edge retire where they are.
    for key in ("shared:dup", "direct:dup", "stray", *(f"own:{k}" for k in KEYS)):
        retired = await _edge(db, world.edges[key])
        assert retired.deleted_at is not None and retired.attrs["retired_by"] == REV, key
        assert "moved_by" not in retired.attrs
    direct = await _edge(db, world.edges["direct"])
    assert direct.deleted_at is None and "moved_by" not in direct.attrs
    nodes = {
        row.id: row
        for row in await db.scalars(
            select(GraphEntity).where(GraphEntity.project_id == world.project)
        )
    }
    for node_id in (*world.categories.values(), world.impostor):
        assert nodes[node_id].deleted_at is not None
        assert nodes[node_id].attrs["retired_by"] == REV
    assert "retired_by" not in nodes[world.old_sensors].attrs  # already deleted: untouched
    assert nodes[world.parts["battery"]].attrs["robot_id"] == str(world.robot)
    assert "robot_id" not in nodes[world.parts["bracket"]].attrs  # provider facts stay
    live_category_edges = await db.scalars(
        select(GraphEdge.id)
        .join(GraphEntity, GraphEntity.id.in_((GraphEdge.src_id, GraphEdge.dst_id)))
        .where(GraphEntity.kind == "robot_category", GraphEdge.deleted_at.is_(None))
    )
    assert list(live_category_edges) == []

    # The readers switched in this commit see the same parts the categories held.
    for key in OWNED:
        assert await current_parent(db, world.project, world.parts[key]) == world.robot, key
    for key in ("removed", "spare", "stray"):
        assert await current_parent(db, world.project, world.parts[key]) is None, key
    unassigned = set(
        await db.scalars(unassigned_parts_stmt(world.project).with_only_columns(GraphEntity.id))
    )
    assert unassigned == {world.parts[key] for key in ("removed", "spare", "stray")}
    orphans = set(
        await db.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == world.project,
                GraphEntity.deleted_at.is_(None),
                orphaned_robot_part_filter(world.project),
            )
        )
    )
    assert orphans == {world.parts["spare"]}

    again = await _run(db, module)
    assert again == {
        "owned_pairs": 6,
        "edges_moved": 0,
        "edges_retired": 0,
        "categories_retired": 0,
        "parts_backfilled": 0,
    }


async def test_the_post_check_refuses_a_world_that_still_has_categories(
    db: AsyncSession,
) -> None:
    module = _module()
    await _seed_old_world(db)

    def check(session: Session) -> None:
        connection = session.connection()
        module._check(connection, module._owned_pairs(connection))

    with pytest.raises(RuntimeError, match="robot_category"):
        await db.run_sync(check)


async def test_an_empty_graph_is_a_no_op(db: AsyncSession) -> None:
    counts = await _run(db, _module())
    assert counts == {
        "owned_pairs": 0,
        "edges_moved": 0,
        "edges_retired": 0,
        "categories_retired": 0,
        "parts_backfilled": 0,
    }


async def _seed_at(url: str) -> OldWorld:
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            world = await _seed_old_world(session)
            await session.commit()
            return world
    finally:
        await engine.dispose()


def test_chain_upgrade_retires_categories_and_the_downgrade_is_a_no_op(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(PREVIOUS)
    world = asyncio.run(_seed_at(migration_db.url))

    migration_db.upgrade(REV)

    live = "SELECT count(*) AS n FROM graph_entity WHERE kind = 'robot_category' "
    assert migration_db.rows(live + "AND deleted_at IS NULL")[0]["n"] == 0
    owned = migration_db.rows(
        "SELECT src_id, dst_id FROM graph_edge WHERE relation_type = 'contains' "
        "AND deleted_at IS NULL"
    )
    assert {(row["src_id"], row["dst_id"]) for row in owned} == {
        (world.robot, world.parts[key]) for key in OWNED
    }
    edges_sql = "SELECT id, src_id, deleted_at, attrs FROM graph_edge ORDER BY id"
    nodes_sql = "SELECT id, deleted_at, attrs FROM graph_entity ORDER BY id"
    snapshot = (migration_db.rows(edges_sql), migration_db.rows(nodes_sql))

    command.downgrade(migration_db.config, PREVIOUS)  # one-way: never raises, restores nothing
    assert (migration_db.rows(edges_sql), migration_db.rows(nodes_sql)) == snapshot
    migration_db.upgrade(REV)  # re-running the data step changes nothing
    assert (migration_db.rows(edges_sql), migration_db.rows(nodes_sql)) == snapshot
