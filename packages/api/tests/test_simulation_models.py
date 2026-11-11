"""Generic graph model creation, idempotence, isolation and resolver compatibility."""

import asyncio
import copy
import uuid
from typing import Any

import pytest
from conftest import ALICE, BOB, add_member, bearer, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.isaac_models import SimulationModel
from solus_api.agent.tools.isaac_tools import _Resolver
from solus_api.models import DataEvent, Domain, GraphEdge, GraphEntity, User, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_isaac_tools import simulation_model

Headers = dict[str, str]


async def setup(client: AsyncClient, headers: Headers) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def url(project: str) -> str:
    return f"/api/v1/projects/{project}/simulation-models"


async def body_for(
    db: AsyncSession, project: str, joint_count: int = 2, sensor: bool = True
) -> dict[str, Any]:
    count = joint_count * 2 + 1 + int(sensor)
    entities = [
        GraphEntity(
            project_id=uuid.UUID(project),
            domain=Domain.MECHANICAL,
            kind="component",
            name=f"component {i}",
            attrs={},
        )
        for i in range(count)
    ]
    db.add_all(entities)
    await db.commit()
    return {
        "name": f"Synthetic {joint_count}-axis model",
        "model": simulation_model(
            [str(entity.id) for entity in entities], joint_count=joint_count, sensor=sensor
        ),
    }


@pytest.mark.parametrize(("joint_count", "sensor"), [(1, False), (3, True)])
async def test_models_use_existing_graph_and_reuse_identical_definition(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession, joint_count: int, sensor: bool
) -> None:
    project, _ = await setup(client, alice_headers)
    body = await body_for(db, project, joint_count, sensor)
    before = set(
        await db.scalars(select(GraphEntity.id).where(GraphEntity.project_id == uuid.UUID(project)))
    )
    response = await client.post(url(project), headers=alice_headers, json=body)
    assert response.status_code == 201, response.text
    result = response.json()["data"]
    model = SimulationModel.model_validate(result["bindings"])
    root = result["model"]
    assert root["origin"] == "manual" and root["source_id"] is None
    assert root["name"] == body["name"]
    after = set(
        await db.scalars(select(GraphEntity.id).where(GraphEntity.project_id == uuid.UUID(project)))
    )
    assert after - before == {uuid.UUID(root["id"])}
    edges = list(
        await db.scalars(select(GraphEdge).where(GraphEdge.src_id == uuid.UUID(root["id"])))
    )
    assert {(str(edge.dst_id), edge.relation_type) for edge in edges} == {
        (identity, "contains") for identity in model.entity_ids()
    }
    graph = await _Resolver(
        async_sessionmaker(db.bind, expire_on_commit=False), uuid.UUID(project)
    ).resolve(root["id"])
    assert graph.model.entity_ids() == model.entity_ids()
    repeat = await client.post(url(project), headers=alice_headers, json=body)
    assert repeat.status_code == 200
    assert repeat.json()["data"]["model"]["id"] == root["id"]
    assert repeat.json()["data"]["created"] is False


async def test_multiple_distinct_models_can_coexist(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession
) -> None:
    project, _ = await setup(client, alice_headers)
    first = await body_for(db, project, 1, False)
    second = await body_for(db, project, 3, True)
    results = [
        await client.post(url(project), headers=alice_headers, json=body)
        for body in (first, second)
    ]
    assert [result.status_code for result in results] == [201, 201]
    assert results[0].json()["data"]["model"]["id"] != results[1].json()["data"]["model"]["id"]


@pytest.mark.parametrize("damage", ["extra", "version", "asset", "parent", "limits"])
async def test_invalid_model_rejected_without_graph_mutation(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession, damage: str
) -> None:
    project, _ = await setup(client, alice_headers)
    body = await body_for(db, project)
    if damage == "extra":
        body["script"] = "untrusted"
    if damage == "version":
        body["model"]["schema_version"] = 1
    if damage == "asset":
        body["model"]["asset"]["urdf_path"] = "../robot.urdf"
    if damage == "parent":
        body["model"]["joints"][0]["parent_link_entity_id"] = str(uuid.uuid4())
    if damage == "limits":
        body["model"]["joints"][0]["lower_rad"] = 5.0
    assert (await client.post(url(project), headers=alice_headers, json=body)).status_code == 422
    assert (
        await db.scalar(
            select(GraphEntity).where(
                GraphEntity.project_id == uuid.UUID(project), GraphEntity.kind == "simulation_model"
            )
        )
        is None
    )


@pytest.mark.parametrize("access", ["foreign", "viewer", "member"])
async def test_project_role_boundary(
    client: AsyncClient,
    alice_headers: Headers,
    bob_headers: Headers,
    db: AsyncSession,
    access: str,
) -> None:
    project, team = await setup(client, alice_headers)
    body = await body_for(db, project)
    await me(client, bob_headers)
    if access != "foreign":
        await add_member(client, alice_headers, bob_headers, BOB, team, role=access)
    response = await client.post(url(project), headers=bob_headers, json=body)
    assert response.status_code == (
        201 if access == "member" else 404 if access == "foreign" else 403
    )


async def test_auth_and_verified_identity_required(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession
) -> None:
    project, _ = await setup(client, alice_headers)
    body = await body_for(db, project)
    assert (await client.post(url(project), json=body)).status_code == 401
    assert (
        await client.post(url(project), headers=bearer(**ALICE, email_verified=False), json=body)
    ).status_code == 403


