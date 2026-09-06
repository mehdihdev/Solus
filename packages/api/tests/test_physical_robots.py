"""Physical Robot instances and retained parts: docs/api/workspace.md Phase 4."""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient, Response
from solus_api.models import (
    DataEvent,
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    ProjectMembership,
    Source,
    SourceType,
    User,
    utcnow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CATEGORIES = {
    "sensors": "Sensors",
    "actuators": "Actuators / motors",
    "controllers": "Controllers",
    "end_effectors": "End effectors",
    "power": "Power",
    "structure": "Structure",
    "wiring": "Wiring",
}


def test_creation_schema_documents_an_optional_nonnullable_name() -> None:
    from solus_api.services.physical_robots import PhysicalRobotCreate

    schema = PhysicalRobotCreate.model_json_schema()
    assert "name" not in schema["required"]
    assert schema["properties"]["name"]["type"] == "string"
    assert "anyOf" not in schema["properties"]["name"]
    assert "default" not in schema["properties"]["name"]
    assert schema["properties"]["name"]["description"] == "Omit to use the project's name."


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def _url(project_id: str, entity_id: str | None = None) -> str:
    return f"/api/v1/projects/{project_id}/entities" + (f"/{entity_id}" if entity_id else "")


async def _create(
    client: AsyncClient, headers: dict[str, str], project_id: str, **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        _url(project_id), headers=headers, json={"type": "physical_robot", **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _mutate(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    entity_id: str,
    *,
    method: str = "PATCH",
    version: str | None = "1",
    body: Any = None,
) -> Response:
    return await client.request(
        method,
        _url(project_id, entity_id),
        headers={**headers, **({"If-Match": version} if version is not None else {})},
        json=body if method == "PATCH" else None,
    )


async def _categories(db: AsyncSession, robot_id: str) -> list[GraphEntity]:
    return list(
        await db.scalars(
            select(GraphEntity)
            .where(GraphEntity.attrs["robot_id"].astext == robot_id)
            .execution_options(populate_existing=True)
        )
    )


def _edge(project_id: str, src: uuid.UUID, dst: uuid.UUID, **extra: Any) -> GraphEdge:
    return GraphEdge(
        project_id=uuid.UUID(project_id),
        src_id=src,
        dst_id=dst,
        relation_type="contains",
        domain_pair="project<->mechanical",
        origin="manual",
        **extra,
    )


async def test_two_creations_have_independent_real_graph_trees(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    first = await _create(client, alice_headers, project_id)
    second = await _create(client, alice_headers, project_id, name="  Scout  ")
    assert first["name"] == "Rover"
    assert second["name"] == "Scout"
    assert first["id"] != second["id"]
    all_ids: set[uuid.UUID] = set()
    for root in (first, second):
        assert root["properties"] == {"hardware_config_ref": None, "transport_refs": None}
        assert root["domain"] == "project"
        assert root["origin"] == "manual" and root["source_id"] is None
        categories = await _categories(db, root["id"])
        assert {item.attrs["category"]: item.name for item in categories} == CATEGORIES
        assert all(
            item.kind == "robot_category" and item.domain == Domain.PROJECT for item in categories
        )
        edges = list(
            await db.scalars(select(GraphEdge).where(GraphEdge.src_id == uuid.UUID(root["id"])))
        )
        assert {edge.dst_id for edge in edges} == {item.id for item in categories}
        assert all(edge.origin == "manual" and edge.source_id is None for edge in edges)
        ids = {
            uuid.UUID(root["id"]),
            *(item.id for item in categories),
            *(edge.id for edge in edges),
        }
        assert len(ids) == 15 and not (ids & all_ids)
        assert all(item.version == 7 for item in ids)
        all_ids.update(ids)


@pytest.mark.parametrize("name", ["", " \t\n ", "a" * 513, None, 12, True, []])
async def test_create_rejects_invalid_names(
    client: AsyncClient, alice_headers: dict[str, str], name: Any
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.post(
        _url(project_id), headers=alice_headers, json={"type": "physical_robot", "name": name}
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "extra",
    [{"hardware_config_ref": None}, {"properties": {}}, {"transport_refs": []}, {"type": "part"}],
)
async def test_creation_rejects_unspecified_fields_and_other_kinds(
    client: AsyncClient, alice_headers: dict[str, str], extra: dict[str, Any]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.post(
        _url(project_id), headers=alice_headers, json={"type": "physical_robot", **extra}
    )
    assert response.status_code == 422, response.text


async def test_rename_versions_only_the_requested_robot_and_graph_stamp_changes(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    first = await _create(client, alice_headers, project_id)
    second = await _create(client, alice_headers, project_id)
    before = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]
    response = await _mutate(
        client, alice_headers, project_id, first["id"], body={"name": "  Scout  "}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["version"] == 2
    assert response.json()["data"]["name"] == "Scout"
    assert (await client.get(_url(project_id, second["id"]), headers=alice_headers)).json()["data"][
        "name"
    ] == "Rover"
    conflict = await _mutate(
        client, alice_headers, project_id, first["id"], body={"name": "Lost edit"}
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["details"] == [{"version": 2, "name": "Scout"}]
    after = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]
    assert before["stats"] == after["stats"]
    assert after["graph_updated_at"] > before["graph_updated_at"]


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize("version", [None, "", "1.0", "-1", '"1"', "true", "9" * 100])
async def test_mutations_require_a_bounded_integer_if_match(
    client: AsyncClient, alice_headers: dict[str, str], method: str, version: str | None
) -> None:
    project_id, _ = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    response = await _mutate(
        client,
        alice_headers,
        project_id,
        root["id"],
        method=method,
        version=version,
        body={"name": "Scout"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "a" * 513}, {"name": None}, {"name": "Scout", "properties": {}}],
)
async def test_rename_rejects_invalid_payloads(
    client: AsyncClient, alice_headers: dict[str, str], body: Any
) -> None:
    project_id, _ = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    assert (
        await _mutate(client, alice_headers, project_id, root["id"], body=body)
    ).status_code == 422


@pytest.mark.parametrize("access", ["foreign", "viewer", "share", "member"])
async def test_central_project_permissions_cover_every_surface(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    access: str,
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    bob = await me(client, bob_headers)
    if access in {"viewer", "member"}:
        await add_member(client, alice_headers, bob_headers, BOB, team_id, role=access)
    if access == "share":
        db.add(ProjectMembership(project_id=uuid.UUID(project_id), user_id=uuid.UUID(bob["id"])))
        await db.commit()
    read = await client.get(
        _url(project_id), params={"orphaned_from_robot": True}, headers=bob_headers
    )
    assert read.status_code == (404 if access == "foreign" else 200)
    expected = 404 if access == "foreign" else 403
    create = await client.post(
        _url(project_id), headers=bob_headers, json={"type": "physical_robot"}
    )
    assert create.status_code == (201 if access == "member" else expected)
    rename = await _mutate(client, bob_headers, project_id, root["id"], body={"name": "Scout"})
    assert rename.status_code == (200 if access == "member" else expected)
    deleted = await _mutate(
        client,
        bob_headers,
        project_id,
        root["id"],
        method="DELETE",
        version="2" if access == "member" else "1",
    )
    assert deleted.status_code == (200 if access == "member" else expected)


async def test_unauthenticated_requests_are_rejected(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    for method in ("GET", "POST", "PATCH", "DELETE"):
        entity_id = str(uuid.uuid4()) if method in {"PATCH", "DELETE"} else None
        response = await client.request(
            method,
            _url(project_id, entity_id),
            json={"type": "physical_robot", "name": "Scout"},
            headers={"If-Match": "1"},
        )
        assert response.status_code == 401, response.text


@pytest.mark.parametrize(
    "kind,origin",
    [
        ("part", "manual"),
        ("solus", "manual"),
        ("solus_section", "manual"),
        ("canonical_part", "fingerprint"),
        ("physical_robot", "fingerprint"),
        ("physical_robot", "connector"),
    ],
)
async def test_only_manual_physical_robot_roots_can_be_mutated(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, kind: str, origin: str
) -> None:
    project_id, _ = await _project(client, alice_headers)
    node = GraphEntity(
        project_id=uuid.UUID(project_id),
        kind=kind,
        origin=origin,
        domain=Domain.PROJECT,
        name="Protected",
    )
    db.add(node)
    await db.commit()
    for method in ("PATCH", "DELETE"):
        response = await _mutate(
            client, alice_headers, project_id, str(node.id), method=method, body={"name": "Wrong"}
        )
        assert response.status_code == 409, response.text
    await db.refresh(node)
    assert node.name == "Protected" and node.deleted_at is None


@pytest.mark.parametrize("state", ["unknown", "other_project", "deleted"])
async def test_non_live_or_foreign_entity_ids_are_not_disclosed(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, state: str
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    entity_id = str(uuid.uuid4())
    if state != "unknown":
        target_project = (
            project_id
            if state == "deleted"
            else (await create_project(client, alice_headers, team_id))["id"]
        )
        root = await _create(client, alice_headers, target_project)
        entity_id = root["id"]
        if state == "deleted":
            node = await db.get(GraphEntity, uuid.UUID(entity_id))
            assert node is not None
            node.deleted_at = utcnow()
            await db.commit()
    for method in ("PATCH", "DELETE"):
        assert (
            await _mutate(
                client, alice_headers, project_id, entity_id, method=method, body={"name": "Wrong"}
            )
        ).status_code == 404


async def test_deletion_retains_real_parts_service_containment_and_unrelated_links(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    first = await _create(client, alice_headers, project_id)
    second = await _create(client, alice_headers, project_id)
    category = (await _categories(db, first["id"]))[0]
    other_category = (await _categories(db, second["id"]))[0]
    nodes = [
        GraphEntity(
            project_id=uuid.UUID(project_id),
            kind=kind,
            origin="connector",
            domain=Domain.MECHANICAL,
            name=kind,
            attrs={"private_design": index},
        )
        for index, kind in enumerate(("part", "motor", "cad_document"))
    ]
    db.add_all(nodes)
    await db.flush()
    owned = [_edge(project_id, category.id, node.id) for node in nodes[:2]]
    service = _edge(project_id, nodes[2].id, nodes[0].id)
    service.origin = "connector"
    crosslink = _edge(project_id, nodes[0].id, nodes[1].id)
    crosslink.relation_type = "drives"
    other_ownership = _edge(project_id, other_category.id, nodes[1].id)
    db.add_all([*owned, service, crosslink, other_ownership])
    await db.commit()
    before = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["graph_updated_at"]
    response = await _mutate(client, alice_headers, project_id, first["id"], method="DELETE")
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "deleted_entity_id": first["id"],
        "retained_part_ids": sorted(str(node.id) for node in nodes[:2]),
    }
    for node in nodes:
        await db.refresh(node)
        assert node.deleted_at is None and node.attrs["private_design"] == nodes.index(node)
    for edge in (service, crosslink, other_ownership):
        await db.refresh(edge)
        assert edge.deleted_at is None
    for edge in owned:
        await db.refresh(edge)
        assert edge.deleted_at is not None
    for category in await _categories(db, first["id"]):
        assert category.deleted_at is not None
    assert (
        await client.get(_url(project_id, second["id"]), headers=alice_headers)
    ).status_code == 200
    for _ in range(2):
        orphans = await client.get(
            _url(project_id),
            params={"orphaned_from_robot": True, "limit": 1},
            headers=alice_headers,
        )
        assert [item["id"] for item in orphans.json()["data"]] == [str(nodes[0].id)]
    after = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["graph_updated_at"]
    assert after > before


async def test_direct_ownership_orphans_are_paginated_and_unowned_categories_survive(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    parts = [
        GraphEntity(
            project_id=uuid.UUID(project_id),
            kind="motor",
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=f"Motor {index}",
        )
        for index in range(3)
    ]
    impostor = GraphEntity(
        project_id=uuid.UUID(project_id),
        kind="robot_category",
        domain=Domain.PROJECT,
        origin="manual",
        name="Unowned category",
        attrs={"robot_id": root["id"], "category": "sensors"},
    )
    db.add_all([*parts, impostor])
    await db.flush()
    db.add_all(_edge(project_id, uuid.UUID(root["id"]), part.id) for part in parts)
    # Duplicate evidence must never duplicate the entity or break pagination.
    db.add(_edge(project_id, uuid.UUID(root["id"]), parts[0].id))
    await db.commit()
    assert (
        await _mutate(client, alice_headers, project_id, root["id"], method="DELETE")
    ).status_code == 200
    await db.refresh(impostor)
    assert impostor.deleted_at is None
    found: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"orphaned_from_robot": True, "limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get(_url(project_id), params=params, headers=alice_headers)).json()
        found.extend(item["id"] for item in page["data"])
        cursor = page["meta"]["next_cursor"]
        if not cursor:
            break
    assert len(found) == 3 and set(found) == {str(part.id) for part in parts}


async def test_source_associated_manual_robot_is_read_only(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    source = Source(
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        name="Source",
        type=SourceType.GITHUB,
    )
    db.add(source)
    await db.flush()
    node = await db.get(GraphEntity, uuid.UUID(root["id"]))
    assert node is not None
    node.source_id = source.id
    await db.commit()
    for method in ("PATCH", "DELETE"):
        response = await _mutate(
            client, alice_headers, project_id, root["id"], method=method, body={"name": "No"}
        )
        assert response.status_code == 409


async def test_graph_stamp_includes_deleted_relation_modification(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    before = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["graph_updated_at"]
    edge = await db.scalar(select(GraphEdge).where(GraphEdge.src_id == uuid.UUID(root["id"])))
    assert edge is not None
    edge.deleted_at = utcnow()
    await db.commit()
    after = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["graph_updated_at"]
    assert after > before
    assert datetime.fromisoformat(after) == edge.updated_at


async def test_creation_hook_rejects_a_deleted_project(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.core.errors import APIError
    from solus_api.services.physical_robots import PhysicalRobotService

    project_id, _ = await _project(client, alice_headers)
    project = await db.get(Project, uuid.UUID(project_id))
    assert project is not None
    project.deleted_at = utcnow()
    await db.commit()
    with pytest.raises(APIError) as caught:
        await PhysicalRobotService(db).create(project.id)
    assert caught.value.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": float("nan")},
        {"name": "Scout", "extra": [float("inf")]},
        {"type": float("nan")},
        [float("nan")],
    ],
)
async def test_nonfinite_malformed_payloads_remain_validation_errors(
    client: AsyncClient, alice_headers: dict[str, str], body: Any
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.post(
        _url(project_id),
        headers={**alice_headers, "Content-Type": "application/json"},
        content=json.dumps(body),
    )
    assert response.status_code == 422, response.text


async def test_concurrent_rename_and_delete_cannot_both_use_the_same_version(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    root = await _create(client, alice_headers, project_id)
    results = await asyncio.gather(
        _mutate(client, alice_headers, project_id, root["id"], body={"name": "Scout"}),
        _mutate(client, alice_headers, project_id, root["id"], method="DELETE"),
    )
    assert sum(item.status_code == 200 for item in results) == 1
    assert next(item.status_code for item in results if item.status_code != 200) in {404, 409}


async def test_creation_hook_is_transaction_scoped_and_never_a_singleton(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.services.physical_robots import PhysicalRobotService

    project_id, _ = await _project(client, alice_headers)
    service = PhysicalRobotService(db)
    first = await service.create(uuid.UUID(project_id))
    second = await service.create(uuid.UUID(project_id), name="Scout")
    assert first.id != second.id
    first_id = first.id
    await db.rollback()
    assert await db.get(GraphEntity, first_id) is None


async def test_metadata_events_and_sse_are_published_after_commit(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, _ = await _project(client, alice_headers)
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()
    frames: list[dict[str, Any]] = []

    async def publish(pid: uuid.UUID, frame: dict[str, Any]) -> None:
        assert str(pid) == project_id
        # A separate database session sees committed mutations before the hint.
        roots = list(
            await db.scalars(
                select(GraphEntity)
                .where(GraphEntity.kind == "physical_robot", GraphEntity.deleted_at.is_(None))
                .execution_options(populate_existing=True)
            )
        )
        assert len(roots) == (0 if frame["counts"]["entities_deleted"] else 1)
        if frame["counts"]["entities_updated"]:
            assert roots[0].name == "Private prototype name"
        frames.append(frame)

    monkeypatch.setattr(app.state.graph_hub, "publish", publish)
    root = await _create(client, alice_headers, project_id)
    assert (
        await _mutate(
            client, alice_headers, project_id, root["id"], body={"name": "Private prototype name"}
        )
    ).status_code == 200
    assert (
        await _mutate(client, alice_headers, project_id, root["id"], method="DELETE", version="2")
    ).status_code == 200
    assert len(frames) == 3
    assert all(frame["source_id"] is None and frame["sync_id"] is None for frame in frames)
    assert frames[0]["counts"]["entities_created"] == 8
    assert frames[0]["counts"]["relations_created"] == 7
    assert frames[2]["counts"]["entities_deleted"] == 8
    events = list(
        await db.scalars(select(DataEvent).where(DataEvent.event_type.like("workspace.robot_%")))
    )
    assert len(events) == 3
    assert "Private prototype name" not in json.dumps([event.payload for event in events] + frames)
