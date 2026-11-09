"""SOLUSDEV-321 P4-T5 fix 1 (R117): POST /bench/runs/compare against the twin built from a
trajectory simulation, and an import's twin marker held to a simulation of its own project."""

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.live import LiveHub
from solus_api.livebench.runs import analysis, store
from solus_api.livebench.runs.models import RevisionSnapshot, RunManifest, RunSummary
from solus_api.livebench.runs.router import router
from solus_api.livebench.runs.snapshot import validate_references
from solus_api.models import Domain, GraphEntity, User
from solus_api.simulation.sim_capability import SimResult
from solus_api.simulation.sim_facts import record_sim_result
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_hardware_router import _hw_project, _robot


async def _shoulder(db: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    """A shoulder part, which the project's scene binds to its `shoulder` joint, in radians."""
    part = GraphEntity(
        project_id=project_id,
        kind=kinds.PART,
        domain=Domain.MECHANICAL,
        origin="manual",
        name="shoulder",
    )
    db.add(part)
    await db.flush()
    joint = {"name": "shoulder", "type": "revolute", "lower": -math.pi, "upper": math.pi}
    scene = {
        "model": {"joints": [joint]},
        "bindings": [{"joint": "shoulder", "part_entity_id": str(part.id)}],
    }
    db.add(
        GraphEntity(
            project_id=project_id,
            kind=kinds.BENCH_SCENE_MODEL,
            domain=Domain.SIMULATION,
            origin="manual",
            name="arm",
            attrs=scene,
        )
    )
    await db.commit()
    return part.id


async def _routine_sim(engine: Any, project_id: uuid.UUID, subject: uuid.UUID) -> uuid.UUID:
    """A rung-3 trajectory simulation of the routine, recorded the one way there is: the shoulder
    commanded to a quarter turn, climbing to it at 0.8 A over ten samples."""
    times, quarter = [n / 2 for n in range(10)], math.pi / 2
    recorded = {
        "trajectory": {
            "joints": ["shoulder"],
            "points": [{"t": 0.0, "positions": [quarter]}, {"t": 4.5, "positions": [quarter]}],
        },
        "expected_trajectory": {
            "t": times,
            "positions": {"shoulder": [quarter * n / 9 for n in range(10)]},
        },
        "expected_current_a": {"shoulder": [0.8] * 10},
    }
    result = {
        "values": {"peak_joint_torque_nm": {"value": 1.2, "unit": "N m"}},
        "provenance": {
            "solver": "rigid_body_trajectory",
            "inputs": {name: {"value": v, "source": "derived"} for name, v in recorded.items()},
            "leaves_out": ["sensor noise and delay"],
        },
    }
    return await record_sim_result(
        async_sessionmaker(engine, expire_on_commit=False),
        LiveHub(),
        project_id=project_id,
        subject_id=subject,
        rung=3,
        result=SimResult.model_validate(result),
        created_by=None,
    )


async def _stalled_run(
    db: AsyncSession, app: FastAPI, project_id: uuid.UUID, robot: uuid.UUID, part: uuid.UUID
) -> tuple[str, Any]:
    """A filed run of the routine in which the shoulder stalls: held at 0 deg at 2.5 A against
    its 2 A rating while 90 deg is commanded."""
    start = datetime(2026, 10, 29, tzinfo=UTC)
    run = RunManifest.model_validate(
        {
            "robot_id": robot,
            "started_at": start,
            "parts": [
                {
                    "entity_id": part,
                    "name": "shoulder",
                    "device_id": "arm/1",
                    "current_signal": "current",
                    "position_signal": "position",
                    "command_signal": "command",
                    "stall_current_a": 2.0,
                    "position_unit": "deg",
                }
            ],
            "packets": [
                {
                    "device_id": "arm/1",
                    "timestamp": start + timedelta(seconds=n / 2),
                    "values": {"position": 0.0, "command": 90.0, "current": 2.5},
                    "units": {"position": "deg", "command": "deg", "current": "A"},
                }
                for n in range(10)
            ],
        }
    )
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=robot,
        name="Shoulder routine",
        origin="recorded",
        status="completed",
        started_at=start,
    )
    entity = store.new_record(project_id, info, user.id)
    db.add(entity)
    await db.flush()
    await store.save(db, app.state.artifact_store, entity, info, run, user.id, final=True)
    return str(info.id), run


