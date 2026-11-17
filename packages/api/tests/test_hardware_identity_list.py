"""SOLUSDEV-326 P1: a stored v2 config keeps a LIST of brains, keyed by brain.

`identity` lists the robot's brains (host / MCU / onboard), each with its binding, the brain it
is reached through and its driver; a bus row names its brain (`None` = the only one). An old
single-identity payload upgrades on every read, drivers still get one v1 document per brain
(`per_brain()`), and nothing that writes through the v1 adapter drops a brain.
"""

import json
import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from pydantic import ValidationError
from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    MAX_BRAINS,
    ConfigLayer,
    EntityHardwareConfig,
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    ProtocolBinding,
    ProvenanceRecord,
    _leaf_items,
    merge_layers,
)
from solus_api.hardware.detect import ProposalOut, bind_device
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import (
    attach_part,
    create_part,
    hand_over_brain,
    put_config,
    put_entity_config,
    read_entity_config,
)
from solus_api.hardware.topology import read_topology
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    Team,
    User,
)
from solus_api.services.solus_config import serialize_entry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ROBOT = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
PART = uuid.UUID("00000000-0000-4000-8000-0000000000a2")
USER = {"by": "user", "source": None}


def _legacy() -> dict[str, Any]:
    """A stored v2 payload from before SOLUSDEV-326: one identity, a top-level protocol."""
    return {
        "schema_version": 2,
        "entity_id": str(ROBOT),
        "identity": {"kind": "usb_serial", "binding": "AAA", "vid": 6790, "pid": 29987},
        "protocol": {"driver_id": "bus-driver", "params": {"baud": 115200}},
        "bus_map": [
            {"protocol": "bus-driver", "address": "1", "part_entity_id": str(PART), "model": "M1"}
        ],
        "disambiguated_by": None,
        "provenance": {
            "identity": {"by": "detected", "source": None},
            "protocol.driver_id": {"by": "repo", "source": "config:arm"},
            "protocol.params": {"by": "user", "source": None},
            "bus_map": {"by": "detected", "source": None},
        },
    }


def _brain(binding: str, driver: str, kind: str = "mcu") -> dict[str, Any]:
    return {
        "kind": kind,
        "binding": {"kind": "usb_serial", "binding": binding},
        "protocol": {"driver_id": driver, "params": {}},
    }


def _two_brains(
    entity: uuid.UUID, left: uuid.UUID | None = None, right: uuid.UUID | None = None
) -> dict[str, Any]:
    """Two MCUs on two USB cables; the same address on each is two endpoints."""
    return {
        "schema_version": 2,
        "entity_id": str(entity),
        "identity": [_brain("AAA", "left-driver"), _brain("BBB", "right-driver")],
        "bus_map": [
            {
                "protocol": "left-driver",
                "address": "1",
                "part_entity_id": str(left) if left else None,
                "brain": "usb:AAA",
            },
            {
                "protocol": "right-driver",
                "address": "1",
                "part_entity_id": str(right) if right else None,
                "brain": "usb:BBB",
            },
        ],
        "provenance": {"identity": USER, "bus_map": USER},
    }


# ----------------------------------------------------------------------------- the model


def test_old_single_identity_payload_upgrades_on_read_with_complete_provenance() -> None:
    config = EntityHardwareConfig.model_validate(_legacy())
    (brain,) = config.identity
    assert brain.kind == "host" and brain.via is None
    assert brain.binding is not None and brain.binding.device_ref == "usb:AAA"
    assert brain.protocol == ProtocolBinding(driver_id="bus-driver", params={"baud": 115200})
    assert brain.device_ref == "usb:AAA"
    dumped = config.model_dump(mode="json")
    assert "protocol" not in dumped and isinstance(dumped["identity"], list)
    assert EntityHardwareConfig.model_validate(dumped) == config
    expected = {
        "identity.0.kind": "detected",
        "identity.0.binding.kind": "detected",
        "identity.0.binding.binding": "detected",
        "identity.0.binding.vid": "detected",
        "identity.0.binding.pid": "detected",
        "identity.0.protocol.driver_id": "repo",
        "identity.0.protocol.params.baud": "user",
        "bus_map.0.address": "detected",
    }
    assert {path: config.provenance_of(path).by.value for path in expected} == expected
    assert config.provenance_of("identity.0.protocol.driver_id").source == "config:arm"
    values = {key: value for key, value in dumped.items() if key not in {"provenance"}}
    leaves = [
        path for path, _ in _leaf_items(values) if path not in {"schema_version", "entity_id"}
    ]
    assert all(config.provenance_of(path) for path in leaves)


