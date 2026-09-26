"""CAD scene refresh consumes committed revision-bound acquisition once."""

import uuid

import pytest
from solus_api.livebench.scene.cad_refresh import ExportCapture


def test_capture_uses_only_selected_export_and_rejects_revision_mix():
    capture = ExportCapture({("doc", "element")})
    capture.observe("other", "element", "r1", "DATA")
    assert capture.exports == {}
    capture.observe("doc", "element", "r1", "FIRST")
    assert capture.exports[("doc", "element")] == ("r1", "FIRST")
    capture.observe("doc", "element", "r2", "SECOND")
    assert capture.error is not None


def test_capture_does_not_retain_unbounded_step():
    capture = ExportCapture({("doc", "element")})
    capture.observe("doc", "element", "r1", " " * (8 * 1024 * 1024 + 1))
    assert capture.error and not capture.exports


@pytest.fixture
async def scene(client, alice_headers, db, monkeypatch):
    from unittest.mock import AsyncMock

    from solus_api.models import Domain, GraphEntity, Source, SourceStatus, SourceType
    from solus_api.routers import sources
    from test_bench_scene import setup, upload
    from test_scene_parser import STL

    project, team, robot = await setup(client, alice_headers, db)
    source = Source(
        project_id=uuid.UUID(project),
        team_id=uuid.UUID(team),
        name="CAD",
        type=SourceType.ONSHAPE,
        status=SourceStatus.CONNECTED,
        secret_ref="test-reference",
        config={"documents": ["doc"]},
    )
    db.add(source)
    await db.flush()
    leaf = GraphEntity(
        project_id=uuid.UUID(project),
        source_id=source.id,
        kind="part",
        domain=Domain.MECHANICAL,
        origin="connector",
        name="CAD leaf",
        external_ref="doc:element:shape",
        attrs={
            "is_assembly": False,
            "document_id": "doc",
            "element_id": "element",
            "observed_microversion": "r1",
        },
    )
    db.add(leaf)
    await db.commit()
    xml = (
        b'<robot name="r"><link name="base"><visual><geometry>'
        b'<mesh filename="a.stl"/></geometry></visual></link></robot>'
    )
    artifact = await upload(client, alice_headers, project, xml)
    mesh = await upload(client, alice_headers, project, STL)
    base = f"/api/v1/projects/{project}/bench/scene"
    response = await client.post(
        base + "/models",
        headers=alice_headers,
        json={
            "robot_id": robot,
            "artifact_id": artifact,
            "name": "model",
            "format": "urdf",
            "meshes": [{"reference": "a.stl", "artifact_id": mesh}],
        },
    )
    assert response.status_code == 201, response.text
    model = response.json()["data"]

    async def queued(session, *args, **kwargs):
        await session.commit()
        return uuid.uuid4()

    enqueue = AsyncMock(side_effect=queued)
    monkeypatch.setattr(sources, "enqueue_sync", enqueue)
    return base, source, leaf, model, enqueue


