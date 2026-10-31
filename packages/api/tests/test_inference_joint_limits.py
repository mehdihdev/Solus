"""graph/inference/joint_limits: a scene model's joints vs accepted firmware constants →
`limits` candidates, hooked into the scene router's `finish()` (SOLUSDEV-320 module 7)."""

from __future__ import annotations

import importlib
import json
import uuid
from typing import Any

from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, joint_limits
from solus_api.models import Domain, GraphEntity
from sqlalchemy.ext.asyncio import AsyncSession
from test_inference_firmware_edges import USER, inferred, seed_code_file, seed_evidence
from test_inference_power_nets import seed_project
from test_scene_parser import URDF

# Untyped test module (mypy must not follow it): the pattern `test_edges.py` uses.
_bench_scene = importlib.import_module("test_bench_scene")
scene_setup = _bench_scene.setup
upload = _bench_scene.upload


async def seed_scene(db: AsyncSession, project_id: uuid.UUID, *joints: str) -> GraphEntity:
    row = GraphEntity(
        project_id=project_id,
        kind=kinds.BENCH_SCENE_MODEL,
        domain=Domain.SIMULATION,
        origin="manual",
        name="arm",
        attrs={"model": {"joints": [{"name": j, "lower": -1.0, "upper": 1.0} for j in joints]}},
    )
    db.add(row)
    await db.flush()
    return row


def constant(kind: str, name: str) -> dict[str, Any]:
    return {"provenance": {"entity_ref": name, "detail": f'{{"kind": "{kind}"}}'}}


async def test_limits_candidate_per_file_from_matching_constants(db: AsyncSession) -> None:
    pid = await seed_project(db)
    brain = GraphEntity(
        project_id=pid, kind=kinds.HARDWARE_BRAIN, domain=Domain.ELECTRICAL, name="mcu"
    )
    db.add(brain)
    await db.flush()
    robot_id = uuid.uuid4()
    scene = await seed_scene(db, pid, "elbow_flex", "wrist-roll", "gripper")
    arm = await seed_code_file(db, pid, "fw/arm.ino")
    other = await seed_code_file(db, pid, "fw/other.ino")
    await seed_evidence(
        db,
        pid,
        robot_id,
        brain.id,
        source_ref="fw/arm.ino:12",
        **constant("pin_constant", "ELBOW_FLEX_MAX"),
    )
    await seed_evidence(
        db,
        pid,
        robot_id,
        brain.id,
        source_ref="fw/arm.ino:13",
        **constant("motor_constant", "wrist_roll_kv"),
    )
    await seed_evidence(
        db,
        pid,
        robot_id,
        brain.id,
        source_ref="fw/other.ino:2",
        **constant("pin_constant", "LED_PIN"),
    )
    await seed_evidence(
        db,
        pid,
        robot_id,
        brain.id,
        source_ref="fw/other.ino:3",
        **constant("attach_call", "GRIPPER_SERVO"),
    )

    report = await joint_limits.infer(db, pid)

    edges = await inferred(db, pid, "limits")
    assert [(e.src_id, e.dst_id, e.confidence) for e in edges] == [(scene.id, arm.id, 0.5)]
    attrs = edges[0].attrs
    assert (attrs["joint"], attrs["constant"], attrs["line"]) == (
        "elbow_flex",
        "ELBOW_FLEX_MAX",
        12,
    )
    assert attrs["matches"] == [
        {"joint": "elbow_flex", "constant": "ELBOW_FLEX_MAX", "line": 12},
        {"joint": "wrist-roll", "constant": "wrist_roll_kv", "line": 13},
    ]
    assert [ev["ref"] for ev in attrs["evidence"]] == ["fw/arm.ino:12", "fw/arm.ino:13"]
    assert other.id not in {e.dst_id for e in edges}
    assert report == InferenceReport("joint_limits", created=1, updated=0, skipped=0, candidates=1)
    assert await joint_limits.infer(db, pid) == InferenceReport(
        "joint_limits", skipped=1, candidates=1
    )


