"""SOLUSDEV-326 P1-T3: the brain topology is a DAG derived from the config's identity items.

A part may sit under two brains, a brain may be reached two ways, and only a cycle is refused.
`mcu`/`onboard` items mint their own brain node (`host` items are the endpoint as before, under
a reviewed host brain when one is attached), `via` wires one brain to another, a reviewed host
attach is scoped per endpoint, a brain's measured clock survives every resync, and a part shared
by two brains resolves telemetry from both.
"""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.bridge.registry import InMemoryBridgeSessionRegistry
from solus_api.core.errors import APIError
from solus_api.graph.edges import write_edge
from solus_api.graph.resolver import DbEntityResolver
from solus_api.hardware.config import (
    MAX_BRAINS,
    EntityHardwareConfig,
    FieldProvenance,
    PortableTransportBinding,
    ProvenanceRecord,
    TransportKind,
)
from solus_api.hardware.host_topology import HostAttachment, HostTopologyService, LocalHostProvider
from solus_api.hardware.store import put_entity_config, read_entity_config
from solus_api.hardware.topology import (
    HOST_MARKER,
    MARKER,
    RELATION,
    BrainClock,
    BrainFacts,
    RobotTopology,
    TopologyEdge,
    TopologyNode,
    clock_source,
    endpoint_id,
    read_topology,
    upsert_onboard_brain,
)
from solus_api.models import GraphEdge, GraphEntity, Project
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_hardware_identity_list import USER, _brain, _created, _project_row, _robot, _url

CLOCK = {
    "offset_ms": -12.5,
    "jitter_ms": 0.8,
    "measured_at": "2026-11-15T10:00:00+00:00",
    "method": "rtt8",
}


def _bus_row(protocol: str, address: str, part: GraphEntity | None, brain: str) -> dict[str, Any]:
    return {
        "protocol": protocol,
        "address": address,
        "part_entity_id": str(part.id) if part else None,
        "brain": brain,
    }


