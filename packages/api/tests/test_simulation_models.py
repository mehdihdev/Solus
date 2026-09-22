"""Bounded SO101 graph template creation, isolation, and resolver compatibility."""

import uuid

import pytest
from conftest import ALICE, BOB, add_member, bearer, create_project, create_team, me
from solus_api.agent.tools.isaac_models import SimulationModel
from solus_api.agent.tools.isaac_tools import _Resolver
from solus_api.models import GraphEdge, GraphEntity
from solus_api.routers.simulation_models import router
from sqlalchemy import select

BODY = {"template": "so101_new_calib_v1"}


@pytest.fixture(autouse=True)
def mounted(app):
    if not any(getattr(route, "path", "").endswith("/simulation-models") for route in app.routes):
        app.include_router(router)


async def setup(client, headers):
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def url(project):
    return f"/api/v1/projects/{project}/simulation-models"


async def test_template_creates_real_graph_and_reuses_intact_instance(
    client, alice_headers, db, app
):
    project, _ = await setup(client, alice_headers)
    response = await client.post(url(project), headers=alice_headers, json=BODY)
    assert response.status_code == 201, response.text
    result = response.json()["data"]
    model = SimulationModel.model_validate(result["bindings"])
    root = result["model"]
    assert root["origin"] == "manual" and root["source_id"] is None
    ids = {uuid.UUID(x) for x in model.entity_ids()} | {uuid.UUID(root["id"])}
    assert len(ids) == 17 and all(x.version == 7 for x in ids)
    rows = list(
        await db.scalars(select(GraphEntity).where(GraphEntity.project_id == uuid.UUID(project)))
    )
    assert ids <= {row.id for row in rows}
    edges = list(
        await db.scalars(select(GraphEdge).where(GraphEdge.project_id == uuid.UUID(project)))
    )
    assert len([edge for edge in edges if edge.src_id in ids and edge.dst_id in ids]) == 30
    # Production graph resolver, with the same session factory used by the app.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    graph = await _Resolver(
        async_sessionmaker(db.bind, expire_on_commit=False), uuid.UUID(project)
    ).resolve(root["id"])
    assert graph.model.entity_ids() == model.entity_ids()
    repeat = await client.post(url(project), headers=alice_headers, json=BODY)
    assert repeat.status_code == 200
    assert repeat.json()["data"]["model"]["id"] == root["id"]
    assert repeat.json()["data"]["created"] is False


@pytest.mark.parametrize(
    "body",
    [{}, {"template": "other"}, {**BODY, "attrs": {}}, {**BODY, "entity_id": str(uuid.uuid4())}],
)
async def test_template_rejects_freeform_inputs(client, alice_headers, body):
    project, _ = await setup(client, alice_headers)
    assert (await client.post(url(project), headers=alice_headers, json=body)).status_code == 422


@pytest.mark.parametrize("access", ["foreign", "viewer", "member"])
async def test_template_project_role_boundary(client, alice_headers, bob_headers, access):
    project, team = await setup(client, alice_headers)
    await me(client, bob_headers)
    if access != "foreign":
        await add_member(client, alice_headers, bob_headers, BOB, team, role=access)
    response = await client.post(url(project), headers=bob_headers, json=BODY)
    assert response.status_code == (
        201 if access == "member" else 404 if access == "foreign" else 403
    )


async def test_template_requires_auth_and_verified_identity(client, alice_headers):
    project, _ = await setup(client, alice_headers)
    assert (await client.post(url(project), json=BODY)).status_code == 401
    assert (
        await client.post(url(project), headers=bearer(**ALICE, email_verified=False), json=BODY)
    ).status_code == 403


@pytest.mark.parametrize("damage", ["model", "binding", "edge"])
async def test_template_refuses_damaged_existing_graph(client, alice_headers, db, damage):
    project, _ = await setup(client, alice_headers)
    result = (await client.post(url(project), headers=alice_headers, json=BODY)).json()["data"]
    root = await db.get(GraphEntity, uuid.UUID(result["model"]["id"]))
    if damage == "model":
        root.attrs = {"template": "so101_new_calib_v1"}
    elif damage == "binding":
        binding = await db.get(GraphEntity, uuid.UUID(result["bindings"]["links"][0]["entity_id"]))
        from solus_api.models import utcnow

        binding.deleted_at = utcnow()
    else:
        edge = await db.scalar(select(GraphEdge).where(GraphEdge.src_id == root.id))
        from solus_api.models import utcnow

        edge.deleted_at = utcnow()
    await db.commit()
    response = await client.post(url(project), headers=alice_headers, json=BODY)
    assert response.status_code == 409


@pytest.mark.parametrize("damage", ["pose", "parent", "extra"])
async def test_template_refuses_changed_template_defaults(client, alice_headers, db, damage):
    import copy

    project, _ = await setup(client, alice_headers)
    result = (await client.post(url(project), headers=alice_headers, json=BODY)).json()["data"]
    root = await db.get(GraphEntity, uuid.UUID(result["model"]["id"]))
    attrs = copy.deepcopy(root.attrs)
    if damage == "pose":
        attrs["simulation_model"]["sensors"][0]["translation_m"] = [0.1, 0.0, 0.0]
    elif damage == "parent":
        attrs["simulation_model"]["sensors"][0]["parent_link_entity_id"] = attrs[
            "simulation_model"
        ]["links"][0]["entity_id"]
    else:
        attrs["extra"] = "unsupported"
    root.attrs = attrs
    await db.commit()
    assert (await client.post(url(project), headers=alice_headers, json=BODY)).status_code == 409


async def test_template_emits_once_after_commit_and_concurrent_reuse(
    client, alice_headers, db, app, monkeypatch
):
    import asyncio

    from solus_api.models import DataEvent, User

    project, _ = await setup(client, alice_headers)
    user = await db.scalar(select(User).where(User.email == ALICE["email"]))
    user.data_collection_consent = True
    await db.commit()
    frames = []

    async def publish(project_id, frame):
        assert str(project_id) == project
        assert frame["counts"]["entities_created"] == 17
        assert frame["counts"]["relations_created"] == 30
        committed = await db.scalar(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id, GraphEntity.kind == "simulation_model"
            )
        )
        assert committed is not None
        frames.append(frame)

    monkeypatch.setattr(app.state.graph_hub, "publish", publish)
    responses = await asyncio.gather(
        *(client.post(url(project), headers=alice_headers, json=BODY) for _ in range(2))
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
    assert set(events[0].payload) == {"entity_id", "template"}
