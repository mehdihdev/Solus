"""SOLUSDEV-322 P6-T2 — `simulation/model_job.py`: the generation job. From the CAD import's scene
model and the graph it gathers the placed mate frames, masses, limits, the actuated set and sensor
sites into a gap report; writes URDF, meshes and (when the engine builds it) MJCF into the artifact
store; mints one `joint` entity per generated joint; and registers a `simulation_model` v2 with
`origin="system"`. A rerun with the same inputs reuses the model. A mate whose frame or limits
are a gap is a FIXED attachment, never a moving joint (plan §0 row 18): the part keeps its CAD
place and the gap names what would free it. Every input here is scripted graph state: no CAD
call, no simulator.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.isaac_models import SimulationModel
from solus_api.graph import kinds
from solus_api.hardware.config import (
    BusMapEntry,
    EntityHardwareConfig,
    FieldProvenance,
    PartConfig,
    PartLimits,
    ProvenanceRecord,
)
from solus_api.hardware.store import put_entity_config
from solus_api.livebench.scene.cad_import import materialize, propose
from solus_api.livebench.scene.service import SceneService
from solus_api.models import (
    Artifact,
    Domain,
    GraphEdge,
    GraphEntity,
    Source,
    SourceStatus,
    SourceType,
)
from solus_api.simulation.model_job import (
    JOB,
    GenerateModelRequest,
    gap_report,
    gather,
    joint_limits,
    regeneration_requests,
    run_generate_sim_model,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_urdf_writer import box_vertices

Maker = async_sessionmaker[AsyncSession]
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
REVISION = {"document_id": "doc", "element_id": "element", "observed_microversion": "r1"}
FRAME = {
    "origin_m": [0.0, 0.0, 0.05],
    "x_axis": [1.0, 0.0, 0.0],
    "y_axis": [0.0, 1.0, 0.0],
    "z_axis": [0.0, 0.0, 1.0],
}
#: Closed boxes: the base carries a cached CAD mass, the arm a material density, the tip nothing.
MESHES = {
    "base": box_vertices(0.1, 0.1, 0.05, cz=0.025),
    "arm": box_vertices(0.02, 0.02, 0.2, cz=0.15),
    "tip": box_vertices(0.02, 0.02, 0.02, cz=0.26),
}
ATTRS: dict[str, dict[str, Any]] = {
    "base": {"mass_properties": {"mass_kg": 1.5}},
    "arm": {"material": {"name": "PLA", "density_kg_m3": 1000.0}},
    "tip": {},
}


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


class CadArm:
    def __init__(
        self, project_id: uuid.UUID, user_id: uuid.UUID, robot: GraphEntity, parts: dict[str, Any]
    ) -> None:
        self.project_id, self.user_id, self.robot, self.parts = project_id, user_id, robot, parts
        self.root: GraphEntity = parts["root"]

    def request(self, **extra: Any) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id),
            "robot_id": str(self.robot.id),
            "name": "Arm",
            "requested_by": str(self.user_id),
            **extra,
        }


def _mate(src: GraphEntity, dst: GraphEntity, feature: str, frame: bool) -> GraphEdge:
    attrs: dict[str, Any] = {"mate_type": "REVOLUTE", "feature_id": feature}
    if frame:
        attrs["mate_frame"] = FRAME
    return GraphEdge(
        project_id=src.project_id,
        source_id=src.source_id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type="mates_with",
        domain_pair="mechanical<->mechanical",
        origin="connector",
        attrs=attrs,
    )


async def cad_arm(
    db: AsyncSession,
    client: AsyncClient,
    headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    frames: tuple[bool, bool] = (True, True),
    limits: bool = True,
) -> CadArm:
    """A connected CAD source, a robot, a three-leaf assembly (base ⟶ arm ⟶ tip, two revolute
    mates) and its materialized scene model with closed box meshes."""
    from solus_api.connectors import step_tessellation

    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    pid, uid = uuid.UUID(project["id"]), uuid.UUID(user["id"])
    source = Source(
        project_id=pid,
        team_id=uuid.UUID(team["id"]),
        name="CAD",
        type=SourceType.ONSHAPE,
        status=SourceStatus.CONNECTED,
        secret_ref="test-reference",
        config={"documents": ["doc"]},
    )
    robot = GraphEntity(
        project_id=pid, kind=kinds.PHYSICAL_ROBOT, domain=Domain.RUNTIME, origin="manual", name="R"
    )
    db.add_all([source, robot])
    await db.flush()

    def cad(name: str, ref: str, **attrs: Any) -> GraphEntity:
        return GraphEntity(
            project_id=pid,
            source_id=source.id,
            kind="part",
            domain=Domain.MECHANICAL,
            origin="connector",
            name=name,
            external_ref=ref,
            attrs={
                **REVISION,
                "parent_transform": {"length_unit": "mm", "matrix": IDENTITY},
                **attrs,
            },
        )

    root = cad("Arm assembly", "doc:element:root", is_assembly=True)
    db.add(root)
    await db.flush()
    parts: dict[str, Any] = {"root": root}
    for name in ("base", "arm", "tip"):
        leaf = cad(name, f"doc:element:root/{name}", is_assembly=False, **ATTRS[name])
        db.add(leaf)
        await db.flush()
        db.add(
            GraphEdge(
                project_id=pid,
                source_id=source.id,
                src_id=leaf.id,
                dst_id=root.id,
                relation_type="part_of",
                domain_pair="mechanical<->mechanical",
                origin="connector",
            )
        )
        parts[name] = leaf
    db.add_all(
        [
            _mate(parts["base"], parts["arm"], "Fm1", frames[0]),
            _mate(parts["arm"], parts["tip"], "Fm2", frames[1]),
        ]
    )
    await db.commit()
    # The arm is the actuated part; its own config states the joint travel in radians.
    await put_entity_config(
        db,
        pid,
        robot,
        EntityHardwareConfig(
            entity_id=robot.id,
            bus_map=[BusMapEntry(protocol="fixture", address="3", part_entity_id=parts["arm"].id)],
            provenance={"bus_map": ProvenanceRecord(by=FieldProvenance.USER)},
        ),
        expected_version=0,
        created_by=uid,
    )
    if limits:
        await put_entity_config(
            db,
            pid,
            parts["arm"],
            EntityHardwareConfig(
                entity_id=parts["arm"].id,
                component=PartConfig(
                    limits=PartLimits(values={"position_min_rad": -1.2, "position_max_rad": 1.2})
                ),
                provenance={"component": ProvenanceRecord(by=FieldProvenance.USER)},
            ),
            expected_version=0,
            created_by=uid,
        )
    await db.commit()
    service = SceneService(db, pid, uid)
    row = await propose(service, robot.id, root.id, "r1")
    await db.commit()
    monkeypatch.setattr(
        step_tessellation,
        "tessellate_isolated",
        AsyncMock(return_value={f"root/{name}": {"vertices": MESHES[name]} for name in MESHES}),
    )
    await materialize(service, row, {("doc", "element"): ("r1", "EXACT")}, app.state.artifact_store)
    await db.commit()
    parts["scene_id"] = uuid.UUID(row.attrs["model_id"])
    return CadArm(pid, uid, robot, parts)


def _ctx(maker: Maker, app: FastAPI) -> dict[str, Any]:
    return {"sessionmaker": maker, "artifact_store": app.state.artifact_store}


async def _report(maker: Maker, arm: CadArm) -> dict[str, Any]:
    async with maker() as session:
        gathered = await gather(session, GenerateModelRequest.model_validate(arm.request()))
    return gap_report(gathered)


async def _models(maker: Maker, project_id: uuid.UUID) -> list[GraphEntity]:
    async with maker() as session:
        return list(
            await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.kind == kinds.SIMULATION_MODEL,
                    GraphEntity.deleted_at.is_(None),
                )
                .order_by(GraphEntity.id)
            )
        )


async def footprint(maker: Maker, *project_ids: uuid.UUID) -> list[tuple[int, int, int]]:
    """Per project: live (simulation_model, joint) entities and artifacts: what generation
    writes."""
    out = []
    async with maker() as session:
        for pid in project_ids:
            counts = []
            for kind in (kinds.SIMULATION_MODEL, kinds.JOINT):
                rows = await session.scalars(
                    select(GraphEntity.id).where(
                        GraphEntity.project_id == pid,
                        GraphEntity.kind == kind,
                        GraphEntity.deleted_at.is_(None),
                    )
                )
                counts.append(len(list(rows)))
            artifacts = await session.scalars(select(Artifact.id).where(Artifact.project_id == pid))
            out.append((counts[0], counts[1], len(list(artifacts))))
    return out


async def test_generated_joints_become_entities_the_model_binds_and_a_rerun_is_idempotent(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)

    first = await run_generate_sim_model(_ctx(maker, app), arm.request())

    assert first["status"] == "generated", first
    (model,) = await _models(maker, arm.project_id)
    assert model.origin == "system" and model.attrs["robot_id"] == str(arm.robot.id)
    assert model.attrs["cad_microversion"] == "r1"
    definition = SimulationModel.model_validate(model.attrs["simulation_model"])
    # Fm2 (arm → tip) has its frame but the tip has no limits: a fixed attachment and a gap.
    assert [joint.name for joint in definition.joints] == ["Fm1"]
    assert (definition.joints[0].lower_rad, definition.joints[0].upper_rad) == (-1.2, 1.2)
    assert "Fm2.limits" in {gap["name"] for gap in model.attrs["gaps"]}
    async with maker() as session:
        joints = list(
            await session.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == arm.project_id, GraphEntity.kind == kinds.JOINT
                )
            )
        )
        edges = list(await session.scalars(select(GraphEdge).where(GraphEdge.src_id == model.id)))
    by_name = {joint.name: joint for joint in joints}
    assert set(by_name) == {"Fm1"}
    assert {str(j.id) for j in joints} == {j.entity_id for j in definition.joints}
    elbow = by_name["Fm1"]
    assert elbow.origin == "system" and elbow.domain == Domain.SIMULATION
    assert elbow.attrs["parent_part_id"] == str(arm.parts["base"].id)
    assert elbow.attrs["child_part_id"] == str(arm.parts["arm"].id)
    assert elbow.attrs["actuator_part_id"] == str(arm.parts["arm"].id)
    assert elbow.attrs["axis"] == [0.0, 0.0, 1.0] and elbow.attrs["origin_m"] == [0.0, 0.0, 0.05]
    assert (elbow.attrs["lower"], elbow.attrs["upper"]) == (-1.2, 1.2)
    # The model root `contains` every link part and every joint entity.
    assert {str(edge.dst_id) for edge in edges} == set(definition.entity_ids())
    assert all(edge.relation_type == "contains" for edge in edges)

    again = await run_generate_sim_model(_ctx(maker, app), arm.request())

    assert again["status"] == "reused" and again["model_id"] == str(model.id)
    assert len(await _models(maker, arm.project_id)) == 1
    async with maker() as session:
        count = len(
            list(
                await session.scalars(
                    select(GraphEntity.id).where(
                        GraphEntity.project_id == arm.project_id, GraphEntity.kind == kinds.JOINT
                    )
                )
            )
        )
    assert count == 1


async def test_missing_mate_frame_is_a_gap_not_a_joint(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch, frames=(True, False))

    report = await _report(maker, arm)
    (frame_gap,) = [gap for gap in report["gaps"] if gap["name"] == "Fm2.frame"]
    assert "mate" in frame_gap["set_in"]
    assert [p["name"] for p in report["properties"] if p["name"].endswith(".frame")] == [
        "Fm1.frame"
    ]

    result = await run_generate_sim_model(_ctx(maker, app), arm.request())

    assert result["status"] == "generated"
    (model,) = await _models(maker, arm.project_id)
    definition = SimulationModel.model_validate(model.attrs["simulation_model"])
    assert [joint.name for joint in definition.joints] == ["Fm1"]
    assert "Fm2.frame" in {gap["name"] for gap in model.attrs["gaps"]}
    # No frame on any mate: nothing to register, and the report says why.
    arm2 = await cad_arm(db, client, alice_headers, app, monkeypatch, frames=(False, False))
    refused = await run_generate_sim_model(_ctx(maker, app), arm2.request())
    assert refused["status"] == "refused" and "joint" in refused["reason"]
    assert [gap["name"] for gap in refused["gaps"] if gap["name"].endswith(".frame")] == [
        "Fm1.frame",
        "Fm2.frame",
    ]
    assert await _models(maker, arm2.project_id) == []


async def test_masses_source_order_onshape_then_mesh_then_gap(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)

    report = await _report(maker, arm)

    masses = {p["name"]: p for p in report["properties"] if p["name"].endswith(".mass")}
    assert masses["base.mass"] == {
        "name": "base.mass",
        "value": 1.5,
        "unit": "kg",
        "source": "cad_mass",
    }
    assert masses["arm.mass"]["source"] == "mesh_mass"
    assert masses["arm.mass"]["value"] == pytest.approx(1000.0 * 0.02 * 0.02 * 0.2)
    assert "tip.mass" not in masses
    (gap,) = [gap for gap in report["gaps"] if gap["name"] == "tip.mass"]
    assert "mass_properties" in gap["set_in"] and "density" in gap["set_in"]
    # Limits: the arm's config in radians; the tip has no actuator and no limits.
    limits = {p["name"]: p for p in report["properties"] if p["name"].endswith(".limits")}
    assert limits["Fm1.limits"] == {
        "name": "Fm1.limits",
        "value": [-1.2, 1.2],
        "unit": "rad",
        "source": "user_config",
    }
    assert "Fm2.limits" in {gap["name"] for gap in report["gaps"]}
    assert {
        p["name"]: p["value"] for p in report["properties"] if p["name"].endswith(".actuated")
    } == {"Fm1.actuated": "fixture 3"}


def test_joint_limits_read_the_config_then_the_definition_then_nothing() -> None:
    from solus_api.hardware.library import PartDefinition, PartLimitsSpec, TelemetrySpec

    deg = PartDefinition(
        id="d",
        name="D",
        category="actuators",
        limits=PartLimitsSpec(position_min=-90, position_max=90),
        telemetry=[TelemetrySpec(quantity="position", unit="deg")],
    )
    config = PartLimits(values={"position_min_deg": -30, "position_max_deg": 60})
    configured = joint_limits("revolute", config, deg)
    assert configured is not None and configured[2] == "user_config"
    assert configured[:2] == pytest.approx((-0.5235987756, 1.0471975512))
    defined = joint_limits("revolute", None, deg)
    assert defined is not None and defined[2] == "definition"
    assert defined[:2] == pytest.approx((-1.5707963268, 1.5707963268))
    unitless = deg.model_copy(update={"telemetry": []})
    assert joint_limits("revolute", None, unitless) is None
    assert joint_limits(
        "prismatic", PartLimits(values={"position_min_mm": 0, "position_max_mm": 50}), None
    ) == (
        0.0,
        0.05,
        "user_config",
    )
    assert (
        joint_limits(
            "revolute", PartLimits(values={"position_min_rad": 1, "position_max_rad": 1}), None
        )
        is None
    )


async def test_model_files_land_in_the_artifact_store_with_a_manifest_sha256(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)

    result = await run_generate_sim_model(_ctx(maker, app), arm.request())

    assert result["status"] == "generated", result
    (model,) = await _models(maker, arm.project_id)
    definition = SimulationModel.model_validate(model.attrs["simulation_model"])
    stored = model.attrs["artifacts"]
    assert set(stored) == {"urdf", "mjcf", "meshes"} and stored["mjcf"] is not None
    assert set(stored["meshes"]) == {"meshes/base.stl", "meshes/arm.stl", "meshes/tip.stl"}
    assert definition.asset.urdf_path == "model.urdf"
    ids = {**stored["meshes"], "model.urdf": stored["urdf"]}
    assert set(ids) == set(definition.asset.files)
    store = app.state.artifact_store
    for path, artifact_id in ids.items():
        data = await store.get(artifact_id)
        assert hashlib.sha256(data).hexdigest() == definition.asset.files[path], path
        async with maker() as session:
            row = await session.get(Artifact, uuid.UUID(artifact_id))
        assert row is not None and row.retained and row.project_id == arm.project_id
    manifest = json.dumps(definition.asset.files, sort_keys=True, separators=(",", ":")).encode()
    assert definition.asset.sha256 == hashlib.sha256(manifest).hexdigest()
    # The MJCF is one the scene parser accepts, with the meshes the manifest names.
    from solus_api.livebench.scene.parser import parse_model

    meshes = {path: await store.get(stored["meshes"][path]) for path in stored["meshes"]}
    parsed = parse_model(await store.get(stored["mjcf"]), "mjcf", meshes)
    # The engine keeps the fixed tip as a jointless body; the scene parser names that attachment.
    assert [joint["name"] for joint in parsed["joints"]] == ["Fm1", "tip:fixed"]
    assert [link["name"] for link in parsed["links"]] == ["base", "arm", "tip"]
    assert not any(gap["name"] == "mjcf" for gap in model.attrs["gaps"])
    assert JOB == "run_generate_sim_model"


async def test_cad_microversion_change_enqueues_regeneration_and_keeps_the_old_model(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.livebench.scene import cad_refresh
    from solus_api.models import JobStatus, Sync, SyncTrigger

    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)
    first = await run_generate_sim_model(_ctx(maker, app), arm.request())
    assert first["status"] == "generated", first

    # The refresh itself is not under test: a successful one leaves the scene at the new revision.
    async def refreshed(maker_: Maker, store: Any, plan: Any, model: Any) -> None:
        async with maker_() as session:
            scene = await session.get(GraphEntity, model.identity)
            assert scene is not None
            scene.attrs = {**scene.attrs, "source_revision": "r2"}
            scene.version += 1
            await session.commit()

    monkeypatch.setattr(cad_refresh, "refresh_model", refreshed)
    source_id = arm.root.source_id
    assert source_id is not None
    sync = Sync(
        source_id=source_id,
        project_id=arm.project_id,
        trigger=SyncTrigger.MANUAL,
        status=JobStatus.SUCCEEDED,
    )
    db.add(sync)
    await db.commit()
    async with maker() as session:
        plan = await cad_refresh.prepare(session, source_id)
    assert [model.identity for model in plan.models] == [arm.parts["scene_id"]]
    plan.capture.observe("doc", "element", "r2", "STEP")
    enqueue = AsyncMock(return_value="job-2")

    await cad_refresh.complete(
        maker, app.state.artifact_store, plan, sync.id, None, enqueue=enqueue
    )

    enqueue.assert_awaited_once_with(
        JOB,
        str(arm.project_id),
        {
            "project_id": str(arm.project_id),
            "robot_id": str(arm.robot.id),
            "name": "Arm",
            "requested_by": str(arm.user_id),
            "source_entity_id": str(arm.root.id),
        },
    )
    (model,) = await _models(maker, arm.project_id)
    assert str(model.id) == first["model_id"] and model.attrs["cad_microversion"] == "r1"
    assert model.deleted_at is None, "the old model stays until the job registers the new one"
    # Without a queue the refresh completes as before and queues nothing.
    await cad_refresh.complete(maker, app.state.artifact_store, plan, sync.id, None)
    enqueue.assert_awaited_once()


async def test_a_request_pairing_a_project_with_a_foreign_robot_is_refused_and_writes_nothing(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant isolation (CLAUDE.md §7): the job reads only the request's project. Project A paired
    with project B's robot — or B's assembly — is a refusal, and neither project gains a model, a
    joint or an artifact."""
    mine = await cad_arm(db, client, alice_headers, app, monkeypatch)
    theirs = await cad_arm(db, client, bob_headers, app, monkeypatch)
    before = await footprint(maker, mine.project_id, theirs.project_id)
    foreign = [
        mine.request(robot_id=str(theirs.robot.id)),
        mine.request(robot_id=str(theirs.robot.id), source_entity_id=str(theirs.root.id)),
        mine.request(source_entity_id=str(theirs.root.id)),
    ]

    for request in foreign:
        result = await run_generate_sim_model(_ctx(maker, app), request)
        assert result["status"] == "refused" and "CAD" in result["reason"], request
        assert result["gaps"] == []

    assert await footprint(maker, mine.project_id, theirs.project_id) == before
    assert await _models(maker, mine.project_id) == []