def test_upgrade_keeps_an_unbound_driver_and_forgets_an_empty_identity() -> None:
    empty = EntityHardwareConfig.model_validate(
        {
            "schema_version": 2,
            "entity_id": str(ROBOT),
            "identity": None,
            "protocol": None,
            "provenance": {"identity": USER},
        }
    )
    assert empty.identity == []
    assert not any(path.startswith("identity") for path in empty.provenance)
    library = EntityHardwareConfig.model_validate(
        {
            "schema_version": 2,
            "entity_id": str(ROBOT),
            "identity": None,
            "protocol": {"driver_id": "kit-driver", "params": {"baud": 9600}},
            "provenance": {"protocol": {"by": "library", "source": "platform:kit"}},
        }
    )
    (brain,) = library.identity
    assert brain.binding is None and brain.device_ref is None
    assert brain.protocol is not None and brain.protocol.driver_id == "kit-driver"
    assert library.provenance_of("identity.0.kind") == ProvenanceRecord(
        by=FieldProvenance.LIBRARY, source="platform:kit"
    )


def test_upgrade_rewrites_leaf_records_and_gives_the_brain_kind_its_identity_record() -> None:
    legacy = _legacy()
    legacy["provenance"] = {
        "identity.kind": USER,
        "identity.binding": {"by": "detected", "source": None},
        "identity.vid": {"by": "detected", "source": None},
        "identity.pid": {"by": "detected", "source": None},
        "protocol.driver_id": {"by": "repo", "source": None},
        "protocol.params.baud": {"by": "repo", "source": None},
        "bus_map": {"by": "detected", "source": None},
    }
    config = EntityHardwareConfig.model_validate(legacy)
    assert config.provenance_of("identity.0.kind").by is FieldProvenance.USER
    assert config.provenance_of("identity.0.binding.binding").by is FieldProvenance.DETECTED
    assert config.provenance_of("identity.0.protocol.params.baud").by is FieldProvenance.REPO
    assert not {"identity.kind", "protocol.driver_id"} & set(config.provenance)


def test_a_list_identity_with_a_top_level_protocol_is_refused() -> None:
    document = _two_brains(ROBOT)
    document["protocol"] = {"driver_id": "left-driver", "params": {}}
    with pytest.raises(ValidationError, match="protocol"):
        EntityHardwareConfig.model_validate(document)


@pytest.mark.parametrize(
    "provenance",
    [
        [1],
        5,
        True,
        [[1, 2]],
        {1: USER},
        [["identity", USER], ["protocol", USER], ["bus_map", USER]],
    ],
)
def test_a_legacy_payload_with_unreadable_provenance_is_refused_never_crashes(
    provenance: object,
) -> None:
    """The upgrade sees raw request bodies before field validation: provenance it cannot read
    is left for validation to refuse (a 422), never a TypeError (a 500), never coerced."""
    legacy = _legacy()
    legacy["provenance"] = provenance
    with pytest.raises(ValidationError, match="provenance"):
        EntityHardwareConfig.model_validate(legacy)