async def test_a_numeric_constant_is_recorded_with_its_unit(db: AsyncSession) -> None:
    """SOLUSDEV-321 P3-T2: a motor constant's number rides on its match with the unit its name
    states, so `joint_limit_vs_code_constant` can compare it with the joint; a pin constant's
    number is a pin, never a limit, and is not recorded."""
    pid = await seed_project(db)
    brain = GraphEntity(
        project_id=pid, kind=kinds.HARDWARE_BRAIN, domain=Domain.ELECTRICAL, name="mcu"
    )
    db.add(brain)
    await db.flush()
    await seed_scene(db, pid, "elbow", "wrist", "base", "gripper")
    await seed_code_file(db, pid, "fw/arm.ino")
    rows = (
        (10, "motor_constant", "SERVO_ELBOW_MAX_RAD", 2.8),
        (11, "motor_constant", "servoWristMaxDeg", 170.0),
        (12, "motor_constant", "SERVO_BASE_LIMIT", 4095),
        (13, "pin_constant", "GRIPPER_PIN", None),
    )
    for line, kind, name, value in rows:
        detail = json.dumps({"kind": kind, "language": "cpp", "value": value})
        await seed_evidence(
            db,
            pid,
            uuid.uuid4(),
            brain.id,
            source_ref=f"fw/arm.ino:{line}",
            provenance={"entity_ref": name, "detail": detail},
        )

    await joint_limits.infer(db, pid)

    (edge,) = await inferred(db, pid, "limits")
    assert edge.attrs["matches"] == [
        {
            "joint": "elbow",
            "constant": "SERVO_ELBOW_MAX_RAD",
            "line": 10,
            "value": 2.8,
            "unit": "rad",
        },
        {
            "joint": "wrist",
            "constant": "servoWristMaxDeg",
            "line": 11,
            "value": 170.0,
            "unit": "deg",
        },
        {
            "joint": "base",
            "constant": "SERVO_BASE_LIMIT",
            "line": 12,
            "value": 4095.0,
            "unit": "raw",
        },
        {"joint": "gripper", "constant": "GRIPPER_PIN", "line": 13},
    ]


def test_a_constant_states_its_unit_by_name() -> None:
    assert [
        joint_limits.unit_of(name)
        for name in ("ELBOW_MAX_DEG", "elbowMaxRad", "ARM_RADIANS", "WHEEL_RADIUS_MM", "KP")
    ] == ["deg", "rad", "rad", "raw", "raw"]


async def _motor_matches(
    db: AsyncSession, joints: tuple[str, ...], *rows: tuple[int, str, float]
) -> list[dict[str, Any]]:
    """The one `limits` edge's `matches` once `rows` (line, name, value), motor constants in
    `fw/arm.ino`, are accepted against a scene with `joints`."""
    pid = await seed_project(db)
    brain = GraphEntity(
        project_id=pid, kind=kinds.HARDWARE_BRAIN, domain=Domain.ELECTRICAL, name="mcu"
    )
    db.add(brain)
    await db.flush()
    await seed_scene(db, pid, *joints)
    await seed_code_file(db, pid, "fw/arm.ino")
    for line, name, value in rows:
        detail = json.dumps({"kind": "motor_constant", "language": "cpp", "value": value})
        provenance = {"entity_ref": name, "detail": detail}
        await seed_evidence(
            db, pid, uuid.uuid4(), brain.id, source_ref=f"fw/arm.ino:{line}", provenance=provenance
        )
    await joint_limits.infer(db, pid)
    (edge,) = await inferred(db, pid, "limits")
    return list(edge.attrs["matches"])


async def test_a_rate_or_effort_constant_states_no_position_limit(db: AsyncSession) -> None:
    """I2(a): a rate or an effort (`NOT_A_POSITION`) is no position, in rad or not. Its number is
    not recorded, so `joint_limit_vs_code_constant` never compares a speed with a joint's range."""
    matches = await _motor_matches(
        db, ("elbow",), (10, "SERVO_ELBOW_MAX_VEL_RAD", 5.0), (11, "ELBOW_TORQUE_LIMIT", 1.2)
    )

    assert matches == [
        {"joint": "elbow", "constant": "SERVO_ELBOW_MAX_VEL_RAD", "line": 10},
        {"joint": "elbow", "constant": "ELBOW_TORQUE_LIMIT", "line": 11},
    ]


async def test_an_angular_rate_constant_states_no_position_limit(db: AsyncSession) -> None:
    """M108: an angular rate (`OMEGA`, `RAD_PER_S`, `RAD_S`, `RPM`) is no position either, so its
    number is not recorded and `joint_limit_vs_code_constant` never reads it as rad."""
    matches = await _motor_matches(
        db,
        ("elbow",),
        (10, "ELBOW_OMEGA_MAX", 3.0),
        (11, "ELBOW_MAX_RAD_PER_S", 3.0),
        (12, "ELBOW_MAX_RAD_S", 3.0),
        (13, "ELBOW_MAX_RPM", 30.0),
    )

    assert all("value" not in match for match in matches), matches


