"""Entity-owned configuration survives assignment; provider facts stay provider-owned."""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import GraphEntity, SolusEntry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


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
                "category": "actuators",
            },
        )
        assert assigned.status_code == 200, assigned.text
        version = assigned.json()["data"]["ownership_version"]
        parent_id = assigned.json()["data"]["parent_id"]
        fetched = await client.get(
            _url(project, f"entities/{part_id}/config"), headers=alice_headers
        )
        assert fetched.json()["data"] == expected


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
        "category": "actuators",
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
            "category": "actuators",
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