def test_duplicate_address_on_two_brains_is_allowed_on_one_brain_refused() -> None:
    config = EntityHardwareConfig.model_validate(_two_brains(ROBOT))
    assert [row.brain for row in config.bus_map] == ["usb:AAA", "usb:BBB"]
    same_brain = _two_brains(ROBOT)
    same_brain["bus_map"][1].update(protocol="left-driver", brain="usb:AAA")
    with pytest.raises(ValidationError, match="duplicate bus endpoint"):
        EntityHardwareConfig.model_validate(same_brain)
    # On a one-brain config an implicit row and a row naming that brain are the same endpoint.
    single = _two_brains(ROBOT)
    single["identity"] = single["identity"][:1]
    single["bus_map"][1].update(protocol="left-driver", brain=None)
    single["bus_map"][0]["brain"] = "usb:AAA"
    with pytest.raises(ValidationError, match="duplicate bus endpoint"):
        EntityHardwareConfig.model_validate(single)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("implicit_row", "brain"),
        ("unknown_row_brain", "brain"),
        ("unknown_via", "via"),
        ("self_via", "via"),
        ("via_cycle", "through each other"),
        ("duplicate_brain", "duplicate brain"),
    ],
)
def test_several_brains_name_their_rows_and_reach_each_other_without_loops(
    change: str, message: str
) -> None:
    document = _two_brains(ROBOT)
    left, right = document["identity"]
    if change == "implicit_row":
        document["bus_map"][0]["brain"] = None
    elif change == "unknown_row_brain":
        document["bus_map"][0]["brain"] = "usb:ZZZ"
    elif change == "unknown_via":
        right["via"] = "usb:ZZZ"
    elif change == "self_via":
        right["via"] = "usb:BBB"
    elif change == "via_cycle":
        left["via"], right["via"] = "usb:BBB", "usb:AAA"
    else:
        right["binding"]["binding"] = "AAA"
    with pytest.raises(ValidationError, match=message):
        EntityHardwareConfig.model_validate(document)
    reached = _two_brains(ROBOT)
    reached["identity"][1]["via"] = "usb:AAA"
    assert EntityHardwareConfig.model_validate(reached).identity[1].via == "usb:AAA"


def test_the_identity_list_is_bounded() -> None:
    document = _two_brains(ROBOT)
    document["bus_map"] = []
    document["identity"] = [_brain(f"B{index}", "drv") for index in range(MAX_BRAINS + 1)]
    with pytest.raises(ValidationError):
        EntityHardwareConfig.model_validate(document)
    document["identity"] = document["identity"][:MAX_BRAINS]
    assert len(EntityHardwareConfig.model_validate(document).identity) == MAX_BRAINS


def test_merge_layers_merges_an_identity_only_into_the_same_device() -> None:
    """A later layer naming another device replaces the identity whole: the first device's
    vendor/product ids never leak onto the second."""
    first = {"identity": {"kind": "usb_serial", "binding": "AAA", "vid": 1, "pid": 2}}
    same = {"identity": {"kind": "usb_serial", "binding": "AAA", "vid": 1, "pid": 3}}
    other = {"identity": {"kind": "usb_serial", "binding": "BBB"}}
    merged = merge_layers(
        ROBOT,
        [
            ConfigLayer(by=FieldProvenance.REPO, document=first),
            ConfigLayer(by=FieldProvenance.DETECTED, document=same),
        ],
    )
    assert merged.identity is not None and (merged.identity.vid, merged.identity.pid) == (1, 3)
    replaced = merge_layers(
        ROBOT,
        [
            ConfigLayer(by=FieldProvenance.REPO, document=first),
            ConfigLayer(by=FieldProvenance.DETECTED, document=other),
        ],
    )
    assert replaced.identity is not None
    assert (replaced.identity.binding, replaced.identity.vid, replaced.identity.pid) == (
        "BBB",
        None,
        None,
    )


# ----------------------------------------------------------------------------- the store


async def _project_row(db: AsyncSession) -> Project:
    team = Team(name="Brains fixture")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="Brains fixture")
    db.add(project)
    await db.flush()
    return project


