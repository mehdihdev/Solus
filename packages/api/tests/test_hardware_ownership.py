"""Entity-owned configuration survives assignment; provider facts stay provider-owned."""

import uuid
from typing import Any, Literal

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.graph.edges import write_edge
from solus_api.hardware.operations import HardwareEntityCreate, ReviewedHardwareOperations
from solus_api.hardware.ownership import list_parts
from solus_api.models import Domain, GraphEntity, SolusEntry
from solus_api.services.physical_robots import PhysicalRobotService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_in_graph import _team


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    return str((await create_project(client, headers, team["id"]))["id"])


def _url(project: str, suffix: str) -> str:
    return f"/api/v1/projects/{project}/hardware/{suffix}"


async def _create(
    client: AsyncClient, headers: dict[str, str], project: str, **body: Any
) -> dict[str, Any]:
    response = await client.post(
        _url(project, "entities"),
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def _config(entity_id: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "entity_id": entity_id,
        "component": {
            "calibration": {"mode": "degrees", "values": {"offset": 17}},
            "limits": {"values": {"min": -90, "max": 90}},
            "lifecycle": "received",
        },
        "provenance": {"component": {"by": "user"}},
    }


async def test_standalone_part_needs_no_robot_or_transport_and_read_does_not_create_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    created = await _create(client, alice_headers, project, kind="part", name=" Wrist joint ")
    entity = created["entity"]
    assert entity["name"] == "Wrist joint"
    assert created["parent_id"] is None
    assert created["config_entry_id"] is None
    before = await db.scalar(select(func.count()).select_from(SolusEntry))
    for _ in range(2):
        response = await client.get(
            _url(project, f"entities/{entity['id']}/config"), headers=alice_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "entity_id": entity["id"],
            "entry_id": None,
            "version": 0,
            "config": None,
        }
    assert await db.scalar(select(func.count()).select_from(SolusEntry)) == before
    robots = await db.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == uuid.UUID(project), GraphEntity.kind == "physical_robot")
    )
    assert robots == 0
    listed = await client.get(_url(project, "parts?ownership=unassigned"), headers=alice_headers)
    assert [row["id"] for row in listed.json()["data"]] == [entity["id"]]