async def test_a_unit_word_only_counts_as_a_whole_token(db: AsyncSession) -> None:
    """Round 2, new issue 7: plural `RADS` is radians (a position), and `rpm` inside camelCase
    (`warpMode`) is no unit, so both keep their value; the four rate units still drop theirs."""
    matches = await _motor_matches(
        db,
        ("elbow",),
        (10, "ELBOW_MAX_RADS", 1.2),
        (11, "elbowWarpModeMax", 0.8),
        (12, "elbowOmegaMax", 3.0),
        (13, "ELBOW_MAX_RAD_PER_S", 3.0),
        (14, "ELBOW_MAX_RAD_S", 3.0),
        (15, "ELBOW_MAX_RPM", 30.0),
    )

    kept = {match["constant"]: "value" in match for match in matches}
    assert kept == {
        "ELBOW_MAX_RADS": True,
        "elbowWarpModeMax": True,
        "elbowOmegaMax": False,
        "ELBOW_MAX_RAD_PER_S": False,
        "ELBOW_MAX_RAD_S": False,
        "ELBOW_MAX_RPM": False,
    }


async def test_a_joint_name_followed_by_a_digit_is_another_joint(db: AsyncSession) -> None:
    """M109: `SERVO_JOINT11_MAX_RAD` names `joint11`, so with no `joint11` in the scene it names no
    joint — never `joint1`."""
    matches = await _motor_matches(
        db, ("joint1",), (10, "SERVO_JOINT11_MAX_RAD", 2.8), (11, "SERVO_JOINT1_MAX_RAD", 1.5)
    )

    assert [(match["joint"], match["constant"]) for match in matches] == [
        ("joint1", "SERVO_JOINT1_MAX_RAD")
    ]


async def test_a_constant_names_only_its_longest_joint(db: AsyncSession) -> None:
    """I2(b): `SERVO_JOINT10_MAX_RAD` names `joint10`, never `joint1` as well. A name holding two
    joints of one length names neither: which one it limits is not known."""
    matches = await _motor_matches(
        db,
        ("joint1", "joint10", "elbow", "wrist"),
        (10, "SERVO_JOINT10_MAX_RAD", 2.8),
        (11, "SERVO_JOINT1_MAX_RAD", 1.5),
        (12, "ELBOW_WRIST_MAX_RAD", 1.0),
    )

    assert [(match["joint"], match["constant"]) for match in matches] == [
        ("joint10", "SERVO_JOINT10_MAX_RAD"),
        ("joint1", "SERVO_JOINT1_MAX_RAD"),
    ]


async def test_manual_limits_edge_survives_a_rerun(db: AsyncSession) -> None:
    pid = await seed_project(db)
    scene = await seed_scene(db, pid, "elbow")
    arm = await seed_code_file(db, pid, "fw/arm.ino")
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=scene.id,
        dst_id=arm.id,
        relation_type="limits",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )
    assert (await joint_limits.infer(db, pid)).created == 0
    await db.refresh(manual)
    assert manual.origin == "manual" and manual.deleted_at is None


async def test_scene_import_runs_the_inference(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _, robot = await scene_setup(client, alice_headers, db)
    pid = uuid.UUID(project)
    brain = GraphEntity(
        project_id=pid, kind=kinds.HARDWARE_BRAIN, domain=Domain.ELECTRICAL, name="mcu"
    )
    db.add(brain)
    await db.flush()
    arm = await seed_code_file(db, pid, "fw/arm.ino")
    await seed_evidence(
        db,
        pid,
        uuid.UUID(robot),
        brain.id,
        source_ref="fw/arm.ino:7",
        **constant("pin_constant", "HINGE_LIMIT"),
    )
    await db.commit()
    artifact = await upload(client, alice_headers, project, URDF)
    response = await client.post(
        f"/api/v1/projects/{project}/bench/scene/models",
        headers=alice_headers,
        json={"robot_id": robot, "artifact_id": artifact, "name": "model", "format": "urdf"},
    )
    assert response.status_code == 201, response.text
    model_id = uuid.UUID(response.json()["data"]["id"])
    edges = await inferred(db, pid, "limits")
    assert [(e.src_id, e.dst_id, e.attrs["joint"]) for e in edges] == [(model_id, arm.id, "hinge")]