async def _robot(db: AsyncSession, project: Project, *names: str) -> tuple[GraphEntity, list[Any]]:
    robot = GraphEntity(
        project_id=project.id,
        kind="physical_robot",
        domain=Domain.PROJECT,
        origin="manual",
        name="Rover",
    )
    db.add(robot)
    await db.flush()
    parts = [
        await attach_part(
            db, project.id, robot, name=name, attrs={}, provenance=FieldProvenance.USER
        )
        for name in names
    ]
    for part in parts:
        await put_entity_config(
            db,
            project.id,
            part,
            EntityHardwareConfig.model_validate(
                {
                    "entity_id": str(part.id),
                    "component": {"telemetry": [{"name": f"{part.name}.position"}]},
                    "provenance": {"component": USER},
                }
            ),
            expected_version=0,
            created_by=None,
        )
    return robot, parts


async def _binds(db: AsyncSession, project: Project) -> set[str]:
    return set(
        await db.scalars(
            select(GraphEdge.attrs["device_ref"].astext).where(
                GraphEdge.project_id == project.id,
                GraphEdge.relation_type == "binds",
                GraphEdge.deleted_at.is_(None),
            )
        )
    )


async def test_two_mcus_on_two_usb_cables_under_one_robot(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (left, right) = await _robot(db, project, "left", "right")
    await put_entity_config(
        db,
        project.id,
        robot,
        EntityHardwareConfig.model_validate(_two_brains(robot.id, left.id, right.id)),
        expected_version=0,
        created_by=None,
    )
    await db.commit()

    runtime = await resolve_runtime_config(db, project.id, robot.id)
    left_doc, right_doc = runtime.per_brain()
    for doc, ref, driver, part in (
        (left_doc, "usb:AAA", "left-driver", left),
        (right_doc, "usb:BBB", "right-driver", right),
    ):
        assert doc.identity is not None and doc.identity.device_ref == ref
        assert doc.protocol is not None and doc.protocol.driver_id == driver
        assert [row.part_entity_id for row in doc.bus_map] == [part.id]
        assert set(doc.parts) == {str(part.id)}
        # The driver input is unchanged: one identity, bus rows without a brain.
        dumped = doc.model_dump(mode="json")
        assert "brain" not in json.dumps(dumped)
        assert HardwareConfig.model_validate(dumped).model_dump(mode="json") == dumped
    # The aggregate keeps every row with its brain; its identity is the first brain.
    assert runtime.identity is not None and runtime.identity.device_ref == "usb:AAA"
    assert [row.brain for row in runtime.bus_map] == ["usb:AAA", "usb:BBB"]
    assert set(runtime.parts) == {str(left.id), str(right.id)}

    assert await _binds(db, project) == {"usb:AAA", "usb:BBB", "usb:AAA/1", "usb:BBB/1"}
    topology = await read_topology(db, project.id, robot.id)
    assert sorted(node.name for node in topology.nodes if node.role == "brain") == [
        "usb:AAA",
        "usb:BBB",
    ]


async def test_one_brain_reads_exactly_as_before(db: AsyncSession) -> None:
    """A one-brain robot's per-brain document IS its aggregate (drivers, digests unchanged)."""
    project = await _project_row(db)
    robot, (part,) = await _robot(db, project, "joint")
    legacy = _legacy()
    legacy["entity_id"] = str(robot.id)
    legacy["bus_map"][0]["part_entity_id"] = str(part.id)
    await put_entity_config(
        db,
        project.id,
        robot,
        EntityHardwareConfig.model_validate(legacy),
        expected_version=0,
        created_by=None,
    )
    runtime = await resolve_runtime_config(db, project.id, robot.id)
    (only,) = runtime.per_brain()
    assert only.model_dump(mode="json") == runtime.model_dump(mode="json")
    assert runtime.provenance_of("protocol.driver_id").source == "config:arm"
    assert "brain" not in json.dumps(runtime.model_dump(mode="json"))


async def test_an_old_payload_upgrades_on_every_read_path(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = str((await create_project(client, alice_headers, team["id"]))["id"])
    robot = await _created(client, alice_headers, project, kind="robot", name="Rover")
    legacy = _legacy()
    legacy["entity_id"] = robot
    legacy["bus_map"][0]["part_entity_id"] = None
    url = _url(project, f"entities/{robot}/config")
    saved = await client.put(
        url, headers={**alice_headers, "If-Match": "0"}, json={"config": legacy}
    )
    assert saved.status_code == 200, saved.text
    # Pre-SOLUSDEV-326 rows hold the old shape verbatim; nothing rewrote them.
    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(robot))
    )
    assert entry is not None
    entry.payload = legacy
    await db.commit()

    read = (await client.get(url, headers=alice_headers)).json()["data"]
    (brain,) = read["config"]["identity"]
    assert brain["binding"]["binding"] == "AAA" and brain["protocol"]["driver_id"] == "bus-driver"
    assert "protocol" not in read["config"]
    assert serialize_entry(entry)["payload"]["identity"] == read["config"]["identity"]
    runtime = await client.get(_url(project, f"robots/{robot}/config"), headers=alice_headers)
    assert runtime.status_code == 200, runtime.text
    view = runtime.json()["data"]["config"]
    assert view["identity"]["binding"] == "AAA" and view["protocol"]["driver_id"] == "bus-driver"
    assert await _binds(db, await _project_by_id(db, project)) == {"usb:AAA"}
    # The v1 adapter's round trip of an unchanged robot writes nothing.
    version = entry.config_version
    robot_row = await db.get(GraphEntity, uuid.UUID(robot))
    assert robot_row is not None
    await put_config(
        db,
        uuid.UUID(project),
        robot_row,
        await resolve_runtime_config(db, uuid.UUID(project), robot_row.id),
        created_by=None,
    )
    await db.commit()
    await db.refresh(entry)
    assert entry.config_version == version and entry.payload == legacy


