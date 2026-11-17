"""SOLUSDEV-326 — hardware its onboarder has not added to the workspace graph (docs/api/hardware.md
§1a). It carries `attrs.in_graph: false` and `attrs.onboarded_by` on the robot, the manual parts it
contains, the topology nodes derived for it and their config nodes, and only its onboarder sees
it. `PUT …/hardware/entities/{id}/graph` (one `set_in_graph` service) adds it to the graph, or takes
it out, together; a teammate sees it only once it is added."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools import ToolRegistry
from solus_api.agent.tools.finding_tools import get_run_handler
from solus_api.agent.tools.solus_tools import register_solus_write_tools
from solus_api.agent.tools.tool import ToolException
from solus_api.core.errors import APIError
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.graph.edges import write_edge
from solus_api.graph.read_scope import GraphReadScope, bind_scope
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.detect import ConfirmIn, ProposalOut, confirm_proposal
from solus_api.hardware.links import LinkSuggestion, LinkTier, persist_suggestions
from solus_api.hardware.operations import HardwareEntityCreate, ReviewedHardwareOperations
from solus_api.hardware.store import attach_existing_parts, put_entity_config
from solus_api.hardware.topology import MARKER, MEMBERSHIP, derived_nodes, sync_topology
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.capture import Capture
from solus_api.livebench.runs.models import RunManifest, RunSummary
from solus_api.models import (
    DataEvent,
    Domain,
    GraphEdge,
    GraphEntity,
    HardwareSuggestion,
    JobStatus,
    Membership,
    Role,
    SolusEntry,
    SourcingRequest,
    User,
    utcnow,
)
from solus_api.services import environment_divergence
from solus_api.services.environment_spec import SPEC_SUBSECTION, recompute_environment_spec
from solus_api.services.physical_robots import PhysicalRobotService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_hardware_attach import _connector_parts
from test_hardware_detect import DEVICE_REF, _six_servo_proposal, _wire_proposal
from test_hardware_detect import detect_local as detect_local
from test_hardware_identity_list import USER, _brain

HIDDEN = {"in_graph": False}


class _Team:
    """Alice (the onboarder) and Bob (a member) in one collaborative team's project."""

    def __init__(self, project: str, team: str, alice: dict[str, Any], bob: dict[str, Any]):
        self.project, self.team, self.alice, self.bob = project, team, alice, bob

    @property
    def project_id(self) -> uuid.UUID:
        return uuid.UUID(self.project)

    @property
    def alice_id(self) -> uuid.UUID:
        return uuid.UUID(self.alice["id"])

    def url(self, *parts: str) -> str:
        return "/".join((f"/api/v1/projects/{self.project}", *parts))


