"""CAD import refuses missing placement evidence and composes measured transforms."""

import pytest
from solus_api.livebench.scene.cad_import import compose, rigid_matrix, transform_mesh
from test_scene_cad_refresh import scene as scene


def test_parent_rotation_moves_child_translation_once_in_metres():
    parent = rigid_matrix(
        {"length_unit": "mm", "matrix": [0, -1, 0, 100, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    )
    child = rigid_matrix(
        {"length_unit": "mm", "matrix": [1, 0, 0, 20, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    )
    result = transform_mesh({"vertices": [0.001, 0, 0] * 3}, compose(parent, child))
    assert result["vertices"][:3] == pytest.approx([0.1, 0.021, 0])


@pytest.mark.parametrize(
    "value",
    [None, {}, {"length_unit": "m", "matrix": [1] * 16}, {"length_unit": "mm", "matrix": [0] * 16}],
)
def test_no_guessed_identity_or_nonrigid_transform(value):
    with pytest.raises(ValueError):
        rigid_matrix(value)


async def test_import_requires_measured_transform(client, alice_headers, scene):
    base, _, leaf, model, _ = scene
    result = await client.post(
        base + "/cad-imports",
        headers=alice_headers,
        json={
            "robot_id": model["robot_id"],
            "source_entity_id": str(leaf.id),
            "expected_revision": "r1",
        },
    )
    assert result.status_code == 422


async def test_import_pending_reused_and_scoped(client, alice_headers, bob_headers, db, scene):
    from conftest import me

    base, _, leaf, model, enqueue = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    body = {
        "robot_id": model["robot_id"],
        "source_entity_id": str(leaf.id),
        "expected_revision": "r1",
    }
    first = await client.post(base + "/cad-imports", headers=alice_headers, json=body)
    assert first.status_code == 202, first.text
    second = await client.post(base + "/cad-imports", headers=alice_headers, json=body)
    assert second.json()["data"]["import_id"] == first.json()["data"]["import_id"]
    assert enqueue.await_count == 1
    await me(client, bob_headers)
    path = base + "/cad-imports/" + first.json()["data"]["import_id"]
    assert (await client.get(path, headers=bob_headers)).status_code == 404
    assert (await client.get(path, headers=alice_headers)).json()["data"]["status"] == "pending"
    bad = await client.post(
        base + "/cad-imports", headers=alice_headers, json={**body, "expected_revision": "other"}
    )
    assert bad.status_code == 409


async def test_materialize_retains_static_metres_and_refresh_binding(
    db, client, alice_headers, scene, app, monkeypatch
):
    import uuid
    from unittest.mock import AsyncMock

    from solus_api.connectors import step_tessellation
    from solus_api.livebench.scene.cad_import import materialize, propose
    from solus_api.livebench.scene.service import SceneService
    from solus_api.models import GraphEntity

    base, _, leaf, model, _ = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [0, -1, 0, 100, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    # Resolve the real authenticated fixture user ID, rather than external subject.
    user = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    service = SceneService(db, leaf.project_id, uuid.UUID(user["id"]))
    row = await propose(service, uuid.UUID(model["robot_id"]), leaf.id, "r1")
    await db.commit()
    monkeypatch.setattr(
        step_tessellation,
        "tessellate_isolated",
        AsyncMock(return_value={"shape": {"vertices": [0.001, 0, 0] * 3}}),
    )
    await materialize(service, row, {("doc", "element"): ("r1", "EXACT")}, app.state.artifact_store)
    await db.commit()
    saved = await db.get(GraphEntity, uuid.UUID(row.attrs["model_id"]))
    assert saved.attrs["model"]["joints"] == []
    assert "static" in saved.attrs["model"]["warnings"][0]
    mesh = next(iter(saved.attrs["model"]["meshes"].values()))
    assert mesh["vertices"][:3] == pytest.approx([0.1, 0.001, 0])
    assert saved.attrs["cad_bindings"][0]["source_entity_id"] == str(leaf.id)
    assert (await service.output(saved))["source_current"] is True
    from solus_api.livebench.scene import cad_refresh
    from solus_api.models import JobStatus, Sync, SyncTrigger
    from sqlalchemy.ext.asyncio import async_sessionmaker

    source = scene[1]
    leaf.attrs = {
        **leaf.attrs,
        "observed_microversion": "r2",
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 200, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    leaf.version += 1
    sync = Sync(
        source_id=source.id,
        project_id=source.project_id,
        trigger=SyncTrigger.MANUAL,
        status=JobStatus.SUCCEEDED,
    )
    db.add(sync)
    await db.commit()
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(
        cad_refresh,
        "tessellate_isolated",
        AsyncMock(return_value={"shape": {"vertices": [0.001, 0, 0] * 3}}),
    )
    async with maker() as session:
        plan = await cad_refresh.prepare(session, source.id)
    plan.capture.observe("doc", "element", "r2", "EXACT NEW")
    await cad_refresh.complete(maker, app.state.artifact_store, plan, sync.id, None)
    await db.refresh(saved)
    assert saved.attrs["source_revision"] == "r2"
    assert (await service.output(saved))["source_current"] is True
    updated = next(iter(saved.attrs["model"]["meshes"].values()))
    assert updated["vertices"][:3] == pytest.approx([0.201, 0, 0])


async def test_assembly_cycles_refused(client, alice_headers, db, scene):
    from solus_api.models import GraphEdge

    base, _, leaf, model, _ = scene
    leaf.attrs = {
        **leaf.attrs,
        "is_assembly": True,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    db.add(
        GraphEdge(
            project_id=leaf.project_id,
            src_id=leaf.id,
            dst_id=leaf.id,
            relation_type="part_of",
            domain_pair="mechanical<->mechanical",
            origin="connector",
        )
    )
    await db.commit()
    result = await client.post(
        base + "/cad-imports",
        headers=alice_headers,
        json={
            "robot_id": model["robot_id"],
            "source_entity_id": str(leaf.id),
            "expected_revision": "r1",
        },
    )
    assert result.status_code == 422


async def test_import_rejects_unauthenticated_and_paths(client, alice_headers, scene):
    base, _, leaf, model, _ = scene
    body = {
        "robot_id": model["robot_id"],
        "source_entity_id": str(leaf.id),
        "expected_revision": "r1",
    }
    assert (await client.post(base + "/cad-imports", json=body)).status_code == 401
    assert (
        await client.post(
            base + "/cad-imports", headers=alice_headers, json={**body, "path": "/tmp/x.step"}
        )
    ).status_code == 422


async def test_foreign_team_cannot_create_or_enqueue_import(client, bob_headers, db, scene):
    from conftest import me
    from solus_api.livebench.scene.cad_import import IMPORT_KIND
    from solus_api.models import GraphEntity
    from sqlalchemy import func, select

    base, _, leaf, model, enqueue = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    await me(client, bob_headers)
    count = (
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == leaf.project_id, GraphEntity.kind == IMPORT_KIND)
    )
    before = await db.scalar(count)
    result = await client.post(
        base + "/cad-imports",
        headers=bob_headers,
        json={
            "robot_id": model["robot_id"],
            "source_entity_id": str(leaf.id),
            "expected_revision": "r1",
        },
    )
    assert result.status_code == 404, result.text
    assert await db.scalar(count) == before
    enqueue.assert_not_awaited()


async def test_sol_import_previews_real_source_and_waits_for_invocation(
    client, alice_headers, db, scene
):
    import uuid
    from unittest.mock import AsyncMock

    from conftest import me
    from solus_api.agent.tools.bench_scene import build_bench_scene_tools
    from solus_api.livebench.scene.service import SceneService
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _, _, leaf, model, _ = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    user = await me(client, alice_headers)
    service = SceneService(db, leaf.project_id, uuid.UUID(user["id"]))

    async def queue(session, row):
        await session.commit()
        return uuid.uuid4()

    enqueue = AsyncMock(side_effect=queue)
    tools = {
        tool.descriptor.name: tool
        for tool in build_bench_scene_tools(
            async_sessionmaker(db.bind, expire_on_commit=False),
            service.project_id,
            service.user_id,
            enqueue,
        )
    }
    tool = tools["bench.import_cad_scene"]
    args = {
        "robot_id": model["robot_id"],
        "source_entity_id": str(leaf.id),
        "expected_revision": "r1",
    }
    preview = await tool.preview(args)
    assert tool.descriptor.requires_confirmation and tool.requires_complete_preview
    assert preview[1]["after"] == leaf.name
    assert preview[2]["after"] == "r1"
    enqueue.assert_not_awaited()
    result = await tool.invoke(args)
    assert result["status"] == "pending"
    assert (await tools["bench.cad_import_status"].invoke({"import_id": result["import_id"]}))[
        "status"
    ] == "pending"
    enqueue.assert_awaited_once()


async def test_assembly_source_picker_opt_in_keeps_mesh_binding_leaves(
    client, alice_headers, db, scene
):
    from solus_api.models import GraphEdge, GraphEntity

    base, _, leaf, _, _ = scene
    transform = {"length_unit": "mm", "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    leaf.attrs = {**leaf.attrs, "parent_transform": transform}
    leaf.external_ref = "doc:element:root/child"
    root = GraphEntity(
        project_id=leaf.project_id,
        source_id=leaf.source_id,
        kind=leaf.kind,
        domain=leaf.domain,
        origin="connector",
        name="Root",
        external_ref="doc:element:root",
        attrs={**leaf.attrs, "is_assembly": True},
    )
    db.add(root)
    await db.flush()
    db.add(
        GraphEdge(
            project_id=leaf.project_id,
            src_id=leaf.id,
            dst_id=root.id,
            relation_type="part_of",
            domain_pair="mechanical<->mechanical",
            origin="connector",
        )
    )
    await db.commit()
    ordinary = (await client.get(base + "/cad-sources", headers=alice_headers)).json()["data"][
        "sources"
    ]
    expanded = (
        await client.get(base + "/cad-sources?include_assemblies=true", headers=alice_headers)
    ).json()["data"]["sources"]
    assert {row["id"] for row in ordinary} == {str(leaf.id)}
    assert {row["id"] for row in expanded} == {str(leaf.id), str(root.id)}


async def test_import_limit_failure_has_safe_reason(
    db, client, alice_headers, scene, app, monkeypatch
):
    import uuid
    from unittest.mock import AsyncMock

    from solus_api.connectors import step_tessellation
    from solus_api.livebench.scene import cad_refresh
    from solus_api.livebench.scene.cad_import import propose
    from solus_api.livebench.scene.service import SceneService
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _, source, leaf, model, _ = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    user = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    service = SceneService(db, leaf.project_id, uuid.UUID(user["id"]))
    row = await propose(service, uuid.UUID(model["robot_id"]), leaf.id, "r1")
    await db.commit()
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        plan = await cad_refresh.prepare(session, source.id)
    plan.capture.observe("doc", "element", "r1", "EXACT")
    monkeypatch.setattr(
        step_tessellation,
        "tessellate_isolated",
        AsyncMock(side_effect=step_tessellation.CadGeometryError()),
    )
    await cad_refresh.complete_imports(maker, app.state.artifact_store, plan, True)
    await db.refresh(row)
    assert row.attrs["status"] == "error"
    assert row.attrs["reason"] == "CAD geometry exceeds the bounded display limits."
    assert row.attrs["model_id"] is None
