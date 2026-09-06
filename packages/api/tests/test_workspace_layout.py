"""Project-shared canvas positions: docs/api/workspace.md (SOLUSDEV-242)."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from httpx import AsyncClient, Response
from solus_api.models import DataEvent, Domain, GraphEntity, Project, User, utcnow
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def _url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/workspace-layout"


async def _entities(db: AsyncSession, project_id: str, count: int = 2) -> list[GraphEntity]:
    nodes = [
        GraphEntity(
            project_id=uuid.UUID(project_id),
            kind="part",
            domain=Domain.MECHANICAL,
            name=f"Part {index}",
            origin="manual",
            attrs={"physical_property": "unchanged"},
        )
        for index in range(count)
    ]
    db.add_all(nodes)
    await db.commit()
    return nodes


async def _put(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    positions: dict[str, Any],
    version: int = 0,
) -> Response:
    return await client.put(
        _url(project_id), json={"version": version, "positions": positions}, headers=headers
    )


async def test_default_layout_is_empty_without_creating_graph_data(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    before = set(await db.scalars(select(GraphEntity.id)))
    response = await client.get(_url(project_id), headers=alice_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"data": {"version": 0, "positions": {}}}
    assert set(await db.scalars(select(GraphEntity.id))) == before


async def test_member_saves_project_shared_positions_and_replaces_the_map(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id)
    nodes = await _entities(db, project_id)
    positions = {str(nodes[0].id): {"x": -100000, "y": 100000}}
    response = await _put(client, bob_headers, project_id, positions)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"version": 1, "positions": positions}
    assert (await client.get(_url(project_id), headers=alice_headers)).json() == response.json()

    replacement = {str(nodes[1].id): {"x": 1.25, "y": -0.5}}
    saved = await _put(client, alice_headers, project_id, replacement, 1)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"] == {"version": 2, "positions": replacement}
    await db.refresh(nodes[0])
    assert nodes[0].attrs == {"physical_property": "unchanged"}
    cleared = await _put(client, alice_headers, project_id, {}, 2)
    assert cleared.json()["data"] == {"version": 3, "positions": {}}


async def test_stale_version_returns_conflict_without_overwriting(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    node = (await _entities(db, project_id, 1))[0]
    positions = {str(node.id): {"x": 10, "y": 20}}
    saved = await _put(client, alice_headers, project_id, positions)
    assert saved.status_code == 200
    conflict = await _put(client, alice_headers, project_id, {})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "conflict"
    assert (await client.get(_url(project_id), headers=alice_headers)).json() == saved.json()


@pytest.mark.parametrize("version", [0, 1])
async def test_concurrent_saves_have_exactly_one_winner_including_first_insert(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, version: int
) -> None:
    project_id, _ = await _project(client, alice_headers)
    node = (await _entities(db, project_id, 1))[0]
    if version:
        assert (await _put(client, alice_headers, project_id, {})).status_code == 200
    attempts = [{str(node.id): {"x": x, "y": 0}} for x in (10, 20)]
    results = await asyncio.gather(
        *(_put(client, alice_headers, project_id, positions, version) for positions in attempts)
    )
    assert sorted(result.status_code for result in results) == [200, 409]
    winner = next(result for result in results if result.status_code == 200)
    assert winner.json()["data"]["version"] == version + 1
    assert (await client.get(_url(project_id), headers=alice_headers)).json() == winner.json()


async def test_read_prunes_soft_deleted_and_hard_deleted_entities(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    nodes = await _entities(db, project_id, 3)
    positions = {str(node.id): {"x": index, "y": 0} for index, node in enumerate(nodes)}
    assert (await _put(client, alice_headers, project_id, positions)).status_code == 200
    nodes[0].deleted_at = utcnow()
    await db.execute(delete(GraphEntity).where(GraphEntity.id == nodes[1].id))
    await db.commit()
    response = await client.get(_url(project_id), headers=alice_headers)
    assert response.json()["data"] == {
        "version": 1,
        "positions": {str(nodes[2].id): positions[str(nodes[2].id)]},
    }


@pytest.mark.parametrize("kind", ["unknown", "other_project", "other_team", "deleted"])
async def test_rejects_positions_for_non_live_or_foreign_entities(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    kind: str,
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    entity_id = uuid.uuid4()
    if kind != "unknown":
        other_project_id = project_id
        if kind == "other_project":
            other_project_id = (await create_project(client, alice_headers, team_id))["id"]
        elif kind == "other_team":
            other_project_id, _ = await _project(client, bob_headers)
        node = (await _entities(db, other_project_id, 1))[0]
        entity_id = node.id
        if kind == "deleted":
            node.deleted_at = utcnow()
            await db.commit()
    response = await _put(client, alice_headers, project_id, {str(entity_id): {"x": 0, "y": 0}})
    assert response.status_code == 404, response.text
    assert (await client.get(_url(project_id), headers=alice_headers)).json()["data"] == {
        "version": 0,
        "positions": {},
    }


async def test_authentication_and_cross_team_access(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    await me(client, bob_headers)
    for method in ("GET", "PUT"):
        body = {"version": 0, "positions": {}} if method == "PUT" else None
        assert (await client.request(method, _url(project_id), json=body)).status_code == 401
        foreign = await client.request(method, _url(project_id), headers=bob_headers, json=body)
        assert foreign.status_code == 404
        missing = await client.request(
            method, _url(str(uuid.uuid4())), headers=alice_headers, json=body
        )
        assert missing.status_code == 404


async def test_viewer_can_read_but_cannot_write(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")
    assert (await client.get(_url(project_id), headers=bob_headers)).status_code == 200
    assert (await _put(client, bob_headers, project_id, {})).status_code == 403


async def test_soft_deleted_project_is_unavailable(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    project = await db.get(Project, uuid.UUID(project_id))
    assert project is not None
    project.deleted_at = utcnow()
    await db.commit()
    assert (await client.get(_url(project_id), headers=alice_headers)).status_code == 404
    assert (await _put(client, alice_headers, project_id, {})).status_code == 404


@pytest.mark.parametrize("version", [-1, 0.5, "0", True, None])
async def test_rejects_invalid_versions(
    client: AsyncClient, alice_headers: dict[str, str], version: Any
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.put(
        _url(project_id), headers=alice_headers, json={"version": version, "positions": {}}
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("value", [-100001, 100001, "0", True, None, float("nan"), float("inf")])
@pytest.mark.parametrize("axis", ["x", "y"])
async def test_rejects_invalid_coordinates(
    client: AsyncClient, alice_headers: dict[str, str], value: Any, axis: str
) -> None:
    project_id, _ = await _project(client, alice_headers)
    point = {"x": 0, "y": 0, axis: value}
    response = await client.put(
        _url(project_id),
        headers={**alice_headers, "Content-Type": "application/json"},
        content=json.dumps({"version": 0, "positions": {str(uuid.uuid4()): point}}),
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "malformed",
    [
        {"extra": float("nan")},
        {"positions": {str(uuid.uuid4()): float("nan")}},
        {"positions": {str(uuid.uuid4()): {"x": [float("nan")], "y": 0}}},
        {"extra": {"nested": [float("inf")]}},
    ],
)
async def test_rejects_nested_nonfinite_input_without_logging_payload(
    client: AsyncClient,
    alice_headers: dict[str, str],
    malformed: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.put(
        _url(project_id),
        headers={**alice_headers, "Content-Type": "application/json"},
        content=json.dumps({"version": 0, "positions": {}, **malformed}),
    )
    assert response.status_code == 422, response.text
    assert "NaN" not in caplog.text
    assert "Infinity" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"version": 0},
        {"positions": {}},
        {"version": 0, "positions": {}, "user_id": "ignored?"},
        {"version": 0, "positions": {}, "extra": [0] * 20000},
        {"version": 0, "positions": {"not-a-uuid": {"x": 0, "y": 0}}},
        {"version": 0, "positions": {str(uuid.uuid4()): {"x": 0, "y": 0, "z": 0}}},
        {"version": 0, "positions": {str(uuid.uuid4()): {"x": 0}}},
        {"version": 0, "positions": []},
        {"version": 0, "positions": {str(uuid.uuid4()): {"x": 0, "y": 0} for _ in range(5001)}},
    ],
)
async def test_rejects_invalid_shape_and_oversized_map(
    client: AsyncClient, alice_headers: dict[str, str], body: Any
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.put(_url(project_id), headers=alice_headers, json=body)
    assert response.status_code == 422, response.text


async def test_accepts_maximum_number_of_positions(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    nodes = await _entities(db, project_id, 5000)
    positions = {str(node.id): {"x": 0, "y": 0} for node in nodes}
    response = await _put(client, alice_headers, project_id, positions)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["positions"] == positions


@pytest.mark.parametrize("consented", [False, True])
async def test_save_emits_consent_gated_metadata_event_only_on_success(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, consented: bool
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    user_id = uuid.UUID((await me(client, alice_headers))["id"])
    user = await db.get(User, user_id)
    assert user is not None
    user.data_collection_consent = consented
    await db.commit()
    assert (await _put(client, alice_headers, project_id, {})).status_code == 200
    assert (await _put(client, alice_headers, project_id, {})).status_code == 409
    events = list(
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "workspace.layout_updated")
        )
    )
    assert len(events) == int(consented)
    if consented:
        assert events[0].payload == {"position_count": 0, "version": 1}
        assert events[0].project_id == uuid.UUID(project_id)
        assert events[0].team_id == uuid.UUID(team_id)
        assert events[0].user_id == user_id
