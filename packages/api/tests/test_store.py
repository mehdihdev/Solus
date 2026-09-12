"""R5 hardware store (docs/api/hardware.md §2): the `.solus` Hardware-configs CONFIG entry is
created once per robot, referenced from the robot root, and every part written through it keeps
its entity id across lifecycle promotion."""

import uuid

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig, FieldProvenance, LifecycleState
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import (
    CONFIG_NODE_KIND,
    PART_KIND,
    config_of,
    create_part,
    ensure_config,
    promote,
    put_config,
    read_entity_config,
    robot_root,
)
from solus_api.models import GraphEdge, GraphEntity, SolusEntry, SolusEntryKind, SolusSection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _store_project(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"])


async def _store_robot(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID
) -> uuid.UUID:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=headers,
        json={"type": "physical_robot", "name": "Bench arm"},
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["id"])


async def test_ensure_config_creates_one_entry_and_references_it_from_the_robot(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    robot_id = await _store_robot(client, alice_headers, project_id)
    robot = await robot_root(db, project_id, robot_id)
    entry, config = await ensure_config(db, project_id, robot, created_by=None)
    again, _ = await ensure_config(db, project_id, robot, created_by=None)
    await db.commit()
    assert again.id == entry.id
    assert entry.kind is SolusEntryKind.CONFIG and entry.section is SolusSection.HARDWARE
    assert config.robot_entity_id == robot_id and config.parts == {}
    assert isinstance(config_of(entry), EntityHardwareConfig)
    assert await resolve_runtime_config(db, project_id, robot_id) == config
    refreshed = await db.get(GraphEntity, robot_id)
    assert refreshed is not None
    assert refreshed.attrs["hardware_config_ref"] == str(entry.id)
    node = await db.get(GraphEntity, entry.entity_id)
    assert node is not None and node.kind == CONFIG_NODE_KIND
    configures = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == node.id,
            GraphEdge.dst_id == robot_id,
            GraphEdge.relation_type == "configures",
            GraphEdge.deleted_at.is_(None),
        )
    )
    assert configures is not None
    rows = (
        await db.scalars(
            select(SolusEntry).where(
                SolusEntry.project_id == project_id, SolusEntry.kind == SolusEntryKind.CONFIG
            )
        )
    ).all()
    assert len(rows) == 1


async def test_put_config_refuses_another_robots_document(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    robot_id = await _store_robot(client, alice_headers, project_id)
    robot = await robot_root(db, project_id, robot_id)
    _, config = await ensure_config(db, project_id, robot, created_by=None)
    foreign = config.model_copy(update={"robot_entity_id": uuid.uuid4()})
    with pytest.raises(APIError) as excinfo:
        await put_config(db, project_id, robot, foreign, created_by=None)
    assert excinfo.value.status_code == 422


async def test_create_part_lands_under_the_category_and_in_the_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    robot_id = await _store_robot(client, alice_headers, project_id)
    robot = await robot_root(db, project_id, robot_id)
    part, entry = await create_part(
        db,
        project_id,
        robot,
        name="Pressure sensor",
        category="sensors",
        specs={"interface": "I2C", "supply_v": 3.3},
        lifecycle=LifecycleState.PLANNED,
        created_by=None,
    )
    await db.commit()
    assert part.kind == PART_KIND and part.origin == "manual" and part.source_id is None
    assert part.attrs["category"] == "sensors" and part.attrs["specs"]["interface"] == "I2C"
    category = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.kind == "robot_category",
            GraphEntity.attrs["robot_id"].astext == str(robot_id),
            GraphEntity.attrs["category"].astext == "sensors",
        )
    )
    assert category is not None
    edge = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == category.id,
            GraphEdge.dst_id == part.id,
            GraphEdge.relation_type == "contains",
            GraphEdge.deleted_at.is_(None),
        )
    )
    assert edge is not None and edge.origin == "manual" and edge.source_id is None
    _, config = await read_entity_config(db, project_id, part.id)
    assert config is not None and config.component is not None
    assert config.component.lifecycle is LifecycleState.PLANNED
    assert config.provenance_of("component.lifecycle").by is FieldProvenance.USER


async def test_create_part_refuses_an_unknown_category(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    robot_id = await _store_robot(client, alice_headers, project_id)
    robot = await robot_root(db, project_id, robot_id)
    with pytest.raises(APIError) as excinfo:
        await create_part(
            db,
            project_id,
            robot,
            name="x",
            category="propulsion",
            specs={},
            lifecycle=LifecycleState.PLANNED,
            created_by=None,
        )
    assert excinfo.value.status_code == 422


async def test_promote_keeps_the_entity_id_and_edges(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    robot_id = await _store_robot(client, alice_headers, project_id)
    robot = await robot_root(db, project_id, robot_id)
    part, _ = await create_part(
        db,
        project_id,
        robot,
        name="ESC",
        category="actuators",
        specs={},
        lifecycle=LifecycleState.ORDERED,
        created_by=None,
    )
    edges_before = (await db.scalars(select(GraphEdge.id).where(GraphEdge.dst_id == part.id))).all()
    for state in (LifecycleState.RECEIVED, LifecycleState.INSTALLED, LifecycleState.LIVE):
        promoted, _ = await promote(db, project_id, robot, part.id, state, created_by=None)
        assert promoted.lifecycle is state
    await db.commit()
    still = await db.get(GraphEntity, part.id)
    assert still is not None and still.deleted_at is None
    edges_after = (await db.scalars(select(GraphEdge.id).where(GraphEdge.dst_id == part.id))).all()
    assert edges_after == edges_before


async def test_promote_refuses_a_part_of_another_robot(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    first = await robot_root(db, project_id, await _store_robot(client, alice_headers, project_id))
    second = await robot_root(db, project_id, await _store_robot(client, alice_headers, project_id))
    part, _ = await create_part(
        db,
        project_id,
        first,
        name="IMU",
        category="sensors",
        specs={},
        lifecycle=LifecycleState.PLANNED,
        created_by=None,
    )
    with pytest.raises(APIError) as excinfo:
        await promote(db, project_id, second, part.id, LifecycleState.LIVE, created_by=None)
    assert excinfo.value.status_code == 404


async def test_robot_root_only_accepts_live_manual_robots(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _store_project(client, alice_headers)
    robot_id = await _store_robot(client, alice_headers, project_id)
    category = await db.scalar(
        select(GraphEntity).where(GraphEntity.attrs["robot_id"].astext == str(robot_id))
    )
    assert category is not None
    with pytest.raises(APIError):
        await robot_root(db, project_id, category.id)
    with pytest.raises(APIError):
        await robot_root(db, uuid.uuid4(), robot_id)