async def bind(client, headers, scene):
    base, _, leaf, model, _ = scene
    key = next(iter(model["model"]["meshes"]))
    response = await client.put(
        f"{base}/models/{model['id']}/cad-bindings",
        headers=headers,
        json={
            "expected_version": model["version"],
            "bindings": [{"mesh_key": key, "source_entity_id": str(leaf.id)}],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["model"]


async def test_source_picker_binding_scope_and_optimistic_conflict(
    client, alice_headers, bob_headers, scene
):
    base, _, leaf, model, enqueue = scene
    options = await client.get(base + "/cad-sources", headers=alice_headers)
    assert options.status_code == 200
    assert options.json()["data"]["sources"] == [
        {"id": str(leaf.id), "name": "CAD leaf", "observed_microversion": "r1"}
    ]
    assert (await client.get(base + "/cad-sources")).status_code == 401
    assert (await client.get(base + "/cad-sources", headers=bob_headers)).status_code == 404
    bound = await bind(client, alice_headers, scene)
    assert bound["refresh_status"] == "queued"
    enqueue.assert_awaited_once()
    conflict = await client.put(
        f"{base}/models/{model['id']}/cad-bindings",
        headers=alice_headers,
        json={"expected_version": model["version"], "bindings": []},
    )
    assert conflict.status_code == 409


def step_pair(tmp_path):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from solus_api.connectors.step_parser import parse_step

    box = BRepPrimAPI_MakeBox(2, 3, 4).Shape()
    cut = BRepAlgoAPI_Cut(box, BRepPrimAPI_MakeBox(gp_Pnt(0.5, 0.5, 0), 1, 1, 4).Shape()).Shape()
    result = []
    for index, shape in enumerate((box, cut)):
        writer = STEPControl_Writer()
        writer.Transfer(shape, STEPControl_AsIs)
        path = tmp_path / f"geometry-{index}.step"
        writer.Write(str(path))
        text = path.read_text()
        result.append((text, parse_step(text).nodes[0].key))
    return result


async def test_actual_successive_syncs_replace_mesh_keep_identity(
    client, alice_headers, db, app, scene, tmp_path
):
    from solus_api.livebench.scene.cad_refresh import complete, prepare
    from solus_api.models import Artifact, GraphEntity, JobStatus, Sync, SyncTrigger
    from sqlalchemy.ext.asyncio import async_sessionmaker

    base, source, leaf, model, _ = scene
    await bind(client, alice_headers, scene)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    geometry = []
    for index, (content, key) in enumerate(step_pair(tmp_path)):
        await db.refresh(leaf)
        leaf.external_ref = f"doc:element:{key}"
        leaf.attrs = {**leaf.attrs, "observed_microversion": f"r{index + 1}"}
        sync = Sync(
            source_id=source.id,
            project_id=source.project_id,
            trigger=SyncTrigger.MANUAL,
            status=JobStatus.SUCCEEDED,
        )
        db.add(sync)
        await db.commit()
        async with maker() as session:
            plan = await prepare(session, source.id)
        plan.capture.observe("doc", "element", f"r{index + 1}", content)
        await complete(maker, app.state.artifact_store, plan, sync.id, None)
        result = (await client.get(base + "/models", headers=alice_headers)).json()["data"][
            "models"
        ][0]
        assert result["refresh_status"] == "current", result
        assert result["id"] == model["id"]
        assert result["model"]["joints"] == model["model"]["joints"]
        geometry.append(next(iter(result["model"]["meshes"].values()))["vertices"])
        entity = await db.get(GraphEntity, uuid.UUID(model["id"]))
        await db.refresh(entity)
        artifact = await db.get(Artifact, uuid.UUID(entity.attrs["geometry_artifact_id"]))
        assert artifact.retained
    assert geometry[0] != geometry[1]


async def test_failed_sync_preserves_geometry(client, alice_headers, db, app, scene):
    from solus_api.livebench.scene.cad_refresh import complete, prepare
    from sqlalchemy.ext.asyncio import async_sessionmaker

    base, source, _, model, _ = scene
    await bind(client, alice_headers, scene)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        plan = await prepare(session, source.id)
    plan.capture.observe("doc", "element", "r1", "not used")
    await complete(maker, app.state.artifact_store, plan, None, None)
    result = (await client.get(base + "/models", headers=alice_headers)).json()["data"]["models"][0]
    assert result["refresh_status"] == "error"
    assert result["model"] == model["model"]


async def test_existing_acquisition_delivers_scene_capture_without_second_export(tmp_path):
    from unittest.mock import AsyncMock

    import httpx
    from solus_api.connectors.export_common import ErrorRecorder
    from solus_api.connectors.onshape import OnshapeConnector, _Target

    content, _ = step_pair(tmp_path)[0]
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    export = AsyncMock(return_value=content)
    connector._geometry_export = export
    capture = ExportCapture({("doc", "element")})
    connector.scene_export_observer = capture.observe
    async with httpx.AsyncClient() as client:
        await connector._ingest(
            client, _Target("doc", "workspace", "element"), ErrorRecorder(), version="r1"
        )
    export.assert_awaited_once()
    assert capture.exports[("doc", "element")] == ("r1", content)


async def test_revoked_account_cannot_be_selected_even_with_stale_connected_source(
    client, alice_headers, db, scene
):
    from solus_api.models import AccountConnection, ConnectionStatus, SourceType, User
    from sqlalchemy import select

    base, source, leaf, model, _ = scene
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    connection = AccountConnection(
        user_id=user.id,
        provider=SourceType.ONSHAPE,
        status=ConnectionStatus.REVOKED,
        secret_ref=source.secret_ref,
    )
    db.add(connection)
    await db.flush()
    source.connection_id = connection.id
    await db.commit()
    options = await client.get(base + "/cad-sources", headers=alice_headers)
    assert options.json()["data"]["sources"] == []
    key = next(iter(model["model"]["meshes"]))
    response = await client.put(
        f"{base}/models/{model['id']}/cad-bindings",
        headers=alice_headers,
        json={
            "expected_version": model["version"],
            "bindings": [{"mesh_key": key, "source_entity_id": str(leaf.id)}],
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize("change", ["source", "scene"])
async def test_changes_during_tessellation_preserve_newer_scene(
    client, alice_headers, db, app, scene, monkeypatch, change
):
    from solus_api.livebench.scene import cad_refresh
    from solus_api.models import GraphEntity, JobStatus, Sync, SyncTrigger
    from sqlalchemy.ext.asyncio import async_sessionmaker

    base, source, leaf, model, _ = scene
    await bind(client, alice_headers, scene)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    sync = Sync(
        source_id=source.id,
        project_id=source.project_id,
        trigger=SyncTrigger.MANUAL,
        status=JobStatus.SUCCEEDED,
    )
    db.add(sync)
    await db.commit()
    async with maker() as session:
        plan = await cad_refresh.prepare(session, source.id)
    plan.capture.observe("doc", "element", "r1", "captured")

    async def parse(*args):
        async with maker() as session:
            identity = leaf.id if change == "source" else uuid.UUID(model["id"])
            entity = await session.get(GraphEntity, identity)
            if change == "source":
                entity.attrs = {**entity.attrs, "observed_microversion": "r2"}
            else:
                entity.name = "User edited scene"
            entity.version += 1
            await session.commit()
        return {"shape": {"vertices": [0, 0, 0, 2, 0, 0, 0, 2, 0]}}

    monkeypatch.setattr(cad_refresh, "tessellate_isolated", parse)
    await cad_refresh.complete(maker, app.state.artifact_store, plan, sync.id, None)
    result = (await client.get(base + "/models", headers=alice_headers)).json()["data"]["models"][0]
    assert result["model"] == model["model"]
    if change == "scene":
        assert result["name"] == "User edited scene"
    else:
        assert result["refresh_status"] == "error"


async def test_binding_mutation_auth_and_cross_tenant_are_noops(
    client, alice_headers, bob_headers, db, scene
):
    from solus_api.models import Domain, GraphEntity, Source, SourceStatus, SourceType
    from test_bench_scene import setup

    base, _, leaf, model, enqueue = scene
    other, team, _ = await setup(client, bob_headers, db)
    source = Source(
        project_id=uuid.UUID(other),
        team_id=uuid.UUID(team),
        name="Other CAD",
        type=SourceType.ONSHAPE,
        status=SourceStatus.CONNECTED,
        secret_ref="other-reference",
        config={"documents": ["other"]},
    )
    db.add(source)
    await db.flush()
    foreign_leaf = GraphEntity(
        project_id=uuid.UUID(other),
        source_id=source.id,
        kind="part",
        domain=Domain.MECHANICAL,
        origin="connector",
        name="Other leaf",
        external_ref="other:element:shape",
        attrs={
            "is_assembly": False,
            "document_id": "other",
            "element_id": "element",
            "observed_microversion": "r1",
        },
    )
    db.add(foreign_leaf)
    await db.commit()
    path = f"{base}/models/{model['id']}/cad-bindings"
    key = next(iter(model["model"]["meshes"]))
    body = {
        "expected_version": model["version"],
        "bindings": [{"mesh_key": key, "source_entity_id": str(leaf.id)}],
    }
    assert (await client.put(path, json=body)).status_code == 401
    assert (await client.put(path, headers=bob_headers, json=body)).status_code == 404
    assert (
        await client.put(
            path,
            headers=alice_headers,
            json={
                **body,
                "bindings": [{"mesh_key": key, "source_entity_id": str(foreign_leaf.id)}],
            },
        )
    ).status_code == 404
    foreign_path = f"/api/v1/projects/{other}/bench/scene/models/{model['id']}/cad-bindings"
    assert (await client.put(foreign_path, headers=bob_headers, json=body)).status_code == 404
    after = (await client.get(base + "/models", headers=alice_headers)).json()["data"]["models"][0]
    assert (
        after["model"] == model["model"]
        and after["cad_bindings"] == []
        and after["version"] == model["version"]
    )
    enqueue.assert_not_awaited()


async def test_refresh_commit_holds_same_source_lock_as_sync(
    client, alice_headers, db, app, scene, monkeypatch
):
    from solus_api.livebench.scene import cad_refresh
    from solus_api.models import JobStatus, Sync, SyncTrigger
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _, source, _, _, _ = scene
    await bind(client, alice_headers, scene)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    sync = Sync(
        source_id=source.id,
        project_id=source.project_id,
        trigger=SyncTrigger.MANUAL,
        status=JobStatus.SUCCEEDED,
    )
    db.add(sync)
    await db.commit()
    async with maker() as session:
        plan = await cad_refresh.prepare(session, source.id)
    plan.capture.observe("doc", "element", "r1", "captured")

    async def parse(*args):
        return {"shape": {"vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0]}}

    monkeypatch.setattr(cad_refresh, "tessellate_isolated", parse)
    original = app.state.artifact_store.put
    observed = []

    async def checked_put(*args, **kwargs):
        async with maker() as session:
            acquired = await session.scalar(
                select(
                    func.pg_try_advisory_xact_lock(func.hashtextextended(f"sync:{source.id}", 0))
                )
            )
            observed.append(acquired)
        return await original(*args, **kwargs)

    monkeypatch.setattr(app.state.artifact_store, "put", checked_put)
    await cad_refresh.complete(maker, app.state.artifact_store, plan, sync.id, None)
    assert observed == [False]
