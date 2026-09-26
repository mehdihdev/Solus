"""Brain topology preserves accepted configuration and imported part identities."""

import uuid

import pytest
from httpx import AsyncClient
from solus_api.models import GraphEdge, GraphEntity, SolusEntry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _hw_url, _robot, _saved_serial_arm


@pytest.mark.asyncio
async def test_topology_empty_read_is_pure_and_scoped(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    before = await db.scalar(select(func.count()).select_from(GraphEntity))
    url = _hw_url(project, "robots", robot["id"], "topology")
    response = await client.get(url, headers=alice_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "robot_id": robot["id"],
        "nodes": [],
        "edges": [],
        "roots": [],
    }
    assert await db.scalar(select(func.count()).select_from(GraphEntity)) == before
    assert (await client.get(url)).status_code == 401
    other, _ = await _hw_project(client, alice_headers)
    assert (
        await client.get(_hw_url(other, "robots", robot["id"], "topology"), headers=alice_headers)
    ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport,protocol",
    [("usb_serial", "serial-bus"), ("usb_can", "can-bus"), ("ethernet", "network-bus")],
)
async def test_accepted_config_persists_idempotent_topology_without_changing_runtime(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    transport: str,
    protocol: str,
) -> None:
    from solus_api.hardware.runtime import resolve_runtime_config
    from solus_api.hardware.topology import sync_topology

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    config["identity"]["kind"] = transport
    for item in config["bus_map"]:
        item["protocol"] = protocol
    response = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert response.status_code == 200, response.text
    project_id, robot_id = uuid.UUID(project), uuid.UUID(robot["id"])
    before = await resolve_runtime_config(db, project_id, robot_id)
    entries = list(await db.scalars(select(SolusEntry).where(SolusEntry.project_id == project_id)))
    snapshots = [(e.id, e.configured_entity_id, e.payload) for e in entries]
    result = await client.get(
        _hw_url(project, "robots", robot["id"], "topology"), headers=alice_headers
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert {p for p in config["parts"]} <= {n["id"] for n in data["nodes"]}
    assert any(n["role"] == "brain" for n in data["nodes"])
    assert any(n["role"] == "bus" for n in data["nodes"])
    assert all(n["software"] is None and n["presence"] is None for n in data["nodes"])
    assert all(n["role"] != "robot_category" for n in data["nodes"])
    count = await db.scalar(select(func.count()).select_from(GraphEdge))
    await sync_topology(db, project_id, robot_id)
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(GraphEdge)) == count
    assert await resolve_runtime_config(db, project_id, robot_id) == before
    await db.refresh(entries[0])
    assert [(e.id, e.configured_entity_id, e.payload) for e in entries] == snapshots


def test_cycles_and_ambiguous_parents_are_rejected() -> None:
    from solus_api.core.errors import APIError
    from solus_api.hardware.topology import TopologyEdge, _validate_tree

    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def edge(src: uuid.UUID, dst: uuid.UUID) -> TopologyEdge:
        return TopologyEdge(id=uuid.uuid4(), source=src, target=dst)

    with pytest.raises(APIError, match="cycle"):
        _validate_tree({a, b}, [edge(a, b), edge(b, a)], [])
    with pytest.raises(APIError, match="ambiguous"):
        _validate_tree({a, b, c}, [edge(a, c), edge(b, c)], [a, b])


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [None, "node", "link", "duplicate", "disabled"])
async def test_frozen_migration_rebuilds_same_projection_and_preserves_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, broken: str | None
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    from solus_api.hardware.topology import MARKER, read_topology
    from sqlalchemy import delete

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    response = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert response.status_code == 200, response.text
    project_id, robot_id = uuid.UUID(project), uuid.UUID(robot["id"])
    if broken == "disabled":
        from solus_api.hardware.bindings import disable_part_bindings
        from solus_api.hardware.topology import sync_topology

        part_id = uuid.UUID(config["bus_map"][0]["part_entity_id"])
        await disable_part_bindings(db, project_id, [part_id])
        await sync_topology(db, project_id, robot_id)
        await db.commit()
    before = await read_topology(db, project_id, robot_id)
    if broken == "disabled":
        assert all(edge.target != part_id for edge in before.edges)
    await db.execute(delete(GraphEdge).where(GraphEdge.attrs["managed_by"].astext == MARKER))
    await db.execute(delete(GraphEntity).where(GraphEntity.attrs["managed_by"].astext == MARKER))
    await db.commit()
    spec = spec_from_file_location(
        "topology_migration",
        Path(__file__).parents[1] / "migrations/versions/a26200000001_brain_topology.py",
    )
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    if broken in ("node", "link", "duplicate"):
        from solus_api.models import utcnow

        owner = await db.scalar(
            select(SolusEntry).where(
                SolusEntry.project_id == project_id, SolusEntry.configured_entity_id == robot_id
            )
        )
        assert owner is not None and owner.payload is not None
        if broken == "node":
            node = await db.get(GraphEntity, owner.entity_id)
            assert node is not None
            node.deleted_at = utcnow()
        elif broken == "link":
            link = await db.scalar(
                select(GraphEdge).where(
                    GraphEdge.src_id == owner.entity_id, GraphEdge.relation_type == "configures"
                )
            )
            assert link is not None
            link.deleted_at = utcnow()
        else:
            bus = owner.payload["bus_map"]
            owner.payload = {
                **owner.payload,
                "bus_map": [bus[0], {**bus[1], "part_entity_id": bus[0]["part_entity_id"]}],
            }
        await db.flush()
        connection = await db.connection()
        with pytest.raises(RuntimeError):
            await connection.run_sync(migration.upgrade_data)
        return
    connection = await db.connection()
    await connection.run_sync(migration.upgrade_data)
    await connection.run_sync(migration.upgrade_data)
    await db.commit()
    after = await read_topology(db, project_id, robot_id)
    assert after == before
    owner = await db.scalar(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id, SolusEntry.configured_entity_id == robot_id
        )
    )
    assert owner is not None and owner.payload is not None
    original = owner.payload
    owner.payload = {
        **original,
        "bus_map": [{**original["bus_map"][0], "part_entity_id": str(uuid.uuid4())}],
    }
    await db.execute(delete(GraphEdge).where(GraphEdge.attrs["managed_by"].astext == MARKER))
    await db.execute(delete(GraphEntity).where(GraphEntity.attrs["managed_by"].astext == MARKER))
    await db.flush()
    connection = await db.connection()
    savepoint = await connection.begin_nested()
    with pytest.raises(RuntimeError, match="absent or foreign"):
        await connection.run_sync(migration.upgrade_data)
    await savepoint.rollback()
    assert (
        await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.attrs["managed_by"].astext == MARKER)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_disabled_binding_removes_wiring_without_changing_part(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.hardware.bindings import disable_part_bindings
    from solus_api.hardware.topology import read_topology

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    response = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert response.status_code == 200, response.text
    part_id = uuid.UUID(next(iter(config["parts"])))
    await disable_part_bindings(db, uuid.UUID(project), [part_id])
    await db.commit()
    result = await read_topology(db, uuid.UUID(project), uuid.UUID(robot["id"]))
    assert not any(e.target == part_id for e in result.edges)
    assert any(n.id == part_id and n.category == "actuators" for n in result.nodes)


@pytest.mark.asyncio
async def test_topology_rejects_deleted_robot_and_cross_team_reader(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    url = _hw_url(project, "robots", robot["id"], "topology")
    assert (await client.get(url, headers=bob_headers)).status_code == 404
    removed = await client.delete(
        f"/api/v1/projects/{project}/entities/{robot['id']}",
        headers={**alice_headers, "If-Match": str(robot["version"])},
    )
    assert removed.status_code == 200, removed.text
    assert (await client.get(url, headers=alice_headers)).status_code == 404


@pytest.mark.asyncio
async def test_ambiguous_accepted_wiring_rolls_back_before_commit(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    config["bus_map"][1]["part_entity_id"] = config["bus_map"][0]["part_entity_id"]
    before = await db.scalar(select(func.count()).select_from(GraphEntity))
    entries_before = list(
        (
            await db.execute(
                select(SolusEntry.id, SolusEntry.payload, SolusEntry.config_version)
                .where(SolusEntry.project_id == uuid.UUID(project))
                .order_by(SolusEntry.id)
            )
        ).all()
    )
    response = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert response.status_code == 409, response.text
    assert await db.scalar(select(func.count()).select_from(GraphEntity)) == before
    assert (
        list(
            (
                await db.execute(
                    select(SolusEntry.id, SolusEntry.payload, SolusEntry.config_version)
                    .where(SolusEntry.project_id == uuid.UUID(project))
                    .order_by(SolusEntry.id)
                )
            ).all()
        )
        == entries_before
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_same_network_identity_refreshes_channel_without_replacing_node(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, shared: bool
) -> None:
    from solus_api.hardware.topology import MARKER, MEMBERSHIP, read_topology

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    config["identity"]["kind"] = "wifi"
    url = _hw_url(project, "robots", robot["id"], "config")
    first = await client.put(url, headers=alice_headers, json={"config": config})
    assert first.status_code == 200, first.text
    before = await read_topology(db, uuid.UUID(project), uuid.UUID(robot["id"]))
    brain_before = next(n for n in before.nodes if n.role == "brain")
    if shared:
        other = await _robot(client, alice_headers, project)
        db.add(
            GraphEdge(
                project_id=uuid.UUID(project),
                src_id=uuid.UUID(other["id"]),
                dst_id=brain_before.id,
                relation_type=MEMBERSHIP,
                domain_pair="project<->electrical",
                origin="manual",
                attrs={"managed_by": MARKER, "robot_id": other["id"]},
            )
        )
        await db.commit()
    config["identity"]["kind"] = "ethernet"
    second = await client.put(url, headers=alice_headers, json={"config": config})
    if shared:
        assert second.status_code == 409, second.text
        after = await read_topology(db, uuid.UUID(project), uuid.UUID(robot["id"]))
        assert next(n for n in after.nodes if n.role == "brain").channel == "wifi"
        return
    assert second.status_code == 200, second.text
    after = await read_topology(db, uuid.UUID(project), uuid.UUID(robot["id"]))
    brain_after = next(n for n in after.nodes if n.role == "brain")
    assert brain_before.id == brain_after.id
    assert brain_after.channel == "ethernet"


@pytest.mark.asyncio
async def test_migration_rejects_cross_owner_channel_conflict_before_writes(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    from solus_api.hardware.topology import MARKER
    from sqlalchemy import delete

    project, _ = await _hw_project(client, alice_headers)
    robots = [await _robot(client, alice_headers, project) for _ in range(2)]
    for index, robot in enumerate(robots):
        config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
        config["identity"]["kind"] = "wifi" if index == 0 else "ethernet"
        config["identity"]["binding"] = f"fixture-host-{index}"
        response = await client.put(
            _hw_url(project, "robots", robot["id"], "config"),
            headers=alice_headers,
            json={"config": config},
        )
        assert response.status_code == 200, response.text
    owner = await db.scalar(
        select(SolusEntry).where(
            SolusEntry.project_id == uuid.UUID(project),
            SolusEntry.configured_entity_id == uuid.UUID(robots[1]["id"]),
        )
    )
    assert owner is not None and owner.payload is not None
    owner.payload = {
        **owner.payload,
        "identity": {**owner.payload["identity"], "binding": "fixture-host-0"},
    }
    await db.execute(delete(GraphEdge).where(GraphEdge.attrs["managed_by"].astext == MARKER))
    await db.execute(delete(GraphEntity).where(GraphEntity.attrs["managed_by"].astext == MARKER))
    await db.flush()
    spec = spec_from_file_location(
        "topology_conflict_migration",
        Path(__file__).parents[1] / "migrations/versions/a26200000001_brain_topology.py",
    )
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db.connection()
    with pytest.raises(RuntimeError, match="channel"):
        await connection.run_sync(migration.upgrade_data)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.attrs["managed_by"].astext == MARKER)
        )
        == 0
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(GraphEdge)
            .where(GraphEdge.attrs["managed_by"].astext == MARKER)
        )
        == 0
    )
