"""SOLUSDEV-322 P5-T3: `robot_of_part` — the live robot a resolved part belongs to, so a sim
session can bind to the robot its packets describe. P5-T4: `record_sim_run` — a routine's readback
becomes a Run (`origin="sim"`) on that robot and a rung-4 `sim_result`; `POST …/pin`."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import BOB, add_member, me
from fixtures.fake_arm import DEVICE_REF, seed_fake_arm
from httpx import AsyncClient
from pydantic import ValidationError
from solus_api.agent.tools.gazebo_tools import gazebo_routine_readback
from solus_api.agent.tools.isaac_tools import isaac_routine_readback
from solus_api.graph import kinds
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.edges import write_edge
from solus_api.graph.live import LiveHub
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.models import RunSummary
from solus_api.livebench.sim_runs import (
    NO_ROBOT,
    JointSample,
    SimRunOutcome,
    part_robot_lookup,
    record_sim_run,
    robot_of_part,
    sim_run_hook,
)
from solus_api.models import Domain, GraphEntity, User
from solus_api.simulation.sessions_ledger import SessionsLedger, SimSessionRecord
from solus_api.storage import LocalArtifactStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_hardware_router import _hw_project
from test_solus_layer import _project

Maker = async_sessionmaker[AsyncSession]


def _node(project: uuid.UUID, kind: str, name: str, **attrs: object) -> GraphEntity:
    return GraphEntity(
        project_id=project,
        kind=kind,
        domain=Domain.PROJECT,
        origin="manual",
        name=name,
        attrs=attrs,
    )


async def _edge(
    db: AsyncSession, project: uuid.UUID, src: uuid.UUID, dst: uuid.UUID, relation: str
) -> None:
    await write_edge(
        db,
        project_id=project,
        src_id=src,
        dst_id=dst,
        relation_type=relation,
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=None,
    )


async def _contains(db: AsyncSession, project: uuid.UUID, src: uuid.UUID, dst: uuid.UUID) -> None:
    await _edge(db, project, src, dst, "contains")


async def _part_of(
    db: AsyncSession, project: uuid.UUID, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """`part_of` runs child -> parent (connectors/mechanical.py, scene/cad_import.children)."""
    await _edge(db, project, child, parent, "part_of")


async def test_robot_of_part_finds_the_live_root_above_a_part(engine: AsyncEngine) -> None:
    """Directly contained (the fake arm) or through a category node: the one live robot root."""
    maker = _maker(engine)
    project = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        category = _node(project, kinds.ROBOT_CATEGORY, "actuators", robot_id=str(arm.robot))
        nested = _node(project, kinds.PART, "nested servo")
        db.add_all([category, nested])
        await db.flush()
        await _contains(db, project, arm.robot, category.id)
        await _contains(db, project, category.id, nested.id)
        await db.commit()

        assert await robot_of_part(db, project, arm.parts[0]) == arm.robot
        assert await robot_of_part(db, project, nested.id) == arm.robot
        # another project's view of the same part: no edges, no robot
        assert await robot_of_part(db, uuid.uuid4(), arm.parts[0]) is None


async def test_robot_of_part_is_none_without_exactly_one_live_root(engine: AsyncEngine) -> None:
    """A part nobody contains, a part two robots contain, and a part whose root is not a live
    manual robot (a connector's node) all answer None — never a guess."""
    maker = _maker(engine)
    project = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        bare = _node(project, kinds.PART, "bare")
        second_robot = _node(project, kinds.PHYSICAL_ROBOT, "second robot")
        synced_root = GraphEntity(
            project_id=project,
            kind=kinds.PHYSICAL_ROBOT,
            domain=Domain.PROJECT,
            origin="connector",
            name="synced robot",
        )
        synced_part = _node(project, kinds.PART, "synced part")
        db.add_all([bare, second_robot, synced_root, synced_part])
        await db.flush()
        await _contains(db, project, second_robot.id, arm.parts[1])  # servo 2: two robots
        await _contains(db, project, synced_root.id, synced_part.id)
        await db.commit()

        assert await robot_of_part(db, project, bare.id) is None
        assert await robot_of_part(db, project, arm.parts[1]) is None
        assert await robot_of_part(db, project, synced_part.id) is None
        assert await robot_of_part(db, project, arm.parts[0]) == arm.robot  # the rest still bind


async def test_robot_of_part_walks_part_of_upward(engine: AsyncEngine) -> None:
    """`robot -contains-> assembly <-part_of- part` binds the part to the robot: `part_of` is
    read child -> parent, the orientation the CAD connector writes. The walk never descends:
    an assembly whose sub-part another robot contains still has exactly one root, and a
    `part_of` edge written in the wrong direction (assembly -> part) owns nothing."""
    maker = _maker(engine)
    project = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        assembly = _node(project, kinds.PART, "gripper assembly")
        part = _node(project, kinds.PART, "gripper finger")
        sub = _node(project, kinds.PART, "finger pad")
        other_robot = _node(project, kinds.PHYSICAL_ROBOT, "other robot")
        inverted = _node(project, kinds.PART, "inverted")
        db.add_all([assembly, part, sub, other_robot, inverted])
        await db.flush()
        await _contains(db, project, arm.robot, assembly.id)
        await _part_of(db, project, part.id, assembly.id)
        await _part_of(db, project, sub.id, assembly.id)
        await _contains(db, project, other_robot.id, sub.id)
        await _part_of(db, project, assembly.id, inverted.id)  # assembly -> inverted: wrong way
        await db.commit()

        assert await robot_of_part(db, project, part.id) == arm.robot
        assert await robot_of_part(db, project, assembly.id) == arm.robot
        assert await robot_of_part(db, project, inverted.id) is None


async def test_part_robot_lookup_opens_its_own_session(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        await db.commit()
    lookup = part_robot_lookup(maker)
    assert await lookup(project, arm.parts[2]) == arm.robot
    assert await lookup(project, uuid.uuid4()) is None


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


# ----------------------------------------------------------------------- P5-T4 sim runs

ELBOW = "demo/arm1/elbow"
ROUTINE: dict[str, Any] = {
    "model": "arm1",
    "routine": "sweep",
    "duration_s": 2.0,
    "sweep": {"joint": "elbow", "lower": -0.5, "upper": 0.5, "speed_rad_s": 0.5},
}


def _packet(device_id: str) -> TelemetryPacket:
    return TelemetryPacket(
        device_id=device_id,
        timestamp=datetime(2026, 11, 9, tzinfo=UTC),
        values={"elbow.position": 0.1},
        units={"elbow.position": "rad"},
    )


def _samples(
    device_id: str, joint: str, positions: list[float], *, target: float | None
) -> list[JointSample]:
    return [
        JointSample(
            device_id=device_id,
            joint=joint,
            t_s=index * 0.5,
            position=position,
            velocity=0.0,
            target=target,
        )
        for index, position in enumerate(positions)
    ]


async def _alias(db: AsyncSession, part_id: uuid.UUID, *aliases: tuple[str, str]) -> None:
    part = await db.get(GraphEntity, part_id)
    assert part is not None
    part.attrs = {
        **part.attrs,
        "sim_aliases": [{"provider": p, "device_id": d} for p, d in aliases],
    }
    await db.commit()


async def _arm(
    engine: AsyncEngine, *aliases: tuple[str, str]
) -> tuple[Maker, uuid.UUID, Any, uuid.UUID]:
    """A project with the fake arm, servo 3 aliased as given, and a user to file runs as."""
    maker = _maker(engine)
    project = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        user = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="sim@example.com")
        db.add(user)
        await db.commit()
        if aliases:
            await _alias(db, arm.parts[2], *aliases)
        return maker, project, arm, user.id


async def _run_count(maker: Maker, project: uuid.UUID) -> int:
    async with maker() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.project_id == project, GraphEntity.kind == run_store.RUN_KIND)
        )
        return int(count or 0)