def _brains_config(
    robot: GraphEntity, brains: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> EntityHardwareConfig:
    return EntityHardwareConfig.model_validate(
        {
            "entity_id": str(robot.id),
            "identity": brains,
            "bus_map": rows,
            "provenance": {"identity": USER, "bus_map": USER},
        }
    )


async def _save_config(
    db: AsyncSession, project: Project, robot: GraphEntity, config: EntityHardwareConfig
) -> None:
    entry, _ = await read_entity_config(db, project.id, robot.id)
    await put_entity_config(
        db,
        project.id,
        robot,
        config,
        expected_version=entry.config_version if entry else 0,
        created_by=None,
    )
    await db.commit()


def _shared(robot: GraphEntity, part: GraphEntity) -> EntityHardwareConfig:
    """One part on two MCUs: address 1 behind usb:AAA, address 7 behind usb:BBB."""
    return _brains_config(
        robot,
        [_brain("AAA", "left-driver"), _brain("BBB", "right-driver")],
        [
            _bus_row("left-driver", "1", part, "usb:AAA"),
            _bus_row("right-driver", "7", part, "usb:BBB"),
        ],
    )


def _host_bus(project: Project, machine: str) -> uuid.UUID:
    return uuid.uuid5(uuid.uuid5(project.id, f"{HOST_MARKER}:host:{machine}"), "usb")


async def _attach_host(
    db: AsyncSession, project: Project, robot: GraphEntity, endpoint: uuid.UUID, machine: str
) -> None:
    """A reviewed host attach (the confirm route's persistence, without its live evidence)."""
    service = HostTopologyService(
        db,
        project_id=project.id,
        team_id=project.team_id,
        user_id=uuid.uuid4(),
        sessions=InMemoryBridgeSessionRegistry(),
        provider=LocalHostProvider(None),
    )
    body = HostAttachment(endpoint_id=endpoint, machine_id=machine, local_source_id=uuid.uuid4())
    topology = await read_topology(db, project.id, robot.id)
    preview = await service._preview(robot.id, body, topology, "Bench laptop", None)
    await service._persist(robot.id, body, preview)
    await db.commit()


# ----------------------------------------------------------------------------- DAG reads


async def test_a_part_behind_two_brains_reads_back_under_both(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (shared,) = await _robot(db, project, "shared")
    await _save_config(db, project, robot, _shared(robot, shared))

    topology = await read_topology(db, project.id, robot.id)
    left, right = endpoint_id(project.id, "usb:AAA"), endpoint_id(project.id, "usb:BBB")
    parents = {edge.source for edge in topology.edges if edge.target == shared.id}
    assert parents == {uuid.uuid5(left, "bus:left-driver"), uuid.uuid5(right, "bus:right-driver")}
    assert set(topology.roots) == {left, right}
    assert [node.id for node in topology.nodes].count(shared.id) == 1


async def test_one_part_twice_on_one_brain_is_refused_however_its_rows_name_it(
    db: AsyncSession,
) -> None:
    """On a one-brain config an implicit row and a row naming that brain sit on the SAME brain."""
    project = await _project_row(db)
    robot, (part,) = await _robot(db, project, "twice")
    implicit = {"protocol": "bus", "address": "1", "part_entity_id": str(part.id)}
    rows = [implicit, _bus_row("bus", "2", part, "usb:AAA")]
    with pytest.raises(APIError) as refused:
        await _save_config(db, project, robot, _brains_config(robot, [_brain("AAA", "bus")], rows))
    assert (refused.value.status_code, refused.value.code) == (409, "topology_conflict")


async def test_a_stored_cycle_is_still_refused(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (part,) = await _robot(db, project, "loop")
    config = _brains_config(robot, [_brain("AAA", "bus")], [_bus_row("bus", "1", part, "usb:AAA")])
    await _save_config(db, project, robot, config)
    await write_edge(
        db,
        project_id=project.id,
        src_id=part.id,
        dst_id=endpoint_id(project.id, "usb:AAA"),
        relation_type=RELATION,
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=None,
        attrs={"managed_by": MARKER, "robot_id": str(robot.id)},
        edge_id=uuid.uuid4(),
        managed_by=MARKER,
    )
    await db.commit()
    with pytest.raises(APIError, match="cycle"):
        await read_topology(db, project.id, robot.id)


# ----------------------------------------------------------------------------- brains from items


def _items_config(robot: GraphEntity, arm: GraphEntity, wheel: GraphEntity) -> EntityHardwareConfig:
    """A host-driven bus adapter, a bare MCU, a robot computer and an MCU behind it."""
    return _brains_config(
        robot,
        [
            _brain("HOST1", "bus", kind="host"),
            _brain("MCU1", "lines", kind="mcu"),
            {"kind": "onboard", "binding": {"kind": "ethernet", "binding": "10.0.0.2"}},
            {**_brain("MCU2", "lines", kind="mcu"), "via": "ip:10.0.0.2"},
        ],
        [_bus_row("bus", "1", arm, "usb:HOST1"), _bus_row("i2c", "0x68", wheel, "usb:MCU2")],
    )


async def test_identity_items_derive_their_brains_with_stable_ids(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (arm, wheel) = await _robot(db, project, "arm", "wheel")
    await _save_config(db, project, robot, _items_config(robot, arm, wheel))

    topology = await read_topology(db, project.id, robot.id)
    ep = {ref: endpoint_id(project.id, ref) for ref in ("usb:HOST1", "usb:MCU1", "usb:MCU2")}
    ep["ip:10.0.0.2"] = endpoint_id(project.id, "ip:10.0.0.2")
    brains = {node.id: node for node in topology.nodes if node.role == "brain"}
    assert set(brains) == set(ep.values())  # no host node is minted by the config
    assert {ref: brains[node].brain_kind for ref, node in ep.items()} == {
        "usb:HOST1": None,  # a host-driven endpoint, as before; the host comes from review
        "usb:MCU1": "mcu",
        "ip:10.0.0.2": "onboard",
        "usb:MCU2": "mcu",
    }
    assert brains[ep["ip:10.0.0.2"]].channel == "ethernet"
    links = {(edge.source, edge.target) for edge in topology.edges}
    assert (ep["ip:10.0.0.2"], ep["usb:MCU2"]) in links  # `via`: brain → brain
    assert (uuid.uuid5(ep["usb:MCU2"], "bus:i2c"), wheel.id) in links
    assert set(topology.roots) == {ep["usb:HOST1"], ep["usb:MCU1"], ep["ip:10.0.0.2"]}

    # A resync after a change keeps every brain's identity; a dropped `via` drops its wire.
    changed = _items_config(robot, arm, wheel).model_dump(mode="json")
    changed["identity"][3]["via"] = None
    await _save_config(db, project, robot, EntityHardwareConfig.model_validate(changed))
    again = await read_topology(db, project.id, robot.id)
    assert {node.id for node in again.nodes if node.role == "brain"} == set(ep.values())
    assert (ep["ip:10.0.0.2"], ep["usb:MCU2"]) not in {(e.source, e.target) for e in again.edges}


async def test_a_brain_reached_two_ways_reads_back(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (arm, wheel) = await _robot(db, project, "arm", "wheel")
    await _save_config(db, project, robot, _items_config(robot, arm, wheel))
    mcu = endpoint_id(project.id, "usb:MCU2")
    await _attach_host(db, project, robot, mcu, "bench-laptop")

    topology = await read_topology(db, project.id, robot.id)
    parents = {edge.source for edge in topology.edges if edge.target == mcu}
    assert parents == {endpoint_id(project.id, "ip:10.0.0.2"), _host_bus(project, "bench-laptop")}
    node = next(n for n in topology.nodes if n.id == mcu)
    assert node.brain_kind == "mcu"  # the config's item outranks a host declaration
    assert {(e.by, e.source) for e in node.evidence} >= {("user", None)}


# ----------------------------------------------------------------------------- host attach


async def test_a_second_endpoint_on_one_host_keeps_the_first(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (left, right) = await _robot(db, project, "left", "right")
    two = _brains_config(
        robot,
        [_brain("AAA", "left-driver", kind="host"), _brain("BBB", "right-driver", kind="host")],
        [
            _bus_row("left-driver", "1", left, "usb:AAA"),
            _bus_row("right-driver", "1", right, "usb:BBB"),
        ],
    )
    await _save_config(db, project, robot, two)
    aaa, bbb = endpoint_id(project.id, "usb:AAA"), endpoint_id(project.id, "usb:BBB")
    usb = _host_bus(project, "bench-laptop")
    await _attach_host(db, project, robot, aaa, "bench-laptop")
    await _attach_host(db, project, robot, bbb, "bench-laptop")

    topology = await read_topology(db, project.id, robot.id)
    assert {edge.target for edge in topology.edges if edge.source == usb} == {aaa, bbb}
    assert [n.brain_kind for n in topology.nodes].count("host") == 1

    # Dropping one brain retires only its host wire; the shared host edges keep serving the other.
    one = _brains_config(
        robot,
        [_brain("AAA", "left-driver", kind="host")],
        [_bus_row("left-driver", "1", left, "usb:AAA")],
    )
    await _save_config(db, project, robot, one)
    after = await read_topology(db, project.id, robot.id)
    assert {edge.target for edge in after.edges if edge.source == usb} == {aaa}
    live = list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project.id,
                GraphEdge.attrs["managed_by"].astext == HOST_MARKER,
                GraphEdge.deleted_at.is_(None),
            )
        )
    )
    assert {tuple(edge.attrs["endpoint_ids"]) for edge in live} == {(str(aaa),)}


# ----------------------------------------------------------------------------- clock


async def test_a_brains_clock_survives_a_resync_and_reads_back(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (arm, wheel) = await _robot(db, project, "arm", "wheel")
    await _save_config(db, project, robot, _items_config(robot, arm, wheel))
    onboard = endpoint_id(project.id, "ip:10.0.0.2")
    node = await db.get(GraphEntity, onboard)
    assert node is not None
    node.attrs = {**node.attrs, "clock": CLOCK}
    await db.commit()

    changed = _items_config(robot, arm, wheel).model_dump(mode="json")
    changed["bus_map"] = changed["bus_map"][:1]
    await _save_config(db, project, robot, EntityHardwareConfig.model_validate(changed))
    await db.refresh(node)
    assert node.attrs["clock"] == CLOCK and node.attrs["brain_kind"] == "onboard"
    topology = await read_topology(db, project.id, robot.id)
    read = next(n for n in topology.nodes if n.id == onboard)
    assert read.clock == BrainClock.model_validate(CLOCK)
    assert all(n.clock is None for n in topology.nodes if n.id != onboard)

    node.attrs = {**node.attrs, "clock": {"offset_ms": "soon"}}  # never 500 on a bad stored fact
    await db.commit()
    topology = await read_topology(db, project.id, robot.id)
    assert next(n for n in topology.nodes if n.id == onboard).clock is None


def test_a_clock_is_finite_and_bounded() -> None:
    for bad in (
        {**CLOCK, "offset_ms": float("nan")},
        {**CLOCK, "jitter_ms": -1.0},
        {**CLOCK, "method": ""},
        {**CLOCK, "extra": 1},
    ):
        with pytest.raises(ValueError):
            BrainClock.model_validate(bad)


def _stamping_topology() -> tuple[RobotTopology, dict[str, uuid.UUID]]:
    """host H → usb U → mcu E → bus B → part P; onboard O → bus B2 → part Q, and B → Q too."""
    ids = {name: uuid.uuid4() for name in ("H", "U", "E", "B", "P", "O", "B2", "Q")}
    roles: dict[str, Any] = {"H": "brain", "E": "brain", "O": "brain", "P": "part", "Q": "part"}
    kinds: dict[str, Any] = {"H": "host", "E": "mcu", "O": "onboard"}
    nodes = [
        TopologyNode(id=ids[n], name=n, role=roles.get(n, "bus"), brain_kind=kinds.get(n))
        for n in ids
    ]
    pairs = [("H", "U"), ("U", "E"), ("E", "B"), ("B", "P"), ("O", "B2"), ("B2", "Q"), ("B", "Q")]
    edges = [TopologyEdge(id=uuid.uuid4(), source=ids[s], target=ids[t]) for s, t in pairs]
    roots = [ids["H"], ids["O"]]
    return RobotTopology(robot_id=uuid.uuid4(), nodes=nodes, edges=edges, roots=roots), ids


def test_clock_source_names_the_brain_that_stamps_a_parts_data() -> None:
    topology, ids = _stamping_topology()
    assert clock_source(topology, ids["P"], device_stamped=True) == ids["E"]
    assert clock_source(topology, ids["P"], device_stamped=False) == ids["H"]
    # A part under two brains needs the brain its data came through.
    assert clock_source(topology, ids["Q"], device_stamped=True) is None
    assert clock_source(topology, ids["Q"], device_stamped=True, endpoint=ids["O"]) == ids["O"]
    assert clock_source(topology, ids["Q"], device_stamped=False, endpoint=ids["E"]) == ids["H"]
    # No host brain is recorded above the robot computer: unknown, never guessed.
    assert clock_source(topology, ids["Q"], device_stamped=False, endpoint=ids["O"]) is None
    assert clock_source(topology, ids["P"], device_stamped=True, endpoint=ids["O"]) is None
    assert clock_source(topology, uuid.uuid4(), device_stamped=True) is None


# ----------------------------------------------------------------------------- onboard writer


async def test_the_onboard_writer_adds_an_item_and_sync_derives_its_node(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (arm,) = await _robot(db, project, "arm")
    one = _brains_config(robot, [_brain("AAA", "bus")], [])
    one = EntityHardwareConfig.model_validate(
        {
            **one.model_dump(mode="json"),
            "bus_map": [{"protocol": "bus", "address": "1", "part_entity_id": str(arm.id)}],
        }
    )
    await _save_config(db, project, robot, one)
    detected = ProvenanceRecord(by=FieldProvenance.DETECTED)
    computer = PortableTransportBinding(kind=TransportKind.ETHERNET, binding="10.0.0.2")

    node = await upsert_onboard_brain(
        db,
        project.id,
        robot.id,
        computer,
        record=detected,
        facts=BrainFacts(clock=BrainClock.model_validate(CLOCK), software="ros2 jazzy"),
        created_by=None,
    )
    await db.commit()
    assert node == endpoint_id(project.id, "ip:10.0.0.2")
    entry, config = await read_entity_config(db, project.id, robot.id)
    assert entry is not None and config is not None
    assert [(b.kind, b.device_ref) for b in config.identity] == [
        ("mcu", "usb:AAA"),
        ("onboard", "ip:10.0.0.2"),
    ]
    assert config.provenance_of("identity.1.kind") == detected
    assert [row.brain for row in config.bus_map] == ["usb:AAA"]  # the old row names its brain now
    topology = await read_topology(db, project.id, robot.id)
    brain = next(n for n in topology.nodes if n.id == node)
    assert (brain.brain_kind, brain.software) == ("onboard", "ros2 jazzy")
    assert brain.clock == BrainClock.model_validate(CLOCK)

    # The same item again with a fresh clock: no new config version, the fact moves.
    version = entry.config_version
    later = BrainClock.model_validate({**CLOCK, "offset_ms": 3.0})
    await upsert_onboard_brain(
        db,
        project.id,
        robot.id,
        computer,
        record=detected,
        facts=BrainFacts(clock=later),
        created_by=None,
    )
    await db.commit()
    entry, _ = await read_entity_config(db, project.id, robot.id)
    assert entry is not None and entry.config_version == version
    topology = await read_topology(db, project.id, robot.id)
    brain = next(n for n in topology.nodes if n.id == node)
    assert brain.clock == later and brain.software == "ros2 jazzy"

    # An MCU behind the computer: the item names it as `via`, the sync wires it.
    await upsert_onboard_brain(
        db,
        project.id,
        robot.id,
        computer,
        record=detected,
        via="usb:AAA",
        created_by=None,
    )
    await db.commit()
    topology = await read_topology(db, project.id, robot.id)
    assert (endpoint_id(project.id, "usb:AAA"), node) in {
        (e.source, e.target) for e in topology.edges
    }


async def test_the_onboard_writer_refuses_another_projects_robot(db: AsyncSession) -> None:
    project, other = await _project_row(db), await _project_row(db)
    robot, _ = await _robot(db, project)
    await db.commit()
    with pytest.raises(APIError) as refused:
        await upsert_onboard_brain(
            db,
            other.id,
            robot.id,
            PortableTransportBinding(kind=TransportKind.ETHERNET, binding="10.0.0.2"),
            record=ProvenanceRecord(by=FieldProvenance.SOL),
            created_by=None,
        )
    assert refused.value.status_code == 404
    entries = await read_entity_config(db, project.id, robot.id)
    assert entries == (None, None)


async def test_the_onboard_writer_adds_a_computer_reached_through_another_brain(
    db: AsyncSession,
) -> None:
    """A NEW item may name `via`: a brain of the robot's config, never of the item alone."""
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    main = {"kind": "onboard", "binding": {"kind": "ethernet", "binding": "10.0.0.2"}}
    await _save_config(db, project, robot, _brains_config(robot, [main], []))
    detected = ProvenanceRecord(by=FieldProvenance.DETECTED)
    second = PortableTransportBinding(kind=TransportKind.ETHERNET, binding="10.0.0.3")

    node = await upsert_onboard_brain(
        db, project.id, robot.id, second, record=detected, via="ip:10.0.0.2", created_by=None
    )
    await db.commit()
    _, config = await read_entity_config(db, project.id, robot.id)
    assert config is not None
    assert [(b.device_ref, b.via) for b in config.identity] == [
        ("ip:10.0.0.2", None),
        ("ip:10.0.0.3", "ip:10.0.0.2"),
    ]
    assert config.provenance_of("identity.1.via") == detected
    topology = await read_topology(db, project.id, robot.id)
    assert (endpoint_id(project.id, "ip:10.0.0.2"), node) in {
        (e.source, e.target) for e in topology.edges
    }


async def test_the_onboard_writer_says_why_a_brain_cannot_join(db: AsyncSession) -> None:
    """A result that does not validate is a 422 naming why (never a 500, never the unbound-brain
    409) and writes nothing; only a sole unbound brain owning implicit rows is that 409."""
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    record = ProvenanceRecord(by=FieldProvenance.DETECTED)
    computer = PortableTransportBinding(kind=TransportKind.ETHERNET, binding="10.0.0.2")
    mcu = PortableTransportBinding(kind=TransportKind.USB_SERIAL, binding="B0")

    async def refusal(binding: PortableTransportBinding, via: str | None = None) -> APIError:
        with pytest.raises(APIError) as refused:
            await upsert_onboard_brain(
                db, project.id, robot.id, binding, record=record, via=via, created_by=None
            )
        return refused.value

    await _save_config(db, project, robot, _brains_config(robot, [_brain("B0", "drv")], []))
    for binding, via, reason in (
        (computer, "usb:ZZZ", "via must name another brain"),  # a new item, an unknown brain
        (mcu, "usb:B0", "via must name another brain"),  # a replaced item, through itself
        (computer, "not a ref", "should match pattern"),
    ):
        error = await refusal(binding, via)
        assert (error.status_code, error.code) == (422, "validation_error")
        assert reason in error.message
    full = [_brain(f"B{index}", "drv") for index in range(MAX_BRAINS)]
    await _save_config(db, project, robot, _brains_config(robot, full, []))
    error = await refusal(computer)
    assert (error.status_code, error.code) == (422, "validation_error")
    assert f"at most {MAX_BRAINS}" in error.message
    entry, _ = await read_entity_config(db, project.id, robot.id)
    assert entry is not None and entry.config_version == 2  # no refusal wrote a version

    unbound = {"kind": "mcu", "protocol": {"driver_id": "drv", "params": {}}}
    implicit = [{"protocol": "drv", "address": "1"}]
    await _save_config(db, project, robot, _brains_config(robot, [unbound], implicit))
    error = await refusal(computer)
    assert (error.status_code, error.code) == (409, "config_conflict")


# ----------------------------------------------------------------------------- aliases


async def test_a_part_shared_by_two_brains_resolves_telemetry_from_both(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project = await _project_row(db)
    robot, (shared,) = await _robot(db, project, "shared")
    await _save_config(db, project, robot, _shared(robot, shared))
    resolver = DbEntityResolver(async_sessionmaker(engine, expire_on_commit=False))

    await db.refresh(shared)
    assert shared.attrs["ref_aliases"] == ["usb:AAA/1", "usb:BBB/7"]
    assert await resolver.resolve(project.id, "usb:AAA/1") == shared.id
    assert await resolver.resolve(project.id, "usb:BBB/7") == shared.id

    # Back on one brain: no alias; the part resolves by `external_ref` alone, as before 326.
    one = _brains_config(robot, [_brain("AAA", "left-driver")], [])
    one = EntityHardwareConfig.model_validate(
        {
            **one.model_dump(mode="json"),
            "bus_map": [
                {"protocol": "left-driver", "address": "1", "part_entity_id": str(shared.id)}
            ],
        }
    )
    await _save_config(db, project, robot, one)
    await db.refresh(shared)
    assert "ref_aliases" not in shared.attrs

    # Shared again, then off the bus map entirely: no alias is left behind.
    await _save_config(db, project, robot, _shared(robot, shared))
    await db.refresh(shared)
    assert shared.attrs["ref_aliases"] == ["usb:AAA/1", "usb:BBB/7"]
    bare = [_brain("AAA", "left-driver"), _brain("BBB", "right-driver")]
    await _save_config(db, project, robot, _brains_config(robot, bare, []))
    await db.refresh(shared)
    assert "ref_aliases" not in shared.attrs
    assert await resolver.resolve(project.id, "usb:BBB/7") is None


# ----------------------------------------------------------------------------- the routes


async def test_a_dag_topology_is_read_only_by_its_team(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    await me(client, alice_headers)
    await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = str((await create_project(client, alice_headers, team["id"]))["id"])
    robot = await _created(client, alice_headers, project, kind="robot", name="Rover")
    part = await _created(client, alice_headers, project, kind="part", name="Shared")
    body = {
        "schema_version": 2,
        "entity_id": robot,
        "identity": [_brain("AAA", "left-driver"), _brain("BBB", "right-driver")],
        "bus_map": [
            {"protocol": "left-driver", "address": "1", "part_entity_id": part, "brain": "usb:AAA"},
            {
                "protocol": "right-driver",
                "address": "7",
                "part_entity_id": part,
                "brain": "usb:BBB",
            },
        ],
        "provenance": {"identity": USER, "bus_map": USER},
    }
    saved = await client.put(
        _url(project, f"entities/{robot}/config"),
        headers={**alice_headers, "If-Match": "0"},
        json={"config": body},
    )
    assert saved.status_code == 200, saved.text
    url = _url(project, f"robots/{robot}/topology")
    read = await client.get(url, headers=alice_headers)
    assert read.status_code == 200, read.text
    assert len([e for e in read.json()["data"]["edges"] if e["target"] == part]) == 2
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=bob_headers)).status_code == 404
