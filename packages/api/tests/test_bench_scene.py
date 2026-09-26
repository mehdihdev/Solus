"""Scene API boundaries and durable graph identity."""

import uuid

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from solus_api.livebench.scene.router import router
from solus_api.models import Domain, GraphEntity


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(router)


async def setup(client, headers, db):
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    robot = GraphEntity(
        project_id=uuid.UUID(project["id"]),
        kind="physical_robot",
        domain=Domain.RUNTIME,
        origin="manual",
        name="Robot",
    )
    db.add(robot)
    await db.commit()
    return project["id"], team["id"], str(robot.id)


async def upload(client, headers, project, content=b'<robot name="r"><link name="base"/></robot>'):
    response = await client.post(
        f"/api/v1/projects/{project}/artifacts",
        headers=headers,
        files={"file": ("model.xml", content, "application/xml")},
        data={"media_type": "application/xml"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["artifact_id"]


async def test_import_retains_and_revision_preserves_identity(client, alice_headers, db):
    project, _, robot = await setup(client, alice_headers, db)
    artifact = await upload(client, alice_headers, project)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    body = {"robot_id": robot, "artifact_id": artifact, "name": "Local robot", "format": "urdf"}
    response = await client.post(base, headers=alice_headers, json=body)
    assert response.status_code == 201, response.text
    model = response.json()["data"]
    assert model["model"]["warnings"] and model["source_current"]
    changed = await client.put(
        f"{base}/{model['id']}",
        headers=alice_headers,
        json={**body, "expected_version": model["version"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["id"] == model["id"]
    assert (
        await client.put(
            f"{base}/{model['id']}",
            headers=alice_headers,
            json={**body, "expected_version": model["version"]},
        )
    ).status_code == 409
    assert len((await client.get(base, headers=alice_headers)).json()["data"]["models"]) == 1


@pytest.mark.parametrize("role,status", [("foreign", 404), ("viewer", 403), ("member", 200)])
async def test_project_access(client, alice_headers, bob_headers, db, role, status):
    project, team, _ = await setup(client, alice_headers, db)
    await me(client, bob_headers)
    if role != "foreign":
        await add_member(client, alice_headers, bob_headers, BOB, team, role=role)
    assert (
        await client.get(f"/api/v1/projects/{project}/bench/scene/models", headers=bob_headers)
    ).status_code == status


async def test_mapping_is_confirmed_config_scoped_and_becomes_stale(client, alice_headers, db):
    from test_hardware_router import _hw_project, _hw_url, _robot, _saved_serial_arm
    from test_scene_parser import URDF

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    saved = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert saved.status_code == 200, saved.text
    artifact = await upload(client, alice_headers, project, URDF)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    response = await client.post(
        base,
        headers=alice_headers,
        json={"robot_id": robot["id"], "artifact_id": artifact, "name": "arm", "format": "urdf"},
    )
    assert response.status_code == 201, response.text
    model = response.json()["data"]
    part = config["bus_map"][0]
    binding = {
        "joint": "hinge",
        "part_entity_id": part["part_entity_id"],
        "device_id": f"usb:{config['identity']['binding']}/{part['address']}",
        "signal": "position",
        "unit": "deg",
        "scale": 1,
        "offset": 0,
    }
    url = f"{base}/{model['id']}/mapping"
    for bad in (
        {**binding, "unit": "m"},
        {**binding, "device_id": "usb:foreign/1"},
        {**binding, "joint": "unknown"},
    ):
        assert (
            await client.put(
                url,
                headers=alice_headers,
                json={"expected_version": model["version"], "bindings": [bad]},
            )
        ).status_code == 422
    mapped = await client.put(
        url,
        headers=alice_headers,
        json={"expected_version": model["version"], "bindings": [binding]},
    )
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["data"]["bindings"] == [binding]
    config["identity"]["binding"] = "different-hardware"
    response = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert response.status_code == 200, response.text
    stale = (await client.get(base, headers=alice_headers)).json()["data"]["models"][0]
    assert not stale["source_current"] and stale["bindings"] == []


async def test_two_models_and_artifact_ttl_retention(client, alice_headers, db):
    from datetime import timedelta

    from solus_api.models import Artifact, utcnow

    project, _, robot = await setup(client, alice_headers, db)
    artifact = await upload(client, alice_headers, project)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    body = {"robot_id": robot, "artifact_id": artifact, "name": "model", "format": "urdf"}
    one = await client.post(base, headers=alice_headers, json=body)
    two = await client.post(base, headers=alice_headers, json={**body, "name": "second"})
    assert one.status_code == two.status_code == 201
    assert one.json()["data"]["id"] != two.json()["data"]["id"]
    row = await db.get(Artifact, uuid.UUID(artifact))
    await db.refresh(row)
    assert row.retained
    row.created_at = utcnow() - timedelta(days=7)
    await db.commit()
    content = await client.get(
        f"/api/v1/projects/{project}/artifacts/{artifact}/content", headers=alice_headers
    )
    assert content.status_code == 200


async def test_foreign_artifact_robot_and_missing_auth(client, alice_headers, db):
    project, _, robot = await setup(client, alice_headers, db)
    other, _, other_robot = await setup(client, alice_headers, db)
    artifact = await upload(client, alice_headers, other)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    body = {"robot_id": robot, "artifact_id": artifact, "name": "model", "format": "urdf"}
    assert (await client.post(base, headers=alice_headers, json=body)).status_code == 404
    own = await upload(client, alice_headers, project)
    assert (
        await client.post(
            base, headers=alice_headers, json={**body, "artifact_id": own, "robot_id": other_robot}
        )
    ).status_code == 404
    assert (await client.get(base)).status_code == 401


async def test_source_revision_invalidates_until_reimport(client, alice_headers, db):
    project, _, robot = await setup(client, alice_headers, db)
    source = GraphEntity(
        project_id=uuid.UUID(project),
        kind="document",
        domain=Domain.PROJECT,
        origin="manual",
        name="design",
        attrs={"revision": "a"},
    )
    db.add(source)
    await db.commit()
    artifact = await upload(client, alice_headers, project)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    body = {
        "robot_id": robot,
        "artifact_id": artifact,
        "name": "model",
        "format": "urdf",
        "source_entity_id": str(source.id),
        "source_revision": "a",
    }
    created = (await client.post(base, headers=alice_headers, json=body)).json()["data"]
    source.attrs = {"revision": "b"}
    source.version += 1
    await db.commit()
    stale = (await client.get(base, headers=alice_headers)).json()["data"]["models"][0]
    assert not stale["source_current"]
    assert (
        await client.put(
            f"{base}/{created['id']}/mapping",
            headers=alice_headers,
            json={"expected_version": created["version"], "bindings": []},
        )
    ).status_code == 409
    updated = await client.put(
        f"{base}/{created['id']}",
        headers=alice_headers,
        json={**body, "source_revision": "b", "expected_version": created["version"]},
    )
    assert updated.status_code == 200 and updated.json()["data"]["source_current"]


async def test_explicit_mesh_import_retains_only_scoped_artifacts(client, alice_headers, db):
    from solus_api.models import Artifact
    from test_scene_parser import STL

    project, _, robot = await setup(client, alice_headers, db)
    xml = (
        b'<robot name="r">'
        b'<link name="base">'
        b"<visual>"
        b"<geometry>"
        b'<mesh filename="parts/a.stl"/>'
        b"</geometry>"
        b"</visual>"
        b"</link>"
        b"</robot>"
    )
    artifact = await upload(client, alice_headers, project, xml)
    mesh = await upload(client, alice_headers, project, STL)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    body = {
        "robot_id": robot,
        "artifact_id": artifact,
        "name": "mesh model",
        "format": "urdf",
        "meshes": [{"reference": "parts/a.stl", "artifact_id": mesh}],
    }
    response = await client.post(base, headers=alice_headers, json=body)
    assert response.status_code == 201, response.text
    model = response.json()["data"]["model"]
    assert len(next(iter(model["meshes"].values()))["vertices"]) == 9
    row = await db.get(Artifact, uuid.UUID(mesh))
    await db.refresh(row)
    assert row.retained
    other, _, _ = await setup(client, alice_headers, db)
    foreign = await upload(client, alice_headers, other, STL)
    bad = await client.post(
        base,
        headers=alice_headers,
        json={**body, "meshes": [{"reference": "parts/a.stl", "artifact_id": foreign}]},
    )
    assert bad.status_code == 404


@pytest.mark.parametrize("action", ["replace", "mapping"])
async def test_mutations_cannot_touch_foreign_models(
    client, alice_headers, bob_headers, db, action
):
    project, _, robot = await setup(client, alice_headers, db)
    artifact = await upload(client, alice_headers, project)
    base = f"/api/v1/projects/{project}/bench/scene/models"
    body = {"robot_id": robot, "artifact_id": artifact, "name": "Protected", "format": "urdf"}
    model = (await client.post(base, headers=alice_headers, json=body)).json()["data"]
    foreign_project, _, foreign_robot = await setup(client, bob_headers, db)
    own_artifact = await upload(client, bob_headers, foreign_project)
    endpoint = f"/{model['id']}" + ("/mapping" if action == "mapping" else "")
    payload = (
        {"expected_version": model["version"], "bindings": []}
        if action == "mapping"
        else {
            **body,
            "robot_id": foreign_robot,
            "artifact_id": own_artifact,
            "expected_version": model["version"],
        }
    )
    for prefix, headers, status in [
        (base, bob_headers, 404),
        (f"/api/v1/projects/{foreign_project}/bench/scene/models", bob_headers, 404),
        (base, {}, 401),
    ]:
        denied = await client.put(prefix + endpoint, headers=headers, json=payload)
        assert denied.status_code == status, denied.text
    unchanged = (await client.get(base, headers=alice_headers)).json()["data"]["models"][0]
    assert unchanged == model


@pytest.mark.parametrize("kind", ["xml", "mesh"])
async def test_oversized_metadata_rejects_before_read(
    client, alice_headers, db, app, monkeypatch, kind
):
    from unittest.mock import AsyncMock

    from solus_api.models import Artifact

    project, _, robot = await setup(client, alice_headers, db)
    artifact = await upload(client, alice_headers, project)
    oversized = (
        artifact if kind == "xml" else await upload(client, alice_headers, project, b"solid mesh")
    )
    row = await db.get(Artifact, uuid.UUID(oversized))
    row.size_bytes = 9 * 1024 * 1024
    await db.commit()
    get = AsyncMock(wraps=app.state.artifact_store.get)
    monkeypatch.setattr(app.state.artifact_store, "get", get)
    body = {"robot_id": robot, "artifact_id": artifact, "name": "Blocked", "format": "urdf"}
    if kind == "mesh":
        body["meshes"] = [{"reference": "arm.stl", "artifact_id": oversized}]
    response = await client.post(
        f"/api/v1/projects/{project}/bench/scene/models", headers=alice_headers, json=body
    )
    assert response.status_code == 413, response.text
    assert all(call.args[0] != oversized for call in get.call_args_list)