async def _record(
    maker: Maker,
    project: uuid.UUID,
    store: LocalArtifactStore,
    user: uuid.UUID,
    samples: list[JointSample],
    *,
    model_entity_id: uuid.UUID | None = None,
) -> SimRunOutcome:
    return await record_sim_run(
        maker,
        LiveHub(),
        store,
        project_id=project,
        provider="gazebo",
        family="gz",
        version="8.15.0",
        model_entity_id=model_entity_id,
        scene_ref="demo.sdf",
        routine_args=ROUTINE,
        samples=samples,
        created_by=user,
    )


async def test_same_elbow_resolves_to_one_part_across_mujoco_gazebo_isaac_and_real(
    engine: AsyncEngine,
) -> None:
    """Through the ONE ingest path: the MuJoCo session's `<scene>/elbow`, the Gazebo fixture's
    `<world>/<model>/elbow` and Isaac's readback keyed by the joint entity id all land, under
    their session's `source`, on the part the real bus packet lands on by `external_ref`. An
    unmapped `wrist` stays unresolved, and a real session never reads an alias."""
    joint_entity = str(uuid.uuid4())
    maker, project, arm, _ = await _arm(
        engine, ("mujoco", "arm/elbow"), ("gazebo", ELBOW), ("isaac", joint_entity)
    )
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker))

    async def ingest(device_id: str, source: str | None) -> uuid.UUID | None:
        return (await plumbing.ingest(project, _packet(device_id), source=source)).entity_id

    elbow = arm.parts[2]
    assert await ingest("arm/elbow", "mujoco") == elbow
    assert await ingest(ELBOW, "gazebo") == elbow
    assert await ingest(joint_entity, "isaac") == elbow
    assert await ingest(f"{DEVICE_REF}/3", None) == elbow
    assert await ingest("demo/arm1/wrist", "gazebo") is None
    assert await ingest("arm/elbow", None) is None