async def test_put_config_never_drops_a_second_identity(db: AsyncSession) -> None:
    project = await _project_row(db)
    robot, (left, right) = await _robot(db, project, "left", "right")
    entry = await put_entity_config(
        db,
        project.id,
        robot,
        EntityHardwareConfig.model_validate(_two_brains(robot.id, left.id, right.id)),
        expected_version=0,
        created_by=None,
    )
    _, before = await read_entity_config(db, project.id, robot.id)
    assert before is not None
    await create_part(
        db,
        project.id,
        robot,
        name="camera",
        specs={},
        lifecycle=LifecycleState.PLANNED,
        created_by=None,
    )
    _, after = await read_entity_config(db, project.id, robot.id)
    assert after is not None
    assert after.identity == before.identity and after.bus_map == before.bus_map
    assert entry.config_version == 1
    # Unbinding the first brain through v1 would orphan its rows: refused, nothing dropped.
    runtime = await resolve_runtime_config(db, project.id, robot.id)
    with pytest.raises(APIError) as refused:
        await put_config(
            db,
            project.id,
            robot,
            runtime.model_copy(update={"identity": None}),
            created_by=None,
        )
    assert refused.value.code == "config_upgrade_required"


async def test_binding_a_new_device_adds_a_brain_instead_of_refusing(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    project = await _project_row(db)
    robot, (left,) = await _robot(db, project, "left")
    single = _two_brains(robot.id, left.id)
    single["identity"] = single["identity"][:1]
    single["bus_map"] = [{**single["bus_map"][0], "brain": None}]
    await put_entity_config(
        db,
        project.id,
        robot,
        EntityHardwareConfig.model_validate(single),
        expected_version=0,
        created_by=None,
    )
    proposal = _bus_proposal("BBB", "right-driver")
    await bind_device(db, project.id, robot, proposal, created_by=user)
    await bind_device(db, project.id, robot, proposal, created_by=user)  # again: no third brain
    await db.commit()

    _, stored = await read_entity_config(db, project.id, robot.id)
    assert stored is not None
    assert [brain.device_ref for brain in stored.identity] == ["usb:AAA", "usb:BBB"]
    protocols = [brain.protocol.driver_id if brain.protocol else None for brain in stored.identity]
    assert protocols == ["left-driver", "right-driver"]
    rows = {(row.brain, row.address): row.part_entity_id for row in stored.bus_map}
    # The first brain's implicit row names it once a second brain joins.
    assert rows == {("usb:AAA", "1"): left.id, ("usb:BBB", "1"): None}
    assert await _binds(db, project) >= {"usb:AAA", "usb:BBB", "usb:AAA/1"}


async def test_a_lone_parts_device_is_handed_to_a_robot_in_one_transaction(
    db: AsyncSession,
) -> None:
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    lone = GraphEntity(
        project_id=project.id, kind="part", domain=Domain.PROJECT, origin="manual", name="Board"
    )
    db.add(lone)
    await db.flush()
    await put_entity_config(
        db,
        project.id,
        lone,
        EntityHardwareConfig.model_validate(
            {
                "entity_id": str(lone.id),
                "identity": [_brain("LONE", "line-stream")],
                "component": {"telemetry": [{"name": "temperature"}]},
                "provenance": {"identity": USER, "component": USER},
            }
        ),
        expected_version=0,
        created_by=None,
    )
    await db.commit()
    claim = EntityHardwareConfig.model_validate(
        {
            "entity_id": str(robot.id),
            "identity": [_brain("LONE", "line-stream")],
            "provenance": {"identity": USER},
        }
    )
    # One config per device project-wide: the robot cannot take a bound device by itself.
    project_id, robot_id, lone_id = project.id, robot.id, lone.id
    with pytest.raises(APIError) as conflict:
        async with db.begin_nested():
            await put_entity_config(
                db, project_id, robot, claim, expected_version=0, created_by=None
            )
    assert conflict.value.code == "binding_conflict"

    source, target = await db.get(GraphEntity, lone_id), await db.get(GraphEntity, robot_id)
    assert source is not None and target is not None
    await hand_over_brain(
        db, project_id, device_ref="usb:LONE", source=source, target=target, created_by=None
    )
    await db.commit()
    _, part_config = await read_entity_config(db, project_id, lone_id)
    _, robot_config = await read_entity_config(db, project_id, robot_id)
    assert part_config is not None and part_config.identity == []
    assert part_config.component is not None and part_config.component.telemetry
    assert robot_config is not None
    assert [brain.device_ref for brain in robot_config.identity] == ["usb:LONE"]
    assert robot_config.identity[0].kind == "mcu"
    assert robot_config.provenance_of("identity.0.protocol.driver_id").by is FieldProvenance.USER
    owners = set(
        await db.scalars(
            select(SolusEntry.configured_entity_id)
            .join(GraphEdge, GraphEdge.src_id == SolusEntry.entity_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == "binds",
                GraphEdge.deleted_at.is_(None),
                GraphEdge.attrs["device_ref"].astext == "usb:LONE",
            )
        )
    )
    assert owners == {robot_id}


async def test_a_hand_over_the_robot_cannot_take_says_why(db: AsyncSession) -> None:
    """A result that does not validate (a 17th brain) is a 422 naming why, not the 409 that
    asks to bind the robot's unbound brain first."""
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    lone = GraphEntity(
        project_id=project.id, kind="part", domain=Domain.PROJECT, origin="manual", name="Board"
    )
    db.add(lone)
    await db.flush()
    board = {"entity_id": str(lone.id), "identity": [_brain("LONE", "line-stream")]}
    brains = [_brain(f"B{index}", "drv") for index in range(MAX_BRAINS)]
    full = {"entity_id": str(robot.id), "identity": brains}
    for subject, document in ((lone, board), (robot, full)):
        config = EntityHardwareConfig.model_validate({**document, "provenance": {"identity": USER}})
        await put_entity_config(
            db, project.id, subject, config, expected_version=0, created_by=None
        )
    with pytest.raises(APIError) as refused:
        await hand_over_brain(
            db, project.id, device_ref="usb:LONE", source=lone, target=robot, created_by=None
        )
    assert (refused.value.status_code, refused.value.code) == (422, "validation_error")
    assert f"at most {MAX_BRAINS}" in refused.value.message


# ----------------------------------------------------------------------------- the routes


def _url(project: str, suffix: str) -> str:
    return f"/api/v1/projects/{project}/hardware/{suffix}"


async def _created(client: AsyncClient, headers: dict[str, str], project: str, **body: Any) -> str:
    response = await client.post(
        _url(project, "entities"),
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["entity"]["id"])


async def _project_by_id(db: AsyncSession, project: str) -> Project:
    row = await db.get(Project, uuid.UUID(project))
    assert row is not None
    return row


def _bus_proposal(binding: str, driver: str) -> ProposalOut:
    ref = f"usb:{binding}"
    return ProposalOut.model_validate(
        {
            "device_ref": ref,
            "identity": {"kind": "usb_serial", "binding": binding},
            "level": "protocol",
            "summary": "Fixture bus",
            "driver_id": driver,
            "params": {},
            "rows": [
                {
                    "id": f"{ref}/1",
                    "subject": "fixture at 1",
                    "address": "1",
                    "model": None,
                    "proposed_function": None,
                    "confidence": 0.9,
                    "evidence": [],
                    "provenance": "bus",
                }
            ],
            "disambiguation": None,
            "confidence": 0.9,
        }
    )


async def test_brain_list_config_routes_refuse_anonymous_callers_and_other_teams(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = str((await create_project(client, alice_headers, team["id"]))["id"])
    robot = await _created(client, alice_headers, project, kind="robot", name="Rover")
    url = _url(project, f"entities/{robot}/config")
    body = {"config": _two_brains(uuid.UUID(robot))}
    await me(client, bob_headers)
    for headers, status in (({}, 401), (bob_headers, 404)):
        put = await client.put(url, headers={**headers, "If-Match": "0"}, json=body)
        assert put.status_code == status, put.text
        assert (await client.get(url, headers=headers)).status_code == status
        legacy = await client.get(_url(project, f"robots/{robot}/config"), headers=headers)
        assert legacy.status_code == status, legacy.text
    assert (
        await db.scalar(
            select(SolusEntry.id).where(SolusEntry.configured_entity_id == uuid.UUID(robot))
        )
        is None
    )
    saved = await client.put(url, headers={**alice_headers, "If-Match": "0"}, json=body)
    assert saved.status_code == 200, saved.text
    read = (await client.get(url, headers=alice_headers)).json()["data"]["config"]
    assert [brain["binding"]["binding"] for brain in read["identity"]] == ["AAA", "BBB"]
    assert [row["brain"] for row in read["bus_map"]] == ["usb:AAA", "usb:BBB"]


@pytest.mark.parametrize("provenance", [5, [[1, {"by": "user"}]]])
async def test_a_legacy_body_with_unreadable_provenance_is_a_422_on_both_write_routes(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    provenance: object,
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = str((await create_project(client, alice_headers, team["id"]))["id"])
    robot = await _created(client, alice_headers, project, kind="robot", name="Rover")
    entries = select(SolusEntry.id).where(SolusEntry.project_id == uuid.UUID(project))
    before = (await db.scalars(entries)).all()
    legacy = {"identity": {"kind": "usb_serial", "binding": "AAA"}, "provenance": provenance}
    put = await client.put(
        _url(project, f"entities/{robot}/config"),
        headers={**alice_headers, "If-Match": "0"},
        json={"config": {"schema_version": 2, "entity_id": robot, **legacy}},
    )
    post = await client.post(
        _url(project, "entities"),
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"kind": "part", "name": "Arm", "config": legacy},
    )
    for response in (put, post):
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"
    assert (await db.scalars(entries)).all() == before