async def test_assignment_detachment_and_robot_removal_preserve_part_config(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project = await _project(client, alice_headers)
    part = await _create(client, alice_headers, project, kind="part", name="Wrist joint")
    first = await _create(client, alice_headers, project, kind="robot", name="Arm one")
    second = await _create(client, alice_headers, project, kind="robot", name="Arm two")
    part_id = part["entity"]["id"]
    saved = await client.put(
        _url(project, f"entities/{part_id}/config"),
        headers={**alice_headers, "If-Match": "0"},
        json={"config": _config(part_id)},
    )
    assert saved.status_code == 200, saved.text
    expected = saved.json()["data"]
    parent_id = None
    version = part["ownership_version"]
    for robot in (first, second, None):
        wanted = robot["entity"]["id"] if robot else None
        assigned = await client.patch(
            _url(project, f"parts/{part_id}/parent"),
            headers=alice_headers,
            json={
                "parent_id": wanted,
                "expected_parent_id": parent_id,
                "version": version,
            },
        )
        assert assigned.status_code == 200, assigned.text
        version = assigned.json()["data"]["ownership_version"]
        parent_id = assigned.json()["data"]["parent_id"]
        fetched = await client.get(
            _url(project, f"entities/{part_id}/config"), headers=alice_headers
        )
        assert fetched.json()["data"] == expected


async def test_a_robot_root_is_the_only_parent(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """SOLUSDEV-326: the robot contains the part directly; a retired category node's id is no
    parent (404)."""
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Arm"))["entity"]
    created = await _create(
        client,
        alice_headers,
        project,
        kind="part",
        name="Wrist joint",
        parent_id=robot["id"],
    )
    part = created["entity"]
    assert created["parent_id"] == robot["id"]
    assert part["properties"] == {"robot_id": robot["id"]}  # no category stored
    legacy = GraphEntity(
        project_id=uuid.UUID(project),
        kind="robot_category",
        domain=Domain.PROJECT,
        origin="manual",
        name="Sensors",
        attrs={"robot_id": robot["id"], "category": "sensors"},
    )
    db.add(legacy)
    await db.commit()
    parent_url = _url(project, f"parts/{part['id']}/parent")
    moved = await client.patch(
        parent_url,
        headers=alice_headers,
        json={
            "parent_id": str(legacy.id),
            "expected_parent_id": robot["id"],
            "version": created["ownership_version"],
        },
    )
    assert moved.status_code == 404, moved.text
    detached = await client.patch(
        parent_url,
        headers=alice_headers,
        json={
            "parent_id": None,
            "expected_parent_id": robot["id"],
            "version": created["ownership_version"],
        },
    )
    assert detached.status_code == 200, detached.text
    assert detached.json()["data"]["parent_id"] is None
    assert "robot_id" not in detached.json()["data"]["entity"]["properties"]


async def test_changed_write_routes_refuse_anonymous_callers_and_other_teams(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """SOLUSDEV-326 changed these bodies: no token is 401, another team's member is 404, and
    neither writes anything."""
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Arm"))["entity"]
    created = await _create(client, alice_headers, project, kind="part", name="Joint")
    part = created["entity"]
    calls = [
        ("POST", "entities", {"kind": "part", "name": "Wrist"}),
        (
            "PATCH",
            f"parts/{part['id']}/parent",
            {
                "parent_id": robot["id"],
                "expected_parent_id": None,
                "version": created["ownership_version"],
            },
        ),
        ("POST", f"robots/{robot['id']}/parts", {"name": "Elbow"}),
        ("POST", f"robots/{robot['id']}/parts/attach", {"entity_ids": [part["id"]]}),
    ]
    await me(client, bob_headers)
    for method, suffix, body in calls:
        key = {"Idempotency-Key": str(uuid.uuid4())}
        anonymous = await client.request(method, _url(project, suffix), headers=key, json=body)
        assert anonymous.status_code == 401, (suffix, anonymous.text)
        stranger = await client.request(
            method, _url(project, suffix), headers={**bob_headers, **key}, json=body
        )
        assert stranger.status_code == 404, (suffix, stranger.text)
    listed = await client.get(_url(project, "parts?ownership=unassigned"), headers=alice_headers)
    assert [row["id"] for row in listed.json()["data"]] == [part["id"]]


async def test_stale_configuration_and_parent_writes_are_conflicts(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project = await _project(client, alice_headers)
    part = await _create(client, alice_headers, project, kind="part", name="Joint")
    robot = await _create(client, alice_headers, project, kind="robot", name="Arm")
    part_id = part["entity"]["id"]
    config_url = _url(project, f"entities/{part_id}/config")
    body = {"config": _config(part_id)}
    assert (
        await client.put(config_url, headers={**alice_headers, "If-Match": "0"}, json=body)
    ).status_code == 200
    stale = await client.put(config_url, headers={**alice_headers, "If-Match": "0"}, json=body)
    assert stale.status_code == 409
    parent_body = {
        "parent_id": robot["entity"]["id"],
        "expected_parent_id": None,
        "version": part["ownership_version"],
    }
    parent_url = _url(project, f"parts/{part_id}/parent")
    assert (
        await client.patch(parent_url, headers=alice_headers, json=parent_body)
    ).status_code == 200
    assert (
        await client.patch(parent_url, headers=alice_headers, json=parent_body)
    ).status_code == 409


async def test_cross_project_entity_config_and_parent_are_not_visible(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project = await _project(client, alice_headers)
    other = await _project(client, bob_headers)
    part = await _create(client, alice_headers, project, kind="part", name="Joint")
    part_id = part["entity"]["id"]
    for suffix in (f"entities/{part_id}/config", "parts?ownership=unassigned"):
        assert (await client.get(_url(project, suffix), headers=bob_headers)).status_code == 404
    assert (
        await client.get(_url(other, f"entities/{part_id}/config"), headers=bob_headers)
    ).status_code == 404
    foreign_robot = await _create(client, bob_headers, other, kind="robot", name="Other arm")
    response = await client.patch(
        _url(project, f"parts/{part_id}/parent"),
        headers=alice_headers,
        json={
            "parent_id": foreign_robot["entity"]["id"],
            "expected_parent_id": None,
            "version": part["ownership_version"],
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize("name", [None, "", "  ", 42])
async def test_creation_requires_user_name(
    client: AsyncClient, alice_headers: dict[str, str], name: Any
) -> None:
    project = await _project(client, alice_headers)
    response = await client.post(
        _url(project, "entities"),
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"kind": "part", "name": name},
    )
    assert response.status_code == 422


async def test_creation_retry_returns_the_same_entity_and_rejects_changed_review(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    url = _url(project, "entities")
    body = {"kind": "part", "name": "Joint"}
    first = await client.post(url, headers=headers, json=body)
    assert first.status_code == 201, first.text
    again = await client.post(url, headers=headers, json=body)
    assert again.status_code == 201, again.text
    assert again.json()["data"] == first.json()["data"]
    changed = await client.post(url, headers=headers, json={**body, "name": "Different joint"})
    assert changed.status_code == 409
    count = await db.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == uuid.UUID(project), GraphEntity.kind == "part")
    )
    assert count == 1


async def test_unassigned_unifies_manual_and_connector_parts(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from test_hardware_attach import _attach_project, _connector_parts

    project, team = await _attach_project(client, alice_headers)
    manual = await _create(client, alice_headers, project, kind="part", name="Manual sensor")
    connector = await _connector_parts(db, project, team, ["Connector sensor"])
    response = await client.get(_url(project, "parts?ownership=unassigned"), headers=alice_headers)
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()["data"]} == {
        manual["entity"]["id"],
        str(connector[0]),
    }


# ------------------------------------------- SOLUSDEV-326 P2: the parts list as a service


async def test_the_parts_list_service_pairs_each_part_with_its_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """`ownership.list_parts`, which the route and SOL both read: newest first, each part with
    the robot that owns it, a page at a time; `unassigned` is the parts no robot owns."""
    team = await _team(client, alice_headers, bob_headers)
    robot = (await _create(client, alice_headers, team.project, kind="robot", name="Arm"))["entity"]
    held = await _create(
        client, alice_headers, team.project, kind="part", name="Wrist", parent_id=robot["id"]
    )
    spare = await _create(client, alice_headers, team.project, kind="part", name="Spare")
    newest_first = [(spare["entity"]["id"], None), (held["entity"]["id"], robot["id"])]

    async def listed(
        ownership: Literal["unassigned", "all"], limit: int = 50, cursor: str | None = None
    ) -> tuple[list[tuple[str, str | None]], str | None]:
        rows, meta = await list_parts(
            db, team.project_id, team.alice_id, ownership=ownership, limit=limit, cursor=cursor
        )
        pairs = [(str(part.id), str(parent) if parent else None) for part, parent in rows]
        return pairs, meta["next_cursor"]

    assert await listed("all") == (newest_first, None)
    assert await listed("unassigned") == (newest_first[:1], None)
    first, cursor = await listed("all", limit=1)
    assert first == newest_first[:1] and cursor is not None
    assert await listed("all", limit=1, cursor=cursor) == (newest_first[1:], None)


async def test_the_parts_list_service_leaves_out_what_its_reader_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Bob never lists Alice's part she has not added to the graph, and a part he can see that
    her hidden robot holds (it never took her keys) has no parent he can read (§1a)."""
    team = await _team(client, alice_headers, bob_headers)
    created, _ = await ReviewedHardwareOperations(db, team.project_id, team.alice_id).create(
        uuid.uuid4(),
        HardwareEntityCreate.model_validate({"kind": "part", "name": "Spare servo"}),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    robot = await PhysicalRobotService(db).create(
        team.project_id, "Private arm", in_graph=False, onboarded_by=team.alice_id
    )
    shared = GraphEntity(
        project_id=team.project_id,
        kind="part",
        domain=Domain.PROJECT,
        origin="manual",
        name="Bracket",
    )
    db.add(shared)
    await db.flush()
    await write_edge(
        db,
        project_id=team.project_id,
        src_id=robot.id,
        dst_id=shared.id,
        relation_type="contains",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=None,
    )
    await db.commit()
    spare = uuid.UUID(str(created["entity"]["id"]))

    async def listed(user: uuid.UUID) -> set[tuple[uuid.UUID, uuid.UUID | None]]:
        rows, _ = await list_parts(
            db, team.project_id, user, ownership="all", limit=50, cursor=None
        )
        return {(part.id, parent) for part, parent in rows}

    assert await listed(uuid.UUID(team.bob["id"])) == {(shared.id, None)}
    assert await listed(team.alice_id) == {(shared.id, robot.id), (spare, None)}


async def test_a_creation_key_minted_before_the_category_went_still_replays(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """SOLUSDEV-326 P2 retired the body's `category`; the replay digest still covers the
    `category: null` a body without one carried, so such a key replays instead of a 409."""
    team = await _team(client, alice_headers, bob_headers)
    ledger = ReviewedHardwareOperations(db, team.project_id, team.alice_id)
    key = uuid.uuid4()
    before = {"kind": "part", "name": "Joint", "parent_id": None, "category": None, "config": None}
    _, digest = await ledger.replay(key, "entity.create", before)
    saved = ledger.record(key, "entity.create", digest, {"entity": {"id": "saved"}})
    await db.commit()

    response, replayed = await ledger.create(
        key, HardwareEntityCreate.model_validate({"kind": "part", "name": "Joint"})
    )

    assert replayed and response == saved