@pytest.mark.parametrize("damage", ["foreign", "deleted", "workspace"])
async def test_unavailable_component_refused_atomically(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession, damage: str
) -> None:
    project, _ = await setup(client, alice_headers)
    body = await body_for(db, project)
    entity = await db.get(GraphEntity, uuid.UUID(body["model"]["links"][0]["entity_id"]))
    assert entity is not None
    if damage == "foreign":
        other, _ = await setup(client, alice_headers)
        entity.project_id = uuid.UUID(other)
    elif damage == "deleted":
        entity.deleted_at = utcnow()
    else:
        entity.domain = Domain.WORKSPACE
    await db.commit()
    response = await client.post(url(project), headers=alice_headers, json=body)
    assert response.status_code == 404, response.text
    assert (
        await db.scalar(
            select(GraphEntity).where(
                GraphEntity.project_id == uuid.UUID(project), GraphEntity.kind == "simulation_model"
            )
        )
        is None
    )


@pytest.mark.parametrize("damage", ["model", "edge", "deleted"])
async def test_changed_existing_model_not_silently_repaired(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession, damage: str
) -> None:
    project, _ = await setup(client, alice_headers)
    body = await body_for(db, project)
    result = (await client.post(url(project), headers=alice_headers, json=body)).json()["data"]
    root = await db.get(GraphEntity, uuid.UUID(result["model"]["id"]))
    assert root is not None
    if damage == "model":
        attrs = copy.deepcopy(root.attrs)
        attrs["simulation_model"]["joints"][0]["lower_rad"] = -0.25
        root.attrs = attrs
    elif damage == "deleted":
        root.deleted_at = utcnow()
    else:
        edge = await db.scalar(select(GraphEdge).where(GraphEdge.src_id == root.id))
        assert edge is not None
        edge.deleted_at = utcnow()
    await db.commit()
    assert (await client.post(url(project), headers=alice_headers, json=body)).status_code == 409


async def test_emits_dynamic_counts_once_after_commit_and_concurrent_reuse(
    client: AsyncClient,
    alice_headers: Headers,
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _ = await setup(client, alice_headers)
    body = await body_for(db, project, 1, False)
    user = await db.scalar(select(User).where(User.email == ALICE["email"]))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()
    frames: list[dict[str, Any]] = []

    async def publish(project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        assert str(project_id) == project
        assert frame["counts"]["entities_created"] == 1
        assert frame["counts"]["relations_created"] == 3
        assert (
            await db.scalar(
                select(GraphEntity).where(
                    GraphEntity.project_id == project_id, GraphEntity.kind == "simulation_model"
                )
            )
            is not None
        )
        frames.append(frame)

    monkeypatch.setattr(app.state.graph_hub, "publish", publish)
    responses = await asyncio.gather(
        *(client.post(url(project), headers=alice_headers, json=body) for _ in range(2))
    )
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert len({response.json()["data"]["model"]["id"] for response in responses}) == 1
    assert len(frames) == 1
    events = list(
        await db.scalars(
            select(DataEvent).where(
                DataEvent.project_id == uuid.UUID(project),
                DataEvent.event_type == "simulation.model_created",
            )
        )
    )
    assert len(events) == 1
    assert set(events[0].payload) == {"entity_id", "schema_version"}


async def test_explicit_v2_creation_does_not_mutate_legacy_graph(
    client: AsyncClient, alice_headers: Headers, db: AsyncSession
) -> None:
    project, _ = await setup(client, alice_headers)
    legacy = GraphEntity(
        project_id=uuid.UUID(project),
        domain=Domain.SIMULATION,
        kind="simulation_model",
        name="Legacy model",
        attrs={"simulation_model": {"schema_version": 1}},
    )
    db.add(legacy)
    await db.commit()
    body = await body_for(db, project, 1, False)
    response = await client.post(url(project), headers=alice_headers, json=body)
    assert response.status_code == 201, response.text
    await db.refresh(legacy)
    assert legacy.attrs == {"simulation_model": {"schema_version": 1}}
    assert legacy.deleted_at is None
    assert response.json()["data"]["model"]["id"] != str(legacy.id)


async def test_system_origin_and_extra_attrs_validate_only_the_definition(
    db: AsyncSession, client: AsyncClient, alice_headers: Headers
) -> None:
    """SOLUSDEV-322 P6-T2: the generation job creates with `origin="system"` and rides its own
    attrs (robot, revision, gaps, artifacts) beside `simulation_model`; a rerun with the same
    definition but different extra attrs is the same model (reused, never 409)."""
    from solus_api.services.simulation_models import SimulationModelCreate, SimulationModelService

    project, _ = await setup(client, alice_headers)
    body = SimulationModelCreate.model_validate(await body_for(db, project, 1, False))
    service = SimulationModelService(db)
    root, _, created = await service.create(
        uuid.UUID(project), body, origin="system", extra_attrs={"gaps": [{"name": "mass"}]}
    )
    await db.commit()
    assert created and root.origin == "system" and root.attrs["gaps"] == [{"name": "mass"}]
    edges = list(await db.scalars(select(GraphEdge).where(GraphEdge.src_id == root.id)))
    assert edges and all(edge.origin == "system" for edge in edges)
    again, _, created = await service.create(
        uuid.UUID(project), body, origin="system", extra_attrs={"gaps": []}
    )
    assert (again.id, created) == (root.id, False)
    # The same definition asked for as a manual model is a different thing: a conflict.
    from solus_api.core.errors import APIError

    with pytest.raises(APIError) as refused:
        await service.create(uuid.UUID(project), body)
    assert refused.value.status_code == 409