async def test_regeneration_never_queues_another_projects_model_over_this_scene(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A system model in project B whose `attrs.scene_model_id` claims project A's scene is never
    a regeneration of A's refresh: `regeneration_requests` reads the scene's project only."""
    mine = await cad_arm(db, client, alice_headers, app, monkeypatch)
    theirs = await cad_arm(db, client, bob_headers, app, monkeypatch)
    first = await run_generate_sim_model(_ctx(maker, app), mine.request())
    assert first["status"] == "generated", first
    db.add(
        GraphEntity(
            project_id=theirs.project_id,
            kind=kinds.SIMULATION_MODEL,
            domain=Domain.SIMULATION,
            origin="system",
            name="Theirs",
            attrs={
                "scene_model_id": str(mine.parts["scene_id"]),
                "cad_microversion": "r0",
                "robot_id": str(theirs.robot.id),
                "requested_by": str(theirs.user_id),
                "source_entity_id": str(theirs.root.id),
            },
        )
    )
    await db.commit()
    async with maker() as session:
        scene = await session.get(GraphEntity, mine.parts["scene_id"])
        assert scene is not None
        scene.attrs = {**scene.attrs, "source_revision": "r2"}
        await session.commit()

    async with maker() as session:
        scene = await session.get(GraphEntity, mine.parts["scene_id"])
        assert scene is not None
        requests = await regeneration_requests(session, scene)

    assert requests == [mine.request(source_entity_id=str(mine.root.id))]
