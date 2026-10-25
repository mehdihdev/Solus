"""graph/inference/joint_limits: a scene model's joints vs accepted firmware constants →
`limits` candidates, hooked into the scene router's `finish()` (SOLUSDEV-320 module 7)."""

from __future__ import annotations

import importlib
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