async def _shoulder_routine(
    client: AsyncClient, db: AsyncSession, engine: Any, app: FastAPI, headers: dict[str, str]
) -> dict[str, Any]:
    """The robot's shoulder bound in its scene, a trajectory simulation of the routine, and a
    filed run of it in which the shoulder stalls."""
    if not any(getattr(route, "path", "").endswith("/runs/compare") for route in app.routes):
        app.include_router(router)
    project, _ = await _hw_project(client, headers)
    robot = uuid.UUID((await _robot(client, headers, project))["id"])
    part = await _shoulder(db, uuid.UUID(project))
    sim = await _routine_sim(engine, uuid.UUID(project), robot)
    run, manifest = await _stalled_run(db, app, uuid.UUID(project), robot, part)
    return {
        "url": f"/api/v1/projects/{project}/bench/runs/compare",
        "run": run,
        "manifest": manifest,
        "sim": str(sim),
        "part": str(part),
    }


@pytest.mark.asyncio
async def test_compare_against_a_simulation_reads_the_candidate_against_its_twin(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    engine: Any,
    alice_headers: dict[str, str],
) -> None:
    """R117: with `sim_result_id`, the twin's run built from that trajectory simulation, laid onto
    the candidate's parts, stands in for the baseline: the stalled shoulder, which the twin drove
    to its command, is electrical or mechanical, beside a simulation gap."""
    f = await _shoulder_routine(client, db, engine, app, alice_headers)
    body = {"baseline_id": f["run"], "candidate_id": f["run"], "sim_result_id": f["sim"]}

    response = await client.post(f["url"], headers=alice_headers, json=body)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["expected_source"], data["source_snapshots_changed"]) == ("sim", False)
    evidence = data["evidence"]
    assert (evidence["sim_result_id"], evidence["sim_control"], evidence["simulation_gap"]) == (
        f["sim"],
        "electrical_or_mechanical",
        True,
    )
    assert set(evidence["residuals"]) == {f["part"]}


@pytest.mark.asyncio
async def test_compare_names_only_a_simulation_of_its_own_project(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    engine: Any,
    alice_headers: dict[str, str],
) -> None:
    """A `sim_result_id` of another project, or the id of an entity of another kind, is not
    found; without one, compare answers exactly as it did before."""
    f = await _shoulder_routine(client, db, engine, app, alice_headers)
    other = await _shoulder_routine(client, db, engine, app, alice_headers)
    runs = {"baseline_id": f["run"], "candidate_id": f["run"]}

    for wrong in (other["sim"], f["part"]):
        response = await client.post(
            f["url"], headers=alice_headers, json={**runs, "sim_result_id": wrong}
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "not_found"
    plain = await client.post(f["url"], headers=alice_headers, json=runs)

    assert plain.status_code == 200, plain.text
    assert plain.json()["data"] == jsonable_encoder(analysis.compare(f["manifest"], f["manifest"]))


@pytest.mark.asyncio
async def test_an_imported_twin_marker_must_name_a_simulation_of_its_project(
    client: AsyncClient, db: AsyncSession, engine: Any, alice_headers: dict[str, str]
) -> None:
    """Minor 2: an import may mark as its twin only a `sim_result` of its own project; a marker
    naming any other entity of the project is not found."""
    project, _ = await _hw_project(client, alice_headers)
    robot = uuid.UUID((await _robot(client, alice_headers, project))["id"])
    sim = await _routine_sim(engine, uuid.UUID(project), robot)
    run = RunManifest(robot_id=robot, started_at=datetime(2026, 10, 29, tzinfo=UTC))

    run.snapshots = [RevisionSnapshot(entity_id=robot, kind=kinds.SIM_RESULT, name="forged")]
    with pytest.raises(APIError, match="not found"):
        await validate_references(db, uuid.UUID(project), run)
    run.snapshots = [RevisionSnapshot(entity_id=sim, kind=kinds.SIM_RESULT, name="the twin")]
    await validate_references(db, uuid.UUID(project), run)
