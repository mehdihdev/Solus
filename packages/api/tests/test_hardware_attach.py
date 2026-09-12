"""From a file (docs/api/hardware.md §4): connector-sourced parts not yet owned by a robot are
listed, and a multi-select attaches them under a category — never twice, never across robots."""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import Domain, GraphEdge, GraphEntity, Source, SourceType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _attach_project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"]), str(team["id"])


async def _attach_robot(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=headers,
        json={"type": "physical_robot", "name": "Arm"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


async def _connector_parts(
    db: AsyncSession, project_id: str, team_id: str, names: list[str]
) -> list[uuid.UUID]:
    source = Source(
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        type=SourceType.ONSHAPE,
        name="CAD",
        config={},
        status="connected",
    )
    db.add(source)
    await db.flush()
    ids: list[uuid.UUID] = []
    for index, name in enumerate(names):
        part = GraphEntity(
            project_id=uuid.UUID(project_id),
            kind="part",
            domain=Domain.MECHANICAL,
            name=name,
            origin="connector",
            source_id=source.id,
            source_connector="onshape",
            external_ref=f"doc:{index}",
            attrs={},
        )
        db.add(part)
        await db.flush()
        ids.append(part.id)
    await db.commit()
    return ids


def _attach_url(project_id: str, *parts: str) -> str:
    return f"/api/v1/projects/{project_id}/hardware/" + "/".join(parts)


async def test_unassigned_lists_connector_parts_not_owned_by_a_robot(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, team_id = await _attach_project(client, alice_headers)
    robot_id = await _attach_robot(client, alice_headers, project_id)
    parts = await _connector_parts(db, project_id, team_id, ["bracket", "camera mount", "horn"])
    attach = await client.post(
        _attach_url(project_id, "robots", robot_id, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [str(parts[0])], "category": "structure"},
    )
    assert attach.status_code == 200, attach.text
    resp = await client.get(_attach_url(project_id, "unassigned"), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    listed = {row["id"] for row in resp.json()["data"]}
    assert listed == {str(parts[1]), str(parts[2])}
    assert resp.json()["meta"]["next_cursor"] is None


async def test_named_manual_part_is_unassigned_then_attachable(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _attach_project(client, alice_headers)
    robot_id = await _attach_robot(client, alice_headers, project_id)
    part = GraphEntity(
        project_id=uuid.UUID(project_id),
        kind="part",
        domain=Domain.PROJECT,
        origin="manual",
        name="Named gripper",
        attrs={},
    )
    db.add(part)
    await db.commit()
    listed = await client.get(_attach_url(project_id, "unassigned"), headers=alice_headers)
    assert any(
        row["id"] == str(part.id) and row["name"] == "Named gripper"
        for row in listed.json()["data"]
    )
    attached = await client.post(
        _attach_url(project_id, "robots", robot_id, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [str(part.id)], "category": "end_effectors"},
    )
    assert attached.status_code == 200, attached.text
    listed = await client.get(_attach_url(project_id, "unassigned"), headers=alice_headers)
    assert all(row["id"] != str(part.id) for row in listed.json()["data"])


async def test_unassigned_pages_and_bounds_the_limit(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, team_id = await _attach_project(client, alice_headers)
    await _connector_parts(db, project_id, team_id, [f"p{i}" for i in range(5)])
    first = await client.get(
        _attach_url(project_id, "unassigned"), headers=alice_headers, params={"limit": 2}
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["data"]) == 2 and first.json()["meta"]["next_cursor"]
    second = await client.get(
        _attach_url(project_id, "unassigned"),
        headers=alice_headers,
        params={"limit": 2, "cursor": first.json()["meta"]["next_cursor"]},
    )
    assert len(second.json()["data"]) == 2
    too_many = await client.get(
        _attach_url(project_id, "unassigned"), headers=alice_headers, params={"limit": 1000}
    )
    assert too_many.status_code == 422


async def test_attach_creates_category_edges_and_config_slots(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, team_id = await _attach_project(client, alice_headers)
    robot_id = await _attach_robot(client, alice_headers, project_id)
    parts = await _connector_parts(db, project_id, team_id, ["imu board", "imu bracket"])
    resp = await client.post(
        _attach_url(project_id, "robots", robot_id, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [str(p) for p in parts], "category": "sensors"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data["attached"]) == {str(p) for p in parts} and data["skipped"] == []
    assert data["config_entry_id"]
    for part_id in parts:
        edge = await db.scalar(
            select(GraphEdge).where(
                GraphEdge.dst_id == part_id,
                GraphEdge.relation_type == "contains",
                GraphEdge.origin == "manual",
                GraphEdge.deleted_at.is_(None),
            )
        )
        assert edge is not None
        category = await db.get(GraphEntity, edge.src_id)
        assert category is not None and category.attrs["category"] == "sensors"
        part = await db.get(GraphEntity, part_id)
        assert part is not None and part.origin == "connector"  # identity untouched
        saved = await client.get(
            _attach_url(project_id, "entities", str(part_id), "config"), headers=alice_headers
        )
        document = saved.json()["data"]["config"]
        assert document["schema_version"] == 2 and document["entity_id"] == str(part_id)
        assert document["component"]["lifecycle"] == "planned"
        assert "parts" not in document
    config = (
        await client.get(
            _attach_url(project_id, "robots", robot_id, "config"), headers=alice_headers
        )
    ).json()["data"]["config"]
    assert set(config["parts"]) == {str(p) for p in parts}
    assert all(part["lifecycle"] == "planned" for part in config["parts"].values())


async def test_attach_skips_parts_already_here_and_refuses_parts_of_another_robot(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, team_id = await _attach_project(client, alice_headers)
    first = await _attach_robot(client, alice_headers, project_id)
    second = await _attach_robot(client, alice_headers, project_id)
    parts = await _connector_parts(db, project_id, team_id, ["shared"])
    body: dict[str, Any] = {"entity_ids": [str(parts[0])], "category": "structure"}
    initial = await client.post(
        _attach_url(project_id, "robots", first, "parts", "attach"),
        headers=alice_headers,
        json=body,
    )
    assert initial.status_code == 200, initial.text
    again = await client.post(
        _attach_url(project_id, "robots", first, "parts", "attach"),
        headers=alice_headers,
        json=body,
    )
    assert again.status_code == 200 and again.json()["data"]["skipped"] == [str(parts[0])]
    other = await client.post(
        _attach_url(project_id, "robots", second, "parts", "attach"),
        headers=alice_headers,
        json=body,
    )
    assert other.status_code == 409, other.text


@pytest.mark.parametrize(
    "body",
    [
        {"entity_ids": [], "category": "structure"},
        {"entity_ids": [str(uuid.uuid4())], "category": "structure"},
        {"entity_ids": ["x"], "category": "structure"},
        {"entity_ids": [str(uuid.uuid4()) for _ in range(65)], "category": "structure"},
    ],
)
async def test_attach_rejects_bad_bodies(
    client: AsyncClient, alice_headers: dict[str, str], body: dict[str, Any]
) -> None:
    project_id, _ = await _attach_project(client, alice_headers)
    robot_id = await _attach_robot(client, alice_headers, project_id)
    resp = await client.post(
        _attach_url(project_id, "robots", robot_id, "parts", "attach"),
        headers=alice_headers,
        json=body,
    )
    assert resp.status_code in (404, 422), resp.text


async def test_attach_refuses_a_robot_root_or_a_foreign_part(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, _ = await _attach_project(client, alice_headers)
    other_project, other_team = await _attach_project(client, alice_headers)
    robot_id = await _attach_robot(client, alice_headers, project_id)
    foreign = await _connector_parts(db, other_project, other_team, ["foreign"])
    resp = await client.post(
        _attach_url(project_id, "robots", robot_id, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [str(foreign[0])], "category": "structure"},
    )
    assert resp.status_code == 404, resp.text
    resp = await client.post(
        _attach_url(project_id, "robots", robot_id, "parts", "attach"),
        headers=alice_headers,
        json={"entity_ids": [robot_id], "category": "structure"},
    )
    assert resp.status_code == 404, resp.text
    await me(client, bob_headers)
    listed = await client.get(_attach_url(project_id, "unassigned"), headers=bob_headers)
    assert listed.status_code == 404