async def _team(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> _Team:
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    return _Team(project["id"], team["id"], alice, bob)


async def _onboard(db: AsyncSession, team: _Team, *, in_graph: bool = False) -> Any:
    """A detected arm confirmed by its onboarder: a robot, two parts on one brain, configs."""
    body = ConfirmIn.model_validate(
        {
            "target": {"kind": "new", "name": "Private arm"},
            "accepted": [{"row_id": f"{DEVICE_REF}/1"}, {"row_id": f"{DEVICE_REF}/2"}],
            "start_session": False,
        }
    )
    result = await confirm_proposal(
        db,
        project_id=team.project_id,
        proposal=ProposalOut.model_validate(_wire_proposal()),
        body=body,
        created_by=team.alice_id,
        in_graph=in_graph,
        onboarded_by=team.alice_id,
    )
    await db.commit()
    return result


async def _config_nodes(db: AsyncSession, subjects: list[uuid.UUID]) -> list[GraphEntity]:
    nodes = await db.scalars(
        select(GraphEntity)
        .join(SolusEntry, SolusEntry.entity_id == GraphEntity.id)
        .where(SolusEntry.configured_entity_id.in_(subjects), SolusEntry.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    return list(nodes)


async def _fresh(db: AsyncSession, ids: list[uuid.UUID]) -> list[GraphEntity]:
    rows = await db.scalars(
        select(GraphEntity).where(GraphEntity.id.in_(ids)).execution_options(populate_existing=True)
    )
    return list(rows)


async def _config_entries(db: AsyncSession, subjects: list[uuid.UUID]) -> list[SolusEntry]:
    rows = await db.scalars(
        select(SolusEntry).where(
            SolusEntry.configured_entity_id.in_(subjects), SolusEntry.deleted_at.is_(None)
        )
    )
    return list(rows)


async def _solus_ids(client: AsyncClient, headers: dict[str, str], team: _Team) -> set[str]:
    response = await client.get(team.url("solus"), headers=headers)
    assert response.status_code == 200, response.text
    sections: dict[str, list[dict[str, Any]]] = response.json()["data"]["sections"]
    return {str(entry["id"]) for entries in sections.values() for entry in entries}


def _flags(row: GraphEntity) -> dict[str, Any]:
    return {key: row.attrs[key] for key in ("in_graph", "onboarded_by") if key in row.attrs}


ONLY_ONBOARDER = "Only the person who onboarded this hardware can take it out of the graph."
ADMIT_REFUSED = (
    "This wires hardware a teammate hasn't added to the graph yet. Ask them to add it to the "
    "graph first."
)


async def _onboarded(db: AsyncSession, entity_id: str, user_id: uuid.UUID) -> None:
    """What an onboarding tool records (P2): `user_id` onboarded this hardware, and the parts a
    robot was created with, in the graph."""
    rows = await db.scalars(
        select(GraphEntity)
        .where(
            (GraphEntity.id == uuid.UUID(entity_id))
            | (GraphEntity.attrs["robot_id"].astext == entity_id)
        )
        .execution_options(populate_existing=True)
    )
    for row in rows:
        row.attrs = {**row.attrs, "onboarded_by": str(user_id)}
    await db.commit()


# --------------------------------------------------------------------------- stamping


async def test_onboarding_stamps_the_robot_its_parts_brains_buses_and_config_nodes(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    stamp = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    robot_id = result.robot.id

    owned = await _fresh(db, [robot_id, *result.part_ids])
    nodes = (await derived_nodes(db, team.project_id, robot_id))[0]
    configs = await _config_nodes(db, [robot_id, *result.part_ids])
    assert {node.kind for node in nodes} == {"hardware_brain", "hardware_bus"}
    assert len(configs) == 3  # the robot's and each part's
    for row in [*owned, *nodes, *configs]:
        assert _flags(row) == stamp, (row.kind, row.name)

    # The creators' default is the graph, with no onboarder: nothing stamped at all.
    plain = await PhysicalRobotService(db).create(team.project_id, "Shared arm")
    assert _flags(plain) == {}
    with pytest.raises(ValueError, match="onboarder"):
        await PhysicalRobotService(db).create(team.project_id, "Orphan", in_graph=False)


async def test_a_node_another_robots_topology_reaches_carries_neither_robots_keys(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A derived node another robot's managed edge also reaches (one device bound to two robots)
    is shared topology, like a host brain: it never moves with either robot, and a sync clears
    the keys it was given before it was shared."""
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team, in_graph=True)
    robot = result.robot.id
    nodes = (await derived_nodes(db, team.project_id, robot))[0]
    (brain,) = [node for node in nodes if node.kind == "hardware_brain"]
    other = uuid.UUID(await _bobs_robot(client, team, bob_headers))
    await write_edge(
        db,
        project_id=team.project_id,
        src_id=other,
        dst_id=brain.id,
        relation_type=MEMBERSHIP,
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=None,
        attrs={"managed_by": MARKER, "robot_id": str(other)},
        managed_by=MARKER,
    )
    await db.commit()
    assert brain.id not in {
        node.id for node in (await derived_nodes(db, team.project_id, robot))[0]
    }

    assert (await _out(client, team, alice_headers, str(robot))).status_code == 200
    (brain,) = await _fresh(db, [brain.id])
    assert _flags(brain) == {}  # Bob's robot, in the graph, reaches it: shared, no keys
    hidden = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    bus = next(node for node in nodes if node.kind == "hardware_bus")
    assert _flags((await _fresh(db, [bus.id]))[0]) == hidden  # hers alone: moved with the robot
    brain.attrs = {**brain.attrs, **hidden}  # stamped while it was hers alone
    await db.commit()

    async def synced() -> dict[str, Any]:
        db.expire_all()  # visibility changed in other sessions
        await sync_topology(db, team.project_id, robot)
        await db.commit()
        return _flags((await _fresh(db, [brain.id]))[0])

    assert await synced() == {}
    # Reached only by robots out of the graph, it fails closed: never public.
    await _onboarded(db, str(other), uuid.UUID(team.bob["id"]))
    assert (await _out(client, team, bob_headers, str(other))).status_code == 200
    assert await synced() == hidden


async def test_the_reviewed_create_stamps_a_lone_part_and_its_config_node(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    operations = ReviewedHardwareOperations(db, team.project_id, team.alice_id)
    body = HardwareEntityCreate.model_validate(
        {
            "kind": "part",
            "name": "Loose IMU",
            "config": {
                "component": {"lifecycle": "received"},
                "provenance": {"component": {"by": "user"}},
            },
        }
    )
    created, _ = await operations.create(
        uuid.uuid4(), body, in_graph=False, onboarded_by=team.alice_id
    )
    part_id = uuid.UUID(str(created["entity"]["id"]))
    (part,) = await _fresh(db, [part_id])
    (node,) = await _config_nodes(db, [part_id])
    stamp = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    assert _flags(part) == _flags(node) == stamp
    assert created["entity"]["properties"]["in_graph"] is False

    robot, _ = await operations.create(
        uuid.uuid4(),
        HardwareEntityCreate.model_validate({"kind": "robot", "name": "Hidden rover"}),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    assert robot["entity"]["properties"]["onboarded_by"] == str(team.alice_id)


async def test_a_part_attached_to_a_robot_takes_the_robots_visibility(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A robot's manual parts share its visibility, whichever writer adds them: authored on it,
    attached from its onboarder's loose parts, or moved onto it."""
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    robot = str(result.robot.id)
    authored = await client.post(
        team.url("hardware", "robots", robot, "parts"),
        headers=alice_headers,
        json={"name": "Gripper"},
    )
    assert authored.status_code == 201, authored.text
    loose = await client.post(
        team.url("hardware", "entities"),
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"kind": "part", "name": "Wrist camera"},
    )
    assert loose.status_code == 201, loose.text
    loose_id = loose.json()["data"]["entity"]["id"]
    await _onboarded(db, loose_id, team.alice_id)
    attached = await client.post(
        team.url("hardware", "robots", robot, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [loose_id]},
    )
    assert attached.status_code == 200, attached.text
    ids = [uuid.UUID(authored.json()["data"]["entity"]["id"]), uuid.UUID(loose_id)]
    stamp = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    for row in [*await _fresh(db, ids), *await _config_nodes(db, ids)]:
        assert _flags(row) == stamp, row.name

    # Moved off the robot, a part keeps what it had; moved onto a shared robot, it follows.
    shared = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "S"}
    )
    (camera,) = await _fresh(db, [uuid.UUID(loose_id)])
    moved = await client.patch(
        team.url("hardware", "parts", loose_id, "parent"),
        headers=alice_headers,
        json={
            "parent_id": shared.json()["data"]["id"],
            "expected_parent_id": robot,
            "version": camera.version,
        },
    )
    assert moved.status_code == 200, moved.text
    (camera,) = await _fresh(db, [uuid.UUID(loose_id)])
    assert _flags(camera) == {"onboarded_by": str(team.alice_id)}  # in the graph, still hers


# ------------------------------------------------------------------------ visibility


async def _ids(client: AsyncClient, headers: dict[str, str], url: str) -> set[str]:
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return {str(row["id"]) for row in response.json()["data"]}


async def test_a_teammate_sees_hidden_hardware_only_once_it_is_added(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    robot = str(result.robot.id)
    hardware = {robot, *(str(part) for part in result.part_ids)}
    reads = [
        team.url("hardware", "robots", robot, "topology"),
        team.url("hardware", "robots", robot, "config"),
        team.url("hardware", "entities", robot, "config"),
        team.url("hardware", "entities", str(result.part_ids[0]), "config"),
        team.url("entities", robot),
        team.url("entities", robot, "relations"),
    ]

    assert hardware <= await _ids(client, alice_headers, team.url("entities"))
    assert hardware - {robot} <= await _ids(client, alice_headers, team.url("hardware", "parts"))
    for url in reads:
        assert (await client.get(url, headers=alice_headers)).status_code == 200, url

    assert not hardware & await _ids(client, bob_headers, team.url("entities"))
    assert not hardware & await _ids(client, bob_headers, team.url("hardware", "parts"))
    relations = await _ids(client, bob_headers, team.url("relations"))
    alice_relations = await _ids(client, alice_headers, team.url("relations"))
    assert relations < alice_relations  # the hidden robot's edges go with it
    for url in reads:
        assert (await client.get(url, headers=bob_headers)).status_code == 404, url
    # Its config entries stay in the onboarder's `.solus`, and no other member can address one.
    configs = {str(row.id) for row in await _config_entries(db, [result.robot.id])}
    assert configs <= await _solus_ids(client, alice_headers, team)
    assert not configs & await _solus_ids(client, bob_headers, team)
    (entry,) = configs
    gone = await client.delete(team.url("solus", "entries", entry), headers=bob_headers)
    assert gone.status_code == 404, gone.text
    # A teammate cannot write to it either: same 404 as a robot that does not exist.
    for method, url, body in (
        ("post", team.url("hardware", "robots", robot, "parts"), {"name": "Sneaky"}),
        ("patch", team.url("entities", robot), {"name": "Renamed"}),
    ):
        headers = {**bob_headers, "If-Match": "1"}
        response = await client.request(method.upper(), url, headers=headers, json=body)
        assert response.status_code == 404, (url, response.text)

    added = await client.put(
        team.url("hardware", "entities", robot, "graph"),
        headers=alice_headers,
        json={"in_graph": True},
    )
    assert added.status_code == 200, added.text
    assert added.json()["data"]["in_graph"] is True
    assert added.json()["data"]["updated"] >= 6  # robot, 2 parts, 3 config nodes, brain, bus

    assert hardware <= await _ids(client, bob_headers, team.url("entities"))
    assert await _ids(client, bob_headers, team.url("relations")) == alice_relations
    assert configs <= await _solus_ids(client, bob_headers, team)
    for url in reads:
        assert (await client.get(url, headers=bob_headers)).status_code == 200, url


async def test_a_lone_hidden_part_stays_out_of_a_teammates_unassigned_list(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    created, _ = await ReviewedHardwareOperations(db, team.project_id, team.alice_id).create(
        uuid.uuid4(),
        HardwareEntityCreate.model_validate({"kind": "part", "name": "Spare servo"}),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    await db.commit()
    part = str(created["entity"]["id"])
    for url in (
        team.url("hardware", "unassigned"),
        team.url("hardware", "parts") + "?ownership=unassigned",
    ):
        assert part in await _ids(client, alice_headers, url)
        assert part not in await _ids(client, bob_headers, url)

    response = await client.put(
        team.url("hardware", "entities", part, "graph"),
        headers=alice_headers,
        json={"in_graph": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["updated"] == 1  # a lone part with no config moves alone
    assert part in await _ids(client, bob_headers, team.url("hardware", "unassigned"))


async def test_device_suggestions_for_a_hidden_robot_reach_its_onboarder_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    match = ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=SourceRef(source_connector="bench", external_ref="usb:OTHER/1"),
        confidence=0.8,
        state=MatchState.MATCHED,
        evidence={"matched_on": "bus_enumeration"},
    )
    (row,) = await persist_suggestions(
        db,
        team.project_id,
        [
            LinkSuggestion(
                subject_ref="usb:OTHER",
                subject_kind="device",
                candidate_robot_id=result.robot.id,
                confidence=0.8,
                tier=LinkTier.HIGH,
                evidence=[match],
                reason="bus enumeration matched a free slot",
            )
        ],
    )
    await db.commit()
    suggestions = team.url("hardware", "suggestions")
    assert await _ids(client, alice_headers, suggestions) == {str(row.id)}
    assert await _ids(client, bob_headers, suggestions) == set()
    for verb in ("accept", "reject"):
        decided = await client.post(f"{suggestions}/{row.id}/{verb}", headers=bob_headers)
        assert decided.status_code == 404, decided.text
    still = await db.scalar(
        select(HardwareSuggestion.status)
        .where(HardwareSuggestion.id == row.id)
        .execution_options(populate_existing=True)
    )
    assert still is not None and still.value == "pending"


# ------------------------------------------------------------------- the route itself


async def test_the_graph_route_is_member_only_verified_strict_and_project_scoped(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    unverified_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    robot = str(result.robot.id)
    url = team.url("hardware", "entities", robot, "graph")
    body = {"in_graph": True}

    assert (await client.put(url, json=body)).status_code == 401
    unverified = await me(client, unverified_headers)
    db.add(
        Membership(
            team_id=uuid.UUID(team.team), user_id=uuid.UUID(unverified["id"]), role=Role.MEMBER
        )
    )
    await db.commit()
    assert (await client.put(url, json=body, headers=unverified_headers)).status_code == 403
    for bad in ({"in_graph": "yes"}, {"in_graph": True, "onboarded_by": "x"}, {}):
        assert (await client.put(url, json=bad, headers=alice_headers)).status_code == 422
    # A teammate cannot reach hardware they cannot see: the same 404 as an unknown id.
    assert (await client.put(url, json=body, headers=bob_headers)).status_code == 404
    unknown = team.url("hardware", "entities", str(uuid.uuid4()), "graph")
    assert (await client.put(unknown, json=body, headers=alice_headers)).status_code == 404
    # A robot's part moves with its robot, never alone.
    part = team.url("hardware", "entities", str(result.part_ids[0]), "graph")
    refused = await client.put(part, json=body, headers=alice_headers)
    assert refused.status_code == 409, refused.text

    # Cross-team: Bob's own team's project cannot name Alice's robot, and he is no member of
    # Alice's second project at all.
    bob_team = await create_team(client, bob_headers, name="Bob's team")
    bob_project = await create_project(client, bob_headers, bob_team["id"])
    theirs = f"/api/v1/projects/{bob_project['id']}/hardware/entities/{robot}/graph"
    assert (await client.put(theirs, json=body, headers=bob_headers)).status_code == 404
    other = await create_project(client, alice_headers, team.team, name="Second")
    elsewhere = f"/api/v1/projects/{other['id']}/hardware/entities/{robot}/graph"
    assert (await client.put(elsewhere, json=body, headers=alice_headers)).status_code == 404

    # A viewer of the project may read but never flip.
    viewer_team = await create_team(client, alice_headers, name="Viewers")
    viewer_project = await create_project(client, alice_headers, viewer_team["id"])
    db.add(  # Bob is at his plan's team limit; the role is what this checks, not the invite
        Membership(
            team_id=uuid.UUID(viewer_team["id"]),
            user_id=uuid.UUID(team.bob["id"]),
            role=Role.VIEWER,
        )
    )
    await db.commit()
    shared = await client.post(
        f"/api/v1/projects/{viewer_project['id']}/entities",
        headers=alice_headers,
        json={"type": "physical_robot", "name": "Shared"},
    )
    viewer_url = (
        f"/api/v1/projects/{viewer_project['id']}/hardware/entities/"
        f"{shared.json()['data']['id']}/graph"
    )
    denied = await client.put(viewer_url, json={"in_graph": False}, headers=bob_headers)
    assert denied.status_code == 403, denied.text


async def test_flipping_emits_one_event_and_one_graph_change_per_real_change(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    for user in await db.scalars(select(User)):
        user.data_collection_consent = True
    await db.commit()
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "A"}
    )
    robot = created.json()["data"]["id"]
    frames: list[dict[str, Any]] = []

    async def publish(project: uuid.UUID, frame: dict[str, Any]) -> None:
        assert str(project) == team.project
        frames.append(frame)

    monkeypatch.setattr(app.state.graph_hub, "publish", publish)
    url = team.url("hardware", "entities", robot, "graph")

    async def flip(headers: dict[str, str], in_graph: bool) -> dict[str, Any]:
        response = await client.put(url, json={"in_graph": in_graph}, headers=headers)
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()["data"]
        return data

    # Only its onboarder takes hardware out of the graph: nobody onboarded this robot, so it stays.
    for headers in (alice_headers, bob_headers):
        refused = await client.put(url, json={"in_graph": False}, headers=headers)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["message"] == ONLY_ONBOARDER
    assert (await flip(alice_headers, True))["updated"] == 0  # already in: no change
    await _onboarded(db, robot, team.alice_id)
    refused = await client.put(url, json={"in_graph": False}, headers=bob_headers)
    assert refused.status_code == 403, refused.text

    taken = await flip(alice_headers, False)
    assert taken["entity"]["properties"] == {
        **taken["entity"]["properties"],
        "in_graph": False,
        "onboarded_by": team.alice["id"],
    }
    assert (await client.get(team.url("entities", robot), headers=bob_headers)).status_code == 404
    assert (await flip(alice_headers, False))["updated"] == 0  # already out: no change
    assert (await flip(alice_headers, True))["updated"] == 1

    assert [frame["counts"]["entities_updated"] for frame in frames] == [1, 1]
    events = list(
        await db.scalars(
            select(DataEvent)
            .where(DataEvent.event_type.like("hardware.%_graph"))
            .order_by(DataEvent.created_at)
        )
    )
    assert [(event.event_type, event.user_id) for event in events] == [
        ("hardware.removed_from_graph", team.alice_id),
        ("hardware.added_to_graph", team.alice_id),
    ]
    assert events[0].payload == {"entity_id": robot, "kind": "robot", "count": 1}
    assert "A" not in json.dumps([event.payload for event in events])


async def test_generic_entity_routes_cannot_set_visibility(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"),
        headers=alice_headers,
        json={"type": "physical_robot", "name": "A", "in_graph": False},
    )
    assert created.status_code == 422, created.text
    robot = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "A"}
    )
    renamed = await client.patch(
        team.url("entities", robot.json()["data"]["id"]),
        headers={**alice_headers, "If-Match": "1"},
        json={"name": "B", "in_graph": False, "onboarded_by": team.bob["id"]},
    )
    assert renamed.status_code == 422, renamed.text
    hardware = await client.post(
        team.url("hardware", "entities"),
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"kind": "part", "name": "P", "in_graph": False},
    )
    assert hardware.status_code == 422, hardware.text


# ------------------------------------------------- hidden hardware named in a request


async def test_a_teammate_cannot_attach_another_members_hidden_part(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Naming a hidden part in an attach body is the same 404 as an unknown id (never a 409 that
    names it): a lone part and a part of a hidden robot keep their keys and their robot."""
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    lone, _ = await ReviewedHardwareOperations(db, team.project_id, team.alice_id).create(
        uuid.uuid4(),
        HardwareEntityCreate.model_validate({"kind": "part", "name": "Spare servo"}),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    await db.commit()
    mine = await client.post(
        team.url("entities"), headers=bob_headers, json={"type": "physical_robot", "name": "B"}
    )
    assert mine.status_code == 201, mine.text
    attach = team.url("hardware", "robots", mine.json()["data"]["id"], "parts", "attach")
    for part_id in (uuid.UUID(str(lone["entity"]["id"])), result.part_ids[0]):
        (part,) = await _fresh(db, [part_id])
        name, before = part.name, dict(part.attrs)
        body = {"entity_ids": [str(part_id)]}
        response = await client.post(attach, headers=bob_headers, json=body)
        assert response.status_code == 404, response.text
        assert name not in response.text
        (part,) = await _fresh(db, [part_id])
        assert part.attrs == before


def _wiring(robot: str, part: str, binding: str) -> dict[str, Any]:
    """One brain on `robot`, with `part` at address 1 of its bus."""
    return {
        "schema_version": 2,
        "entity_id": robot,
        "identity": [_brain(binding, "bus-driver", kind="host")],
        "bus_map": [{"protocol": "bus-driver", "address": "1", "part_entity_id": part}],
        "provenance": {"identity": USER, "bus_map": USER},
    }


async def _bobs_robot(client: AsyncClient, team: _Team, bob_headers: dict[str, str]) -> str:
    created = await client.post(
        team.url("entities"), headers=bob_headers, json={"type": "physical_robot", "name": "B"}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["data"]["id"])


async def _loose(client: AsyncClient, team: _Team, headers: dict[str, str], name: str) -> str:
    created = await client.post(
        team.url("hardware", "entities"),
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"kind": "part", "name": name},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["data"]["entity"]["id"])


async def _wire(
    client: AsyncClient,
    team: _Team,
    headers: dict[str, str],
    robot: str,
    part: str | None,
    binding: str,
) -> None:
    """`robot`'s config: one brain, with `part` at address 1 (None: nothing wired)."""
    url = team.url("hardware", "entities", robot, "config")
    version = (await client.get(url, headers=headers)).json()["data"]["version"]
    config = (
        _wiring(robot, part, binding)
        if part
        else {
            "schema_version": 2,
            "entity_id": robot,
            "identity": [_brain(binding, "bus-driver", kind="host")],
            "provenance": {"identity": USER},
        }
    )
    response = await client.put(
        url, headers={**headers, "If-Match": str(version)}, json={"config": config}
    )
    assert response.status_code == 200, response.text


async def _out(client: AsyncClient, team: _Team, headers: dict[str, str], entity: str) -> Any:
    url = team.url("hardware", "entities", entity, "graph")
    return await client.put(url, headers=headers, json={"in_graph": False})


async def test_hardware_stays_in_the_graph_while_wiring_someone_else_sees_names_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A config names only parts everyone who can see it can see (§1a). Hardware whose part a
    config someone else can see names stays in the graph (409, saying what to do) until that
    wiring is gone; a robot's own config moves with it, and a refusal never names a robot the
    caller cannot see."""
    team = await _team(client, alice_headers, bob_headers)
    part = await _loose(client, team, alice_headers, "Shared encoder")
    await _onboarded(db, part, team.alice_id)
    robot = await _bobs_robot(client, team, bob_headers)
    await _wire(client, team, bob_headers, robot, part, "CCC")
    refused = await _out(client, team, alice_headers, part)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["message"] == (
        "Shared encoder is wired into B, which is in the graph, so it has to stay in the graph. "
        "Remove it from B's wiring first."
    )
    assert (await client.get(team.url("entities", part), headers=bob_headers)).status_code == 200
    await _wire(client, team, bob_headers, robot, None, "CCC")
    assert (await _out(client, team, alice_headers, part)).status_code == 200

    # Her robot's own part is wired into Bob's robot as well: the robot stays in with it.
    arm = await _onboard(db, team, in_graph=True)
    await _wire(client, team, bob_headers, robot, str(arm.part_ids[0]), "CCC")
    refused = await _out(client, team, alice_headers, str(arm.robot.id))
    assert refused.status_code == 409, refused.text
    assert "is wired into B, which is in the graph" in refused.json()["error"]["message"]

    # Bob's part wired into Alice's robot that is out of the graph: he may not hide it, and the
    # refusal says whose it is without naming her robot.
    gear = await _loose(client, team, bob_headers, "Gearbox")
    await _onboarded(db, gear, uuid.UUID(team.bob["id"]))
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    assert (await _out(client, team, alice_headers, hers)).status_code == 200
    await _wire(client, team, alice_headers, hers, gear, "DDD")
    refused = await _out(client, team, bob_headers, gear)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["message"] == (
        "Gearbox is wired into a teammate's hardware that isn't in the graph yet. Ask them to "
        "remove it from their wiring, or to add their hardware to the graph, first."
    )


async def test_a_part_others_see_is_never_hidden_by_putting_it_on_a_hidden_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A part put on a robot takes its visibility; on a robot out of the graph that hides it, which
    only the part's own onboarder may do, and never while a config someone else can see names it.
    Either route refuses with a 409 saying what to do and changes nothing."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    assert (await _out(client, team, alice_headers, hers)).status_code == 200
    shared = await _loose(client, team, alice_headers, "Team servo")  # nobody onboarded it
    own = await _loose(client, team, alice_headers, "Her servo")
    await _onboarded(db, own, team.alice_id)
    wired = await _loose(client, team, alice_headers, "Her encoder")
    await _onboarded(db, wired, team.alice_id)
    await _wire(client, team, bob_headers, await _bobs_robot(client, team, bob_headers), wired, "C")

    async def attach(part: str) -> Any:
        url = team.url("hardware", "robots", hers, "parts", "attach")
        return await client.post(url, headers=alice_headers, json={"entity_ids": [part]})

    async def move(part: str) -> Any:
        (row,) = await _fresh(db, [uuid.UUID(part)])
        body = {"parent_id": hers, "expected_parent_id": None, "version": row.version}
        url = team.url("hardware", "parts", part, "parent")
        return await client.patch(url, headers=alice_headers, json=body)

    for put in (attach, move):
        refused = await put(shared)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["message"] == (
            "Team servo is in the graph, so your team can see it. Add Hers to the graph first, "
            "then put Team servo on it."
        )
        refused = await put(wired)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["message"] == (
            "Her encoder is wired into B, which is in the graph, so it has to stay in the graph. "
            "Remove it from B's wiring first."
        )
    for part in (shared, wired):
        assert (
            await client.get(team.url("entities", part), headers=bob_headers)
        ).status_code == 200
        (row,) = await _fresh(db, [uuid.UUID(part)])
        assert "robot_id" not in row.attrs
    assert (await attach(own)).status_code == 200
    assert (await client.get(team.url("entities", own), headers=bob_headers)).status_code == 404


async def test_wiring_a_part_out_of_the_graph_into_a_robot_in_the_graph_adds_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A config names only parts everyone who can see it can see (§1a): Alice wiring her part out
    of the graph into Bob's robot adds the part to the graph (one `hardware.added_to_graph`), so
    every read of that config, his included, names only what he sees. Until then Bob cannot name
    it: the 404 of an unknown part, nothing written."""
    team = await _team(client, alice_headers, bob_headers)
    for user in await db.scalars(select(User)):
        user.data_collection_consent = True
    await db.commit()
    part = await _loose(client, team, alice_headers, "Shared encoder")
    await _onboarded(db, part, team.alice_id)
    assert (await _out(client, team, alice_headers, part)).status_code == 200
    robot = await _bobs_robot(client, team, bob_headers)
    config = team.url("hardware", "entities", robot, "config")
    named = await client.put(
        config,
        headers={**bob_headers, "If-Match": "0"},
        json={"config": _wiring(robot, part, "CCC")},
    )
    assert named.status_code == 404, named.text
    assert await _config_entries(db, [uuid.UUID(robot)]) == []

    await _wire(client, team, alice_headers, robot, part, "CCC")
    (row,) = await _fresh(db, [uuid.UUID(part)])
    assert _flags(row) == {"onboarded_by": str(team.alice_id)}
    assert (await client.get(team.url("entities", part), headers=bob_headers)).status_code == 200
    reads = (
        config,
        team.url("hardware", "robots", robot, "config"),
        team.url("hardware", "robots", robot, "topology"),
    )
    for url in reads:
        theirs = await client.get(url, headers=bob_headers)
        assert theirs.status_code == 200 and part in theirs.text, url
    events = await db.scalars(
        select(DataEvent).where(DataEvent.event_type == "hardware.added_to_graph")
    )
    assert [
        (event.user_id, event.payload["entity_id"], event.payload["kind"]) for event in events
    ] == [(team.alice_id, part, "part")]


async def test_a_config_out_of_the_graph_never_names_another_members_hidden_part(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Reachable only in the system view (a person's view is the 404 of an unknown part first):
    Alice's robot out of the graph cannot name Bob's part out of the graph; nothing is written."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    assert (await _out(client, team, alice_headers, hers)).status_code == 200
    gear = await _loose(client, team, bob_headers, "Gearbox")
    await _onboarded(db, gear, uuid.UUID(team.bob["id"]))
    assert (await _out(client, team, bob_headers, gear)).status_code == 200

    (subject,) = await _fresh(db, [uuid.UUID(hers)])
    config = EntityHardwareConfig.model_validate(_wiring(hers, gear, "DDD"))
    with pytest.raises(APIError) as refused:
        await put_entity_config(
            db, team.project_id, subject, config, expected_version=0, created_by=None
        )
    assert refused.value.status_code == 409
    assert refused.value.message == ADMIT_REFUSED
    await db.rollback()
    assert await _config_entries(db, [uuid.UUID(hers)]) == []


async def test_only_a_parts_onboarder_adds_it_to_the_graph_by_wiring_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Whatever the read scope, wiring a part out of the graph into hardware in the graph adds it
    only when its own onboarder writes: the system view or a teammate is a 409, nothing written."""
    team = await _team(client, alice_headers, bob_headers)
    part = await _loose(client, team, alice_headers, "Shared encoder")
    await _onboarded(db, part, team.alice_id)
    assert (await _out(client, team, alice_headers, part)).status_code == 200
    robot = await _bobs_robot(client, team, bob_headers)
    config = EntityHardwareConfig.model_validate(_wiring(robot, part, "CCC"))
    for writer in (None, uuid.UUID(team.bob["id"])):
        (subject,) = await _fresh(db, [uuid.UUID(robot)])
        with pytest.raises(APIError) as refused:
            await put_entity_config(
                db, team.project_id, subject, config, expected_version=0, created_by=writer
            )
        assert refused.value.status_code == 409
        assert refused.value.message == ADMIT_REFUSED
        await db.rollback()
    (row,) = await _fresh(db, [uuid.UUID(part)])
    assert row.attrs["in_graph"] is False
    assert await _config_entries(db, [uuid.UUID(robot)]) == []


async def test_adding_a_robot_adds_the_parts_its_config_wires(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Out of the graph Alice wires her loose part into her robot; adding the robot to the graph
    adds that part too (its own `hardware.added_to_graph`), so Bob reads the config whole."""
    team = await _team(client, alice_headers, bob_headers)
    for user in await db.scalars(select(User)):
        user.data_collection_consent = True
    await db.commit()
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    assert (await _out(client, team, alice_headers, hers)).status_code == 200
    part = await _loose(client, team, alice_headers, "Her encoder")
    await _onboarded(db, part, team.alice_id)
    assert (await _out(client, team, alice_headers, part)).status_code == 200
    await _wire(client, team, alice_headers, hers, part, "EEE")
    assert (await client.get(team.url("entities", part), headers=bob_headers)).status_code == 404

    async def flags() -> dict[uuid.UUID, dict[str, Any]]:
        rows = await db.scalars(
            select(GraphEntity)
            .where(GraphEntity.project_id == team.project_id)
            .execution_options(populate_existing=True)
        )
        return {row.id: _flags(row) for row in rows}

    before = await flags()
    url = team.url("hardware", "entities", hers, "graph")
    added = await client.put(url, headers=alice_headers, json={"in_graph": True})
    assert added.status_code == 200, added.text
    after = await flags()
    changed = sum(before.get(key) != value for key, value in after.items())
    assert added.json()["data"]["updated"] == changed  # the wired part and its rows included
    (row,) = await _fresh(db, [uuid.UUID(part)])
    assert _flags(row) == {"onboarded_by": str(team.alice_id)}
    assert (await client.get(team.url("entities", part), headers=bob_headers)).status_code == 200
    theirs = await client.get(team.url("hardware", "entities", hers, "config"), headers=bob_headers)
    assert theirs.status_code == 200 and part in theirs.text
    events = await db.scalars(
        select(DataEvent).where(DataEvent.event_type == "hardware.added_to_graph")
    )
    assert sorted((event.payload["kind"], event.payload["entity_id"]) for event in events) == [
        ("part", part),
        ("robot", hers),
    ]


async def test_putting_a_teammates_part_on_your_robot_never_makes_it_yours(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A part put on a robot in the graph keeps its own onboarder, so moving or attaching a
    teammate's part (or one nobody onboarded) never lets the robot's onboarder take it out of
    the graph, on its own or with the robot: 403 and 409, saying what to do."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    gear = await _loose(client, team, bob_headers, "Gearbox")
    await _onboarded(db, gear, uuid.UUID(team.bob["id"]))
    shared = await _loose(client, team, bob_headers, "Team servo")  # nobody onboarded it

    async def parent(part: str, robot: str | None, expected: str | None) -> None:
        (row,) = await _fresh(db, [uuid.UUID(part)])
        body = {"parent_id": robot, "expected_parent_id": expected, "version": row.version}
        url = team.url("hardware", "parts", part, "parent")
        moved = await client.patch(url, headers=alice_headers, json=body)
        assert moved.status_code == 200, moved.text

    await parent(gear, hers, None)
    (row,) = await _fresh(db, [uuid.UUID(gear)])
    assert _flags(row) == {"onboarded_by": team.bob["id"]}
    await parent(gear, None, hers)
    refused = await _out(client, team, alice_headers, gear)
    assert refused.status_code == 403, refused.text

    for part, name in ((gear, "Gearbox"), (shared, "Team servo")):
        url = team.url("hardware", "robots", hers, "parts", "attach")
        attached = await client.post(url, headers=alice_headers, json={"entity_ids": [part]})
        assert attached.status_code == 200, attached.text
        before = _flags((await _fresh(db, [uuid.UUID(part)]))[0])
        graph = team.url("hardware", "entities", hers, "graph")
        readded = await client.put(graph, headers=alice_headers, json={"in_graph": True})
        assert readded.status_code == 200, readded.text  # an add never rewrites a part's onboarder
        assert _flags((await _fresh(db, [uuid.UUID(part)]))[0]) == before
        refused = await _out(client, team, alice_headers, hers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["message"] == (
            f"{name} on Hers isn't yours to take out of the graph. Take it off Hers first."
        )
        assert (
            await client.get(team.url("entities", part), headers=bob_headers)
        ).status_code == 200
        await parent(part, None, hers)
    assert (await _out(client, team, alice_headers, hers)).status_code == 200


async def test_hardware_joining_the_graph_brings_what_its_config_wires(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Out of the graph, Alice's board's own config wires her sensor. When the board joins the
    graph — wired into Bob's robot, or attached to a robot in it — the sensor joins too, so no
    config a teammate reads names hardware they cannot see."""
    team = await _team(client, alice_headers, bob_headers)

    async def hidden_pair(board_name: str, binding: str) -> tuple[str, str]:
        board = await _loose(client, team, alice_headers, board_name)
        sensor = await _loose(client, team, alice_headers, f"{board_name} sensor")
        for part in (board, sensor):
            await _onboarded(db, part, team.alice_id)
            assert (await _out(client, team, alice_headers, part)).status_code == 200
        await _wire(client, team, alice_headers, board, sensor, binding)
        return board, sensor

    board, sensor = await hidden_pair("Board", "PPP")
    robot = await _bobs_robot(client, team, bob_headers)
    await _wire(client, team, alice_headers, robot, board, "CCC")
    theirs = await client.get(
        team.url("hardware", "entities", board, "config"), headers=bob_headers
    )
    assert theirs.status_code == 200 and sensor in theirs.text
    for part in (board, sensor):
        assert (
            await client.get(team.url("entities", part), headers=bob_headers)
        ).status_code == 200

    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    second, inner = await hidden_pair("Second board", "QQQ")
    url = team.url("hardware", "robots", hers, "parts", "attach")
    attached = await client.post(url, headers=alice_headers, json={"entity_ids": [second]})
    assert attached.status_code == 200, attached.text
    for part in (second, inner):
        assert (
            await client.get(team.url("entities", part), headers=bob_headers)
        ).status_code == 200


async def test_sol_never_wires_a_part_out_of_the_graph_by_config_field(
    client: AsyncClient,
    app: FastAPI,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Red team (CLAUDE.md §7): a config-field write that names a part out of the graph would add
    it to the graph, which the field's card does not say. SOL's tool refuses it, at preview and
    at write, and nothing is parked or written; the asker adds the part to the graph first."""
    team = await _team(client, alice_headers, bob_headers)
    robot = await _bobs_robot(client, team, bob_headers)
    visible = await _loose(client, team, bob_headers, "Encoder")
    await _wire(client, team, bob_headers, robot, visible, "CCC")
    part = await _loose(client, team, alice_headers, "Her sensor")
    await _onboarded(db, part, team.alice_id)
    assert (await _out(client, team, alice_headers, part)).status_code == 200
    registry = ToolRegistry()
    register_solus_write_tools(
        registry,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        store=app.state.artifact_store,
        project_id=team.project_id,
        user_id=team.alice_id,
    )
    tool: Any = next(
        t for t in registry.tools() if t.descriptor.name == "set_hardware_config_field"
    )
    args = {"robot_entity_id": robot, "path": "bus_map.0.part_entity_id", "value": part}
    with bind_scope(GraphReadScope(team.project_id, viewer_id=team.alice_id)):
        with pytest.raises(ToolException, match="isn't in the workspace graph"):
            await tool.preview(args)
    (row,) = await _fresh(db, [uuid.UUID(part)])
    assert row.attrs["in_graph"] is False


async def test_adding_a_robot_nobody_onboarded_keeps_its_parts_onboarders(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Adding a robot to the graph stamps the robot, never the onboarder of a part on it."""
    team = await _team(client, alice_headers, bob_headers)
    robot = await _bobs_robot(client, team, bob_headers)  # nobody onboarded it
    gear = await _loose(client, team, alice_headers, "Gearbox")
    await _onboarded(db, gear, team.alice_id)
    url = team.url("hardware", "robots", robot, "parts", "attach")
    assert (
        await client.post(url, headers=bob_headers, json={"entity_ids": [gear]})
    ).status_code == 200
    graph = team.url("hardware", "entities", robot, "graph")
    assert (
        await client.put(graph, headers=bob_headers, json={"in_graph": True})
    ).status_code == 200
    assert _flags((await _fresh(db, [uuid.UUID(gear)]))[0]) == {"onboarded_by": str(team.alice_id)}


async def test_the_shared_environment_spec_follows_hardware_out_of_the_graph(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Taking a robot out of the graph recomputes the project's environment spec with the same
    commit, so its config's requirements leave the spec every member reads."""
    team = await _team(client, alice_headers, bob_headers)
    arm = await _onboard(db, team, in_graph=True)
    (node,) = await _config_nodes(db, [arm.robot.id])
    requirement = GraphEntity(
        project_id=team.project_id,
        kind="python_requirement",
        domain=Domain.CODE,
        origin="connector",
        name="armlib",
        attrs={"name": "armlib", "ecosystem": "python"},
    )
    db.add(requirement)
    await db.flush()
    await write_edge(
        db,
        project_id=team.project_id,
        src_id=node.id,
        dst_id=requirement.id,
        relation_type="requires",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=None,
    )
    await recompute_environment_spec(db, team.project_id)
    await db.commit()

    async def packages() -> set[str]:
        entry = await db.scalar(
            select(SolusEntry)
            .where(
                SolusEntry.project_id == team.project_id,
                SolusEntry.subsection == SPEC_SUBSECTION,
                SolusEntry.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        assert entry is not None and entry.payload is not None
        return {package["name"] for package in entry.payload["packages"]}

    assert "armlib" in await packages()
    assert (await _out(client, team, alice_headers, str(arm.robot.id))).status_code == 200
    assert "armlib" not in await packages()
    graph = team.url("hardware", "entities", str(arm.robot.id), "graph")
    assert (
        await client.put(graph, headers=alice_headers, json={"in_graph": True})
    ).status_code == 200
    assert "armlib" in await packages()


async def test_sols_config_field_write_refuses_a_part_that_left_the_graph_after_its_preview(
    client: AsyncClient,
    app: FastAPI,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """The refusal holds at write time too: a part that was in the graph when the card was
    previewed, and that its onboarder took out before the approval, is never wired in."""
    team = await _team(client, alice_headers, bob_headers)
    robot = await _bobs_robot(client, team, bob_headers)
    await _wire(
        client, team, bob_headers, robot, await _loose(client, team, bob_headers, "E"), "CCC"
    )
    part = await _loose(client, team, alice_headers, "Her sensor")
    await _onboarded(db, part, team.alice_id)
    registry = ToolRegistry()
    register_solus_write_tools(
        registry,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        store=app.state.artifact_store,
        project_id=team.project_id,
        user_id=team.alice_id,
    )
    tool: Any = next(
        t for t in registry.tools() if t.descriptor.name == "set_hardware_config_field"
    )
    args = {"robot_entity_id": robot, "path": "bus_map.0.part_entity_id", "value": part}
    with bind_scope(GraphReadScope(team.project_id, viewer_id=team.alice_id)):
        await tool.preview(args)
        assert (await _out(client, team, alice_headers, part)).status_code == 200
        with pytest.raises(ToolException, match="isn't in the workspace graph"):
            await tool.invoke(args)
    (row,) = await _fresh(db, [uuid.UUID(part)])
    assert row.attrs["in_graph"] is False


async def test_adding_a_robot_never_makes_another_members_hidden_part_visible(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A part of Alice's out of the graph on her robot in the graph (old data, or a race) joins
    only when she adds the robot: Bob's add, otherwise a no-op, is a 409 naming nothing that
    changes nothing."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    part = await _loose(client, team, alice_headers, "Spare")
    await _onboarded(db, part, team.alice_id)
    url = team.url("hardware", "robots", hers, "parts", "attach")
    assert (
        await client.post(url, headers=alice_headers, json={"entity_ids": [part]})
    ).status_code == 200
    (row,) = await _fresh(db, [uuid.UUID(part)])
    hidden = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    row.attrs = {**row.attrs, **hidden}
    await db.commit()
    graph = team.url("hardware", "entities", hers, "graph")
    refused = await client.put(graph, headers=bob_headers, json={"in_graph": True})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["message"] == ADMIT_REFUSED
    assert _flags((await _fresh(db, [uuid.UUID(part)]))[0]) == hidden
    assert (
        await client.put(graph, headers=alice_headers, json={"in_graph": True})
    ).status_code == 200
    assert _flags((await _fresh(db, [uuid.UUID(part)]))[0]) == {"onboarded_by": str(team.alice_id)}


async def test_an_attach_onto_a_hidden_robot_is_all_or_nothing_and_moves_parts_together(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """One check for every part an attach puts on a robot out of the graph: one part that is not
    hers refuses the lot, and two of hers whose configs wire each other go out together."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    assert (await _out(client, team, alice_headers, hers)).status_code == 200
    mine, other = (
        await _loose(client, team, alice_headers, "Mine"),
        await _loose(client, team, alice_headers, "Other"),
    )
    theirs = await _loose(client, team, bob_headers, "Theirs")
    for part, user in (
        (mine, team.alice_id),
        (other, team.alice_id),
        (theirs, uuid.UUID(team.bob["id"])),
    ):
        await _onboarded(db, part, user)
    url = team.url("hardware", "robots", hers, "parts", "attach")
    refused = await client.post(url, headers=alice_headers, json={"entity_ids": [mine, theirs]})
    assert refused.status_code == 409, refused.text
    for part in (mine, theirs):
        (row,) = await _fresh(db, [uuid.UUID(part)])
        assert "robot_id" not in row.attrs and row.attrs.get("in_graph") is not False
    await _wire(client, team, alice_headers, mine, other, "AAA")
    await _wire(client, team, alice_headers, other, mine, "BBB")
    attached = await client.post(url, headers=alice_headers, json={"entity_ids": [mine, other]})
    assert attached.status_code == 200, attached.text
    for part in (mine, other):
        assert (
            await client.get(team.url("entities", part), headers=bob_headers)
        ).status_code == 404


async def test_an_attach_reads_the_robots_keys_under_the_lock(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A robot object read before its onboarder took it out of the graph never decides an
    attach: the keys are read again under the lock, so Bob's part is not put on a hidden robot."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "Hers"}
    )
    hers = str(created.json()["data"]["id"])
    await _onboarded(db, hers, team.alice_id)
    gear = await _loose(client, team, bob_headers, "Gearbox")
    await _onboarded(db, gear, uuid.UUID(team.bob["id"]))
    (stale,) = await _fresh(db, [uuid.UUID(hers)])  # read while it was in the graph
    assert (await _out(client, team, alice_headers, hers)).status_code == 200
    with pytest.raises(APIError) as refused:
        await attach_existing_parts(
            db, team.project_id, stale, entity_ids=[uuid.UUID(gear)], created_by=team.alice_id
        )
    assert refused.value.status_code == 409
    await db.rollback()
    (row,) = await _fresh(db, [uuid.UUID(gear)])
    assert _flags(row) == {"onboarded_by": team.bob["id"]} and "robot_id" not in row.attrs


async def test_a_failed_environment_recompute_never_fails_add_or_remove(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spec recompute is best-effort: if it fails, the hardware still leaves the graph."""

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("recompute exploded")

    monkeypatch.setattr(environment_divergence, "recompute_divergences", broken)
    team = await _team(client, alice_headers, bob_headers)
    arm = await _onboard(db, team, in_graph=True)
    assert (await _out(client, team, alice_headers, str(arm.robot.id))).status_code == 200
    (robot,) = await _fresh(db, [arm.robot.id])
    assert robot.attrs["in_graph"] is False


#: A sourcing candidate as the engine stores it (`sourcing/candidates.py`).
CANDIDATE = {
    "id": "00000000000000aa",
    "name": "Spare servo",
    "part_number": "SRV-1",
    "optimizes_for": "cost",
    "gives_up": "torque",
}


async def test_a_sourced_part_takes_its_hidden_robots_visibility(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A candidate Alice selects into her robot out of the graph is hers alone, like the robot,
    until she adds the robot."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "A"}
    )
    robot = str(created.json()["data"]["id"])
    await _onboarded(db, robot, team.alice_id)
    graph = team.url("hardware", "entities", robot, "graph")
    out = await client.put(graph, headers=alice_headers, json={"in_graph": False})
    assert out.status_code == 200, out.text
    request = SourcingRequest(
        project_id=team.project_id,
        created_by=team.alice_id,
        status=JobStatus.SUCCEEDED,
        candidates=[CANDIDATE],
    )
    db.add(request)
    await db.flush()
    request_id = str(request.id)
    await db.commit()
    selected = await client.post(
        team.url("sourcing", "requests", request_id, "select"),
        headers=alice_headers,
        json={"candidate_id": CANDIDATE["id"], "robot_entity_id": robot},
    )
    assert selected.status_code == 201, selected.text
    part = str(selected.json()["data"]["entity"]["id"])
    (row,) = await _fresh(db, [uuid.UUID(part)])
    assert _flags(row) == {"in_graph": False, "onboarded_by": str(team.alice_id)}

    async def seen(headers: dict[str, str]) -> tuple[int, bool, bool]:
        entity = await client.get(team.url("entities", part), headers=headers)
        listed = await _ids(client, headers, team.url("entities"))
        parts = await _ids(client, headers, team.url("hardware", "parts"))
        return entity.status_code, part in listed, part in parts

    assert await seen(alice_headers) == (200, True, True)
    assert await seen(bob_headers) == (404, False, False)
    added = await client.put(graph, headers=alice_headers, json={"in_graph": True})
    assert added.status_code == 200, added.text
    assert await seen(bob_headers) == (200, True, True)


async def test_a_device_proposal_never_names_a_robot_the_caller_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    detect_local: Any,
    db: AsyncSession,
) -> None:
    """The device on the wire matches Alice's hidden library arm: Bob's proposal carries no
    suggestion naming it, hers does (the suggestion row is shared; the response is per viewer)."""
    team = await _team(client, alice_headers, bob_headers)
    imported = await client.post(
        team.url("hardware", "library", "platforms", "so101-follower", "import"),
        headers=alice_headers,
        json={},
    )
    assert imported.status_code == 201, imported.text
    robot = str(imported.json()["data"]["robot"]["id"])
    await _onboarded(db, robot, team.alice_id)
    out = await client.put(
        team.url("hardware", "entities", robot, "graph"),
        headers=alice_headers,
        json={"in_graph": False},
    )
    assert out.status_code == 200, out.text
    detect_local.proposal = _six_servo_proposal()

    async def propose(headers: dict[str, str]) -> tuple[list[str], str]:
        url = team.url("hardware", "detected", DEVICE_REF, "propose")
        response = await client.post(url, headers=headers, json={})
        assert response.status_code == 200, response.text
        found = [str(row["candidate_robot_id"]) for row in response.json()["data"]["suggestions"]]
        return found, response.text

    found, text = await propose(bob_headers)
    assert found == [] and robot not in text
    assert (await propose(alice_headers))[0] == [robot]


async def test_a_cad_proposal_never_names_a_robot_the_caller_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A team-visible CAD part whose matched counterpart belongs to Alice's hidden robot: Bob's
    review proposes nothing, hers proposes her robot."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "A"}
    )
    robot = str(created.json()["data"]["id"])
    await _onboarded(db, robot, team.alice_id)
    cad, known = await _connector_parts(db, team.project, team.team, ["CAD grip", "Known grip"])
    attached = await client.post(
        team.url("hardware", "robots", robot, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [str(known)]},
    )
    assert attached.status_code == 200, attached.text
    out = await client.put(
        team.url("hardware", "entities", robot, "graph"),
        headers=alice_headers,
        json={"in_graph": False},
    )
    assert out.status_code == 200, out.text
    db.add(
        GraphEdge(
            project_id=team.project_id,
            src_id=cad,
            dst_id=known,
            relation_type="same_as",
            domain_pair="mechanical<->mechanical",
            origin="fingerprint",
            confidence=0.92,
            attrs={"matched": True, "canonical_id": str(uuid.uuid4())},
        )
    )
    await db.commit()
    url = team.url("hardware", "parts", str(cad), "suggestions")
    bob = await client.post(url, headers=bob_headers)
    assert bob.status_code == 200, bob.text
    assert bob.json()["data"] == [] and robot not in bob.text
    alice = await client.post(url, headers=alice_headers)
    assert alice.status_code == 200, alice.text
    assert [str(row["candidate_robot_id"]) for row in alice.json()["data"]] == [robot]


async def test_a_teammate_cannot_move_a_connector_part_off_a_hidden_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A connector's part never carries the keys, but the hidden robot that contains it is Alice's
    alone: Bob's parts list names no parent for it, and changing its parent is the 404 of an
    unknown part (never a 409 naming the robot) that leaves her robot's edge and binding be."""
    team = await _team(client, alice_headers, bob_headers)
    created = await client.post(
        team.url("entities"), headers=alice_headers, json={"type": "physical_robot", "name": "A"}
    )
    robot = str(created.json()["data"]["id"])
    await _onboarded(db, robot, team.alice_id)
    (cad,) = await _connector_parts(db, team.project, team.team, ["CAD grip"])
    attached = await client.post(
        team.url("hardware", "robots", robot, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [str(cad)]},
    )
    assert attached.status_code == 200, attached.text
    config = team.url("hardware", "entities", robot, "config")
    version = (await client.get(config, headers=alice_headers)).json()["data"]["version"]
    wired = await client.put(
        config,
        headers={**alice_headers, "If-Match": str(version)},
        json={"config": _wiring(robot, str(cad), "EEE")},
    )
    assert wired.status_code == 200, wired.text
    out = await client.put(
        team.url("hardware", "entities", robot, "graph"),
        headers=alice_headers,
        json={"in_graph": False},
    )
    assert out.status_code == 200, out.text

    async def listed(headers: dict[str, str]) -> tuple[Any, str]:
        response = await client.get(team.url("hardware", "parts"), headers=headers)
        assert response.status_code == 200, response.text
        rows = {str(row["id"]): row for row in response.json()["data"]}
        return rows[str(cad)]["parent_id"], response.text

    parent, text = await listed(bob_headers)
    assert parent is None and robot not in text
    assert (await listed(alice_headers))[0] == robot

    async def edges() -> set[tuple[str, Any]]:
        rows = await db.scalars(
            select(GraphEdge)
            .where(GraphEdge.dst_id == cad, GraphEdge.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
        return {(edge.relation_type, edge.attrs.get("enabled")) for edge in rows}

    before = await edges()
    assert {("contains", None), ("binds", True)} <= before
    (part,) = await _fresh(db, [cad])
    url = team.url("hardware", "parts", str(cad), "parent")
    for expected in (robot, None):  # the right parent, or a wrong guess: one answer
        body = {"parent_id": None, "expected_parent_id": expected, "version": part.version}
        response = await client.patch(url, headers=bob_headers, json=body)
        assert response.status_code == 404, response.text
        assert robot not in response.text
    assert await edges() == before
    assert (await _fresh(db, [cad]))[0].version == part.version


# ------------------------------------------------------------------ a hidden robot's runs


async def _hidden_run(
    db: AsyncSession, app: FastAPI, team: _Team, robot: uuid.UUID, *, final: bool
) -> RunSummary:
    """A bench run of `robot` that Alice recorded, saved as a capture saves it."""
    started = utcnow()
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=robot,
        name="Private sweep",
        origin="live",
        status="completed" if final else "running",
        started_at=started,
    )
    record = run_store.new_record(team.project_id, info, team.alice_id)
    db.add(record)
    await db.flush()
    manifest = RunManifest(robot_id=robot, started_at=started)
    await run_store.save(
        db, app.state.artifact_store, record, info, manifest, team.alice_id, final=final
    )
    return info


async def test_a_hidden_robots_runs_and_their_filings_reach_its_onboarder_only(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A bench run is seen by whoever sees its robot: its record, its `.solus` filing and SOL's
    `get_run`. A teammate's lists leave it out and every route naming it is 404 (writes too)
    until the robot is added to the graph; taking the robot out takes its runs with it."""
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    info = await _hidden_run(db, app, team, result.robot.id, final=True)
    run = str(info.id)
    filing = {
        str(entry.id)
        for entry in await db.scalars(
            select(SolusEntry).where(SolusEntry.artifact_id == info.artifact_id)
        )
    }
    assert len(filing) == 1
    runs = team.url("bench", "runs")
    manifest = str(info.artifact_id)  # the run's saved manifest, as an artifact

    async def sol(viewer: uuid.UUID) -> int:
        with bind_scope(GraphReadScope(team.project_id, viewer_id=viewer)):
            try:
                await get_run_handler(
                    {"run_id": run}, sessions=app.state.sessionmaker, project_id=team.project_id
                )
            except APIError as error:
                return error.status_code
        return 200

    async def view(headers: dict[str, str], viewer: uuid.UUID) -> dict[str, Any]:
        listed = await client.get(runs, headers=headers)
        assert listed.status_code == 200, listed.text

        async def status(method: str, path: str) -> int:
            return (await client.request(method, f"{runs}/{path}", headers=headers)).status_code

        params = {"q": "Private sweep", "scope": "solus"}
        found = await client.get(team.url("search"), headers=headers, params=params)
        assert found.status_code == 200, found.text
        return {
            "listed": run in {row["id"] for row in listed.json()["data"]["runs"]},
            "entity": run in await _ids(client, headers, team.url("entities") + "?type=bench_run"),
            "filed": bool(filing & await _solus_ids(client, headers, team)),
            "searched": bool(filing & {hit["id"] for hit in found.json()["data"]["solus"]}),
            "detail": await status("GET", run),
            "findings": await status("GET", f"{run}/findings"),
            "pin": await status("POST", f"{run}/pin"),
            "sol": await sol(viewer),
            "manifest": [
                (await client.get(team.url("artifacts", *path), headers=headers)).status_code
                for path in ((manifest,), (manifest, "content"))
            ],
        }

    seen = {
        "listed": True,
        "entity": True,
        "filed": True,
        "searched": True,
        "detail": 200,
        "findings": 200,
        "pin": 200,
        "sol": 200,
        "manifest": [200, 200],
    }
    unknown = {
        "listed": False,
        "entity": False,
        "filed": False,
        "searched": False,
        "detail": 404,
        "findings": 404,
        "pin": 404,
        "sol": 404,
        "manifest": [404, 404],
    }
    bob = uuid.UUID(team.bob["id"])
    assert await view(alice_headers, team.alice_id) == seen
    assert await view(bob_headers, bob) == unknown

    graph = team.url("hardware", "entities", str(result.robot.id), "graph")
    added = await client.put(graph, headers=alice_headers, json={"in_graph": True})
    assert added.status_code == 200, added.text
    assert await view(bob_headers, bob) == seen
    removed = await client.put(graph, headers=alice_headers, json={"in_graph": False})
    assert removed.status_code == 200, removed.text
    assert await view(bob_headers, bob) == unknown
    assert await view(alice_headers, team.alice_id) == seen


async def test_a_capture_keeps_its_runs_keys_in_any_view(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A capture's checkpoints run in the system view, whoever's request started it, and a
    checkpoint or the final save keeps the run (and its filing) with its robot's visibility."""
    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    info = await _hidden_run(db, app, team, result.robot.id, final=False)
    manifest = RunManifest(robot_id=result.robot.id, started_at=info.started_at)
    capture = Capture(team.project_id, team.alice_id, info, manifest, 100)
    app.state.bench_runs.active[info.id] = capture
    hidden = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    # The task copied a teammate's request scope before Alice took the robot out of the graph.
    with bind_scope(GraphReadScope(team.project_id, viewer_id=uuid.UUID(team.bob["id"]))):
        saved = await app.state.bench_runs.persist(capture, final=False)
        assert saved.status == "running"
        assert _flags((await _fresh(db, [info.id]))[0]) == hidden
        capture.info.status = "completed"
        saved = await app.state.bench_runs.persist(capture, final=True)
    assert saved.status == "completed" and saved.artifact_id is not None
    (record,) = await _fresh(db, [info.id])
    assert _flags(record) == hidden
    (document,) = await db.scalars(
        select(GraphEntity)
        .join(SolusEntry, SolusEntry.entity_id == GraphEntity.id)
        .where(SolusEntry.artifact_id == saved.artifact_id)
    )
    assert _flags(document) == hidden