async def test_routine_result_becomes_a_sim_run_with_inputs_in_attrs(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    maker, project, arm, user = await _arm(engine, ("gazebo", ELBOW))
    store = LocalArtifactStore(str(tmp_path / "artifacts"))

    outcome = await _record(
        maker, project, store, user, _samples(ELBOW, "elbow", [0.1, 0.3, 0.48], target=0.5)
    )

    assert outcome.reason is None and outcome.run_id is not None
    async with maker() as db:
        record = await run_store.record(db, project, outcome.run_id)
        read = run_store.summary(record)
        assert (read.origin, read.status, read.robot_id, read.packet_count) == (
            "sim",
            "completed",
            arm.robot,
            3,
        )
        assert read.session_id is None and read.artifact_id is not None
        assert (read.baseline, read.pinned) == (False, False)
        assert record.attrs["sim"] == {
            "provider": "gazebo",
            "family": "gz",
            "version": "8.15.0",
            "model_sha256": None,
            "scene_ref": "demo.sdf",
            "routine": ROUTINE,
        }
        assert record.attrs["findings_linked"] is False
        manifest = await run_store.load(db, store, record, user, 60)
    assert manifest.sim is not None and manifest.sim.provider == "gazebo"
    assert [(part.entity_id, part.device_id) for part in manifest.parts] == [(arm.parts[2], ELBOW)]
    assert (manifest.parts[0].position_signal, manifest.parts[0].position_unit) == (
        "elbow.position",
        "rad",
    )
    last = manifest.packets[-1]
    assert last.device_id == ELBOW
    assert last.values == {"elbow.position": 0.48, "elbow.velocity": 0.0}
    assert last.units == {"elbow.position": "rad", "elbow.velocity": "rad/s"}
    assert (last.timestamp - manifest.packets[0].timestamp).total_seconds() == pytest.approx(1.0)


async def test_no_bound_robot_records_nothing_and_says_why(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """A joint nobody mapped reaches no part, so no robot: no Run, no `sim_result`, a reason.
    No readback at all, or no user to file as, are reasons too."""
    maker, project, _, user = await _arm(engine)
    store = LocalArtifactStore(str(tmp_path / "artifacts"))

    samples = _samples(ELBOW, "elbow", [0.1], target=0.5)
    unmapped = await _record(maker, project, store, user, samples)
    empty = await _record(maker, project, store, user, [])
    nobody = await record_sim_run(
        maker,
        LiveHub(),
        store,
        project_id=project,
        provider="gazebo",
        family=None,
        version=None,
        model_entity_id=None,
        scene_ref=None,
        routine_args=ROUTINE,
        samples=samples,
        created_by=None,
    )

    assert unmapped == SimRunOutcome(None, None, NO_ROBOT)
    assert empty.run_id is None and empty.reason == "the routine returned no joint readback"
    assert nobody.run_id is None and nobody.reason == "no user to file the run as"
    assert await _run_count(maker, project) == 0


async def test_rung_4_sim_result_lands_expected_on_the_robot(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """The routine's tracking becomes a rung-4 `sim_result` on the ROBOT (§1.1-11): the largest
    final target error in radians, the provenance naming provider, family and version, the inputs
    carrying the model hash, the scene, the routine and the per-joint results; and the robot's
    `expected.joint_trajectory` points at it. A readback without a target files the Run and says
    why no fact was recorded. A model entity's `attrs.robot_id` binds the robot directly."""
    maker, project, arm, user = await _arm(engine, ("gazebo", ELBOW))
    store = LocalArtifactStore(str(tmp_path / "artifacts"))

    outcome = await _record(
        maker, project, store, user, _samples(ELBOW, "elbow", [0.1, 0.3, 0.48], target=0.5)
    )

    assert outcome.sim_result_id is not None
    async with maker() as db:
        fact = await db.get(GraphEntity, outcome.sim_result_id)
        robot = await db.get(GraphEntity, arm.robot, populate_existing=True)
    assert fact is not None and robot is not None
    assert (fact.kind, fact.attrs["rung"], fact.attrs["subject_id"]) == (
        kinds.SIM_RESULT,
        4,
        str(arm.robot),
    )
    assert fact.attrs["values"]["joint_trajectory"] == {
        "value": pytest.approx(0.02),
        "unit": "rad",
    }
    provenance = fact.attrs["provenance"]
    assert provenance["solver"] == "gazebo gz 8.15.0"
    assert set(provenance["inputs"]) == {"model_sha256", "scene_ref", "routine", "joints"}
    assert provenance["inputs"]["routine"] == {"value": ROUTINE, "source": "known"}
    assert provenance["inputs"]["joints"]["value"] == {
        "elbow": {"target": 0.5, "final": 0.48, "error": pytest.approx(0.02)}
    }
    assert provenance["leaves_out"]
    assert robot.attrs["expected"]["joint_trajectory"]["sim_result_id"] == str(
        outcome.sim_result_id
    )

    # no target in the readback: the Run is filed, the fact is not, and the reason says so
    untargeted = await _record(
        maker, project, store, user, _samples(ELBOW, "elbow", [0.1, 0.2], target=None)
    )
    assert untargeted.run_id is not None and untargeted.sim_result_id is None
    assert untargeted.reason == "no joint had a target to read back against"

    # a model entity whose attrs name the robot binds it without any mapped joint
    async with maker() as db:
        model = GraphEntity(
            project_id=project,
            kind=kinds.SIMULATION_MODEL,
            domain=Domain.SIMULATION,
            origin="system",
            name="generated arm",
            attrs={"robot_id": str(arm.robot), "simulation_model": {"asset": {"sha256": "a" * 64}}},
        )
        db.add(model)
        await db.commit()
        model_id = model.id
    bound = await _record(
        maker,
        project,
        store,
        user,
        _samples("demo/arm1/wrist", "wrist", [0.2], target=0.2),
        model_entity_id=model_id,
    )
    assert bound.run_id is not None and bound.sim_result_id is not None
    async with maker() as db:
        record = await run_store.record(db, project, bound.run_id)
    assert run_store.summary(record).robot_id == arm.robot
    assert record.attrs["sim"]["model_sha256"] == "a" * 64
    assert await _run_count(maker, project) == 3


# ------------------------------------------------------------- the wrappers' readback hook


def _gazebo_result(**overrides: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "session_id": "s-1",
        "world": "demo",
        "model": "arm1",
        "routine": "sweep",
        "family": "gz",
        "version": "8.15.0",
        "per_joint": {"elbow": {"target": 0.5, "final": 0.48, "error": 0.02}},
        "max_abs_error_rad": 0.02,
        "paused": False,
        "samples": [
            {"joint": "elbow", "position": 0.1, "velocity": 0.4, "sim_time_s": 10.0},
            {"joint": "elbow", "position": 0.48, "velocity": None, "sim_time_s": 10.5},
            {"joint": "elbow", "position": None, "velocity": None, "sim_time_s": 11.0},
        ],
        **overrides,
    }


def _ledger_session(scene_name: str | None) -> SimSessionRecord:
    return SimSessionRecord(
        project_id=uuid.uuid4(),
        provider="gazebo",
        session_id="s-1",
        owner="sol",
        started_by_call_id=None,
        scene_ref="worlds/demo.sdf",
        scene_name=scene_name,
        started_at=datetime(2026, 11, 9, tzinfo=UTC),
        ended_at=None,
    )


def test_gazebo_routine_readback_becomes_samples() -> None:
    """The device id is `<world>/<model>/<joint>` with the world from the LEDGER row and the
    model from the REQUEST; the companion's own `world`/`model` fields choose nothing."""
    args = {"session_id": "s-1", **ROUTINE}
    forged = _gazebo_result(world="other", model="arm2")
    read = gazebo_routine_readback(args, _gazebo_result(), session=_ledger_session("demo"))
    assert (read.family, read.version) == ("gz", "8.15.0")
    assert read.samples == [
        JointSample(ELBOW, "elbow", 10.0, 0.1, 0.4, 0.5),
        JointSample(ELBOW, "elbow", 10.5, 0.48, None, 0.5),
    ]
    with pytest.raises(ValueError, match="model"):
        gazebo_routine_readback(args, forged, session=_ledger_session("demo"))
    with pytest.raises(ValueError, match="world"):
        gazebo_routine_readback(args, _gazebo_result(), session=_ledger_session(None))
    with pytest.raises(ValueError, match="world"):
        gazebo_routine_readback(args, _gazebo_result())


def test_gazebo_routine_readback_keeps_only_the_requested_joints() -> None:
    """A sweep keeps its one joint; a trajectory keeps `joints`, else the waypoints' joints."""
    session = _ledger_session("demo")
    samples = [{"joint": j, "position": 0.1, "sim_time_s": 1.0} for j in ("elbow", "wrist")]
    sweep = gazebo_routine_readback(
        {"session_id": "s-1", **ROUTINE}, _gazebo_result(samples=samples), session=session
    )
    assert [s.device_id for s in sweep.samples] == [ELBOW]
    trajectory = {
        "model": "arm1",
        "routine": "joint_trajectory",
        "duration_s": 2.0,
        "waypoints": [{"t_s": 1.0, "positions": {"wrist": 0.2}}],
    }
    by_waypoints = gazebo_routine_readback(
        {"session_id": "s-1", **trajectory}, _gazebo_result(samples=samples), session=session
    )
    assert [s.device_id for s in by_waypoints.samples] == ["demo/arm1/wrist"]
    by_joints = gazebo_routine_readback(
        {"session_id": "s-1", **trajectory, "joints": ["elbow"]},
        _gazebo_result(samples=samples),
        session=session,
    )
    assert [s.device_id for s in by_joints.samples] == [ELBOW]


def _isaac_args(*joints: str) -> dict[str, Any]:
    """SOL's validated `isaac.run_routine` args: a trajectory of exactly these joints."""
    return {
        "session_id": str(uuid.UUID(int=7)),
        "routine": "joint_trajectory",
        "duration_s": 2,
        "joints": [{"joint_entity_id": j, "lower": -1.0, "upper": 1.0} for j in joints],
        "waypoints": [{"positions": [{"joint_entity_id": j, "position_rad": 0.2} for j in joints]}],
    }


def test_isaac_routine_readback_becomes_samples() -> None:
    """The reader yields samples only: which model the routine ran on is the wrapper's verified
    graph binding, never a field the companion echoes (see the red-team case below). The joint
    set is the REQUEST's (`joints[]` and every waypoint position): a joint the result adds is
    dropped from the waypoints, the final positions and the target errors alike; a request
    that is not a valid routine reads nothing."""
    joint, other, foreign = (str(uuid.uuid4()) for _ in range(3))
    trajectory = {
        "ok": True,
        "model_entity_id": str(uuid.uuid4()),
        "readback": {
            "targets_reached": True,
            "target_errors_rad": {joint: -0.01, other: 0.0, foreign: 0.0},
            "steps": 120,
            "waypoints": [
                {"waypoint": 1, "step": 60, "positions_rad": {joint: 0.2, other: 0.0, foreign: 0.3}}
            ],
            "positions_rad": {joint: 0.39, other: 0.0, foreign: 0.3},
        },
    }
    read = isaac_routine_readback(_isaac_args(joint, other), trajectory)
    assert read.family is None and not hasattr(read, "model_entity_id")
    assert read.samples[2].target == pytest.approx(0.4)
    assert [dataclasses.replace(sample, target=None) for sample in read.samples] == [
        JointSample(joint, joint, 1.0, 0.2),
        JointSample(other, other, 1.0, 0.0),
        JointSample(joint, joint, 2.0, 0.39),
        JointSample(other, other, 2.0, 0.0),
    ]
    with pytest.raises(ValidationError):
        isaac_routine_readback({"routine": "joint_trajectory"}, trajectory)
    sweep = {
        "ok": True,
        "readback": {
            "steps": 120,
            "final_position_rad": 0.3,
            "min_rad": -0.5,
            "max_rad": 0.5,
            "samples": [{"step": 60, "position_rad": 0.1}],
        },
    }
    args = {
        "session_id": str(uuid.UUID(int=7)),
        "routine": "sweep",
        "duration_s": 2,
        "sweep": {
            "articulation": "/World/arm",
            "joint": "elbow",
            "lower": -0.5,
            "upper": 0.5,
            "speed_rad_s": 0.1,
        },
    }
    assert isaac_routine_readback(args, sweep).samples == [
        JointSample("/World/arm/elbow", "elbow", 1.0, 0.1),
        JointSample("/World/arm/elbow", "elbow", 2.0, 0.3),
    ]


def _model_entity(project: uuid.UUID, robot: uuid.UUID, sha: str) -> GraphEntity:
    return GraphEntity(
        project_id=project,
        kind=kinds.SIMULATION_MODEL,
        domain=Domain.SIMULATION,
        origin="system",
        name=f"model of {robot}",
        attrs={"robot_id": str(robot), "simulation_model": {"asset": {"sha256": sha}}},
    )


async def test_hook_binds_the_run_to_the_verified_model_not_the_companions(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Red team: the fork's `run_routine` result names ANOTHER live model of this project. The
    wrapper hands the hook the model it verified against the graph digest, and the Run, its
    `model_sha256` provenance and the rung-4 fact all land on THAT model's robot; the decoy's
    robot gains no `expected`. The companion's word never chooses where a graph write lands."""
    maker, project, arm, user = await _arm(engine)
    store = LocalArtifactStore(str(tmp_path / "artifacts"))
    async with maker() as db:
        other_robot = _node(project, kinds.PHYSICAL_ROBOT, "other robot")
        db.add(other_robot)
        await db.flush()
        verified = _model_entity(project, arm.robot, "a" * 64)
        decoy = _model_entity(project, other_robot.id, "b" * 64)
        db.add_all([verified, decoy])
        await db.commit()
    hook = sim_run_hook(
        maker,
        LiveHub(),
        store,
        SessionsLedger(maker),
        project_id=project,
        provider="isaac",
        user_id=user,
        reader=isaac_routine_readback,
    )
    joint = str(uuid.uuid4())
    forged = {
        "ok": True,
        "model_entity_id": str(decoy.id),
        "readback": {
            "target_errors_rad": {joint: -0.01},
            "steps": 120,
            "waypoints": [{"step": 60, "positions_rad": {joint: 0.2}}],
            "positions_rad": {joint: 0.39},
        },
    }

    answered = await hook(_isaac_args(joint), forged, model_entity_id=verified.id)

    assert answered is not None and answered["run_reason"] is None, answered
    async with maker() as db:
        record = await run_store.record(db, project, uuid.UUID(answered["run"]))
        fact = await db.get(GraphEntity, uuid.UUID(answered["sim_result_id"]))
        decoy_robot = await db.get(GraphEntity, other_robot.id, populate_existing=True)
    assert run_store.summary(record).robot_id == arm.robot
    assert record.attrs["sim"]["model_sha256"] == "a" * 64
    assert fact is not None and fact.attrs["subject_id"] == str(arm.robot)
    assert decoy_robot is not None and "expected" not in decoy_robot.attrs
    assert await _run_count(maker, project) == 1


async def test_hook_files_the_run_and_answers_in_the_result(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """`GazeboTool.run_routine` hands the hook its native args and the fork's result: the hook
    files the Run under the session's ledger `scene_ref` and answers inside the result (`run`,
    `sim_result_id`, `run_reason`). A readback it cannot read, or a filing that fails, is a
    reason in the result — never an exception after a routine that ran."""
    maker, project, _, user = await _arm(engine, ("gazebo", ELBOW))
    store = LocalArtifactStore(str(tmp_path / "artifacts"))
    ledger = SessionsLedger(maker)
    await ledger.record_owned_start(
        project_id=project,
        provider="gazebo",
        session_id="s-1",
        call_id=None,
        scene_ref="worlds/demo.sdf",
        scene_name="demo",
        created_by=user,
    )
    hook = sim_run_hook(
        maker,
        LiveHub(),
        store,
        ledger,
        project_id=project,
        provider="gazebo",
        user_id=user,
        reader=gazebo_routine_readback,
    )

    answered = await hook({"session_id": "s-1", "dry_run": False, **ROUTINE}, _gazebo_result())
    unreadable = await hook({"session_id": "s-1", **ROUTINE}, {"ok": True, "samples": "nope"})

    assert answered is not None and answered["run_reason"] is None
    assert uuid.UUID(answered["run"]) and uuid.UUID(answered["sim_result_id"])
    async with maker() as db:
        record = await run_store.record(db, project, uuid.UUID(answered["run"]))
    assert record.attrs["sim"]["scene_ref"] == "worlds/demo.sdf"
    assert record.attrs["sim"]["routine"] == ROUTINE  # session_id and dry_run are not inputs
    assert unreadable is not None and unreadable["run"] is None
    assert unreadable["run_reason"] == "the routine readback was not understood"
    assert await _run_count(maker, project) == 1


async def test_hook_never_files_on_the_robot_a_forged_gazebo_readback_names(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Red team: the elbow of the fake arm is aliased `demo/arm1/elbow`; a second live robot's
    wrist is aliased `other/arm2/wrist`. SOL asked for a sweep of `arm1`/`elbow` in the owned
    `demo` world. The companion answers with the OTHER world, model and joint. A model that is
    not the requested one is refused (UNREADABLE); a foreign joint under the requested model is
    dropped, leaving no readback. Either way nothing is filed, and the decoy robot gains no Run
    and no `expected`."""
    maker, project, arm, user = await _arm(engine, ("gazebo", ELBOW))
    store = LocalArtifactStore(str(tmp_path / "artifacts"))
    async with maker() as db:
        decoy = _node(project, kinds.PHYSICAL_ROBOT, "other robot")
        wrist = _node(project, kinds.PART, "wrist")
        db.add_all([decoy, wrist])
        await db.flush()
        await _contains(db, project, decoy.id, wrist.id)
        await db.commit()
        await _alias(db, wrist.id, ("gazebo", "other/arm2/wrist"))
    ledger = SessionsLedger(maker)
    await ledger.record_owned_start(
        project_id=project,
        provider="gazebo",
        session_id="s-1",
        call_id=None,
        scene_ref="worlds/demo.sdf",
        scene_name="demo",
        created_by=user,
    )
    hook = sim_run_hook(
        maker,
        LiveHub(),
        store,
        ledger,
        project_id=project,
        provider="gazebo",
        user_id=user,
        reader=gazebo_routine_readback,
    )
    args = {"session_id": "s-1", **ROUTINE}
    wrist_samples = [{"joint": "wrist", "position": 0.2, "sim_time_s": 1.0}]
    per_joint = {"wrist": {"target": 0.2, "final": 0.2, "error": 0.0}}

    other_model = await hook(
        args,
        _gazebo_result(world="other", model="arm2", per_joint=per_joint, samples=wrist_samples),
    )
    other_joint = await hook(
        args, _gazebo_result(world="other", per_joint=per_joint, samples=wrist_samples)
    )

    assert other_model is not None and other_model["run"] is None
    assert other_model["run_reason"] == "the routine readback was not understood"
    assert other_joint is not None and other_joint["run"] is None
    assert other_joint["run_reason"] == "the routine returned no joint readback"
    assert await _run_count(maker, project) == 0
    async with maker() as db:
        for robot in (decoy.id, arm.robot):
            row = await db.get(GraphEntity, robot, populate_existing=True)
            assert row is not None and "expected" not in row.attrs


async def test_isaac_readback_keeps_the_requested_joints_and_never_the_decoys_robot(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Red team (P5-T4 review): the fork's trajectory readback names, next to the requested
    elbow, a joint entity of ANOTHER live robot of this project, and the verified model's
    `attrs.robot_id` is unset. The requested joint set is the API's own (the validated request),
    so the foreign joint is dropped before the run is filed: the Run lands on the fake arm, the
    rung-4 fact carries only the elbow, and the decoy robot gains no `expected`."""
    wrist_joint, elbow_joint = str(uuid.UUID(int=1)), str(uuid.UUID(int=2**127))
    maker, project, arm, user = await _arm(engine, ("isaac", elbow_joint))
    store = LocalArtifactStore(str(tmp_path / "artifacts"))
    async with maker() as db:
        decoy = _node(project, kinds.PHYSICAL_ROBOT, "other robot")
        wrist = _node(project, kinds.PART, "wrist")
        model = GraphEntity(
            project_id=project,
            kind=kinds.SIMULATION_MODEL,
            domain=Domain.SIMULATION,
            origin="system",
            name="unbound model",
            attrs={"simulation_model": {"asset": {"sha256": "a" * 64}}},
        )
        db.add_all([decoy, wrist, model])
        await db.flush()
        await _contains(db, project, decoy.id, wrist.id)
        await db.commit()
        await _alias(db, wrist.id, ("isaac", wrist_joint))
    hook = sim_run_hook(
        maker,
        LiveHub(),
        store,
        SessionsLedger(maker),
        project_id=project,
        provider="isaac",
        user_id=user,
        reader=isaac_routine_readback,
    )
    result = {
        "ok": True,
        "readback": {
            "target_errors_rad": {elbow_joint: -0.01, wrist_joint: 0.0},
            "steps": 120,
            "waypoints": [{"step": 60, "positions_rad": {elbow_joint: 0.2, wrist_joint: 0.3}}],
            "positions_rad": {elbow_joint: 0.39, wrist_joint: 0.3},
        },
    }

    answered = await hook(_isaac_args(elbow_joint), result, model_entity_id=model.id)

    assert answered is not None and answered["run_reason"] is None, answered
    async with maker() as db:
        record = await run_store.record(db, project, uuid.UUID(answered["run"]))
        fact = await db.get(GraphEntity, uuid.UUID(answered["sim_result_id"]))
        decoy_robot = await db.get(GraphEntity, decoy.id, populate_existing=True)
        manifest = await run_store.load(db, store, record, user, 60)
    assert run_store.summary(record).robot_id == arm.robot
    assert fact is not None and fact.attrs["subject_id"] == str(arm.robot)
    assert set(fact.attrs["provenance"]["inputs"]["joints"]["value"]) == {elbow_joint}
    assert {packet.device_id for packet in manifest.packets} == {elbow_joint}
    assert [part.entity_id for part in manifest.parts] == [arm.parts[2]]
    assert decoy_robot is not None and "expected" not in decoy_robot.attrs
    assert await _run_count(maker, project) == 1


async def test_hook_reports_an_unparseable_model_id_instead_of_raising(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """The wrapper hands the hook its verified model id as text; turning it into a UUID happens
    inside the hook's never-raises boundary, so a routine that ran is answered, not blown up."""
    maker, project, _, user = await _arm(engine, ("gazebo", ELBOW))
    ledger = SessionsLedger(maker)
    await ledger.record_owned_start(
        project_id=project,
        provider="gazebo",
        session_id="s-1",
        call_id=None,
        scene_ref="worlds/demo.sdf",
        scene_name="demo",
        created_by=user,
    )
    hook = sim_run_hook(
        maker,
        LiveHub(),
        LocalArtifactStore(str(tmp_path / "artifacts")),
        ledger,
        project_id=project,
        provider="gazebo",
        user_id=user,
        reader=gazebo_routine_readback,
    )

    answered = await hook(
        {"session_id": "s-1", **ROUTINE}, _gazebo_result(), model_entity_id="not-a-uuid"
    )

    assert answered is not None and answered["run"] is None
    assert answered["run_reason"] == "the run could not be filed"
    assert await _run_count(maker, project) == 0


async def test_solver_words_outside_the_allowed_alphabet_record_unknown(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """A companion-reported family or version is a solver WORD (`^[0-9A-Za-z.+-]{1,64}$`) or it
    is recorded as `unknown`: neither the run manifest nor `SimProvenance.solver` carries free
    text from the fork."""
    maker, project, _, user = await _arm(engine, ("gazebo", ELBOW))
    store = LocalArtifactStore(str(tmp_path / "artifacts"))

    outcome = await record_sim_run(
        maker,
        LiveHub(),
        store,
        project_id=project,
        provider="gazebo",
        family="gz\n",
        version="8.15.0; rm -rf /",
        model_entity_id=None,
        scene_ref="demo.sdf",
        routine_args=ROUTINE,
        samples=_samples(ELBOW, "elbow", [0.1, 0.48], target=0.5),
        created_by=user,
    )

    assert outcome.run_id is not None and outcome.sim_result_id is not None
    async with maker() as db:
        record = await run_store.record(db, project, outcome.run_id)
        fact = await db.get(GraphEntity, outcome.sim_result_id)
    assert (record.attrs["sim"]["family"], record.attrs["sim"]["version"]) == ("unknown", "unknown")
    assert fact is not None and fact.attrs["provenance"]["solver"] == "gazebo unknown unknown"


# --------------------------------------------------------------------- POST …/{run_id}/pin


def _run_row(project: str, *, status: str = "completed", pinned: bool = False) -> GraphEntity:
    summary = RunSummary(
        id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        name="a sim run",
        origin="sim",
        status=status,  # type: ignore[arg-type]
        started_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    row = run_store.new_record(uuid.UUID(project), summary, uuid.uuid4())
    row.attrs = {
        **row.attrs,
        "checkpoint_id": str(uuid.uuid4()),
        **({"pinned": True} if pinned else {}),
    }
    return row


def _pin_url(project: str, run: GraphEntity) -> str:
    return f"/api/v1/projects/{project}/bench/runs/{run.id}/pin"


async def _pins(db: AsyncSession, *rows: GraphEntity) -> list[Any]:
    marks = []
    for row in rows:
        stored = await db.get(GraphEntity, row.id, populate_existing=True)
        assert stored is not None
        marks.append(stored.attrs.get("pinned"))
    return marks


@pytest.mark.asyncio
async def test_pin_route_marks_and_is_idempotent(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    run, other, live = _run_row(project), _run_row(project), _run_row(project, status="running")
    db.add_all([run, other, live])
    await db.commit()

    done = await client.post(_pin_url(project, run), headers=alice_headers)
    assert done.status_code == 200, done.text
    summary = done.json()["data"]
    assert (summary["id"], summary["origin"], summary["pinned"], summary["baseline"]) == (
        str(run.id),
        "sim",
        True,
        False,
    )
    assert await _pins(db, run, other, live) == [True, None, None]
    again = await client.post(_pin_url(project, run), headers=alice_headers)
    assert again.status_code == 200 and again.json()["data"]["pinned"] is True
    stored = await db.get(GraphEntity, run.id, populate_existing=True)
    assert stored is not None and stored.attrs["checkpoint_id"] == run.attrs["checkpoint_id"]
    assert "pinned" not in stored.attrs["summary"]  # the record's own attr, never the summary

    refused = await client.post(_pin_url(project, live), headers=alice_headers)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "run_active"

    listing = await client.get(f"/api/v1/projects/{project}/bench/runs", headers=alice_headers)
    assert listing.status_code == 200, listing.text
    flags = {row["id"]: row["pinned"] for row in listing.json()["data"]["runs"]}
    assert flags == {str(run.id): True, str(other.id): False, str(live.id): False}


@pytest.mark.asyncio
async def test_pin_cross_team_404(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    mine, _ = await _hw_project(client, alice_headers)
    theirs, _ = await _hw_project(client, bob_headers)
    run = _run_row(mine)
    deleted = _run_row(mine)
    deleted.deleted_at = datetime.now(UTC)
    db.add_all([run, deleted])
    await db.commit()

    assert (await client.post(_pin_url(mine, run))).status_code == 401
    assert (await client.post(_pin_url(mine, run), headers=bob_headers)).status_code == 404
    through_theirs = await client.post(_pin_url(theirs, run), headers=bob_headers)
    assert through_theirs.status_code == 404
    assert through_theirs.json()["error"]["code"] == "not_found"
    assert (await client.post(_pin_url(mine, deleted), headers=alice_headers)).status_code == 404
    unknown = f"/api/v1/projects/{mine}/bench/runs/{uuid.uuid4()}/pin"
    assert (await client.post(unknown, headers=alice_headers)).status_code == 404
    assert await _pins(db, run, deleted) == [None, None]
    assert (await client.post(_pin_url(mine, run), headers=alice_headers)).status_code == 200


@pytest.mark.asyncio
async def test_pin_viewer_403(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Pinning is a member's write: a viewer of the team is refused and the run stays unpinned."""
    project, team_id = await _hw_project(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")
    run = _run_row(project)
    db.add(run)
    await db.commit()

    refused = await client.post(_pin_url(project, run), headers=bob_headers)

    assert refused.status_code == 403, refused.text
    assert await _pins(db, run) == [None]
