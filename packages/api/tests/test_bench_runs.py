"""Run capture uses accepted scope and durable retained artifacts; fixtures never move hardware."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.livebench.runs.models import RunManifest
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _robot
from test_run_analysis import manifest as _manifest

# `test_run_analysis.manifest` is untyped; type it once here, not at every call.
# ponytail: import it directly again once test_run_analysis types the helper.
manifest: Callable[[], RunManifest] = _manifest


@pytest.mark.asyncio
async def test_capture_sink_receives_session_bound_packets_before_resolution() -> None:
    from solus_api.graph.buffer import InMemoryTelemetryBuffer
    from solus_api.graph.packet import TelemetryPacket
    from solus_api.graph.telemetry import TelemetryPlumbing

    project, session = uuid.uuid4(), uuid.uuid4()
    plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(), AsyncMock(resolve=AsyncMock(return_value=None))
    )
    observed: list[tuple[uuid.UUID, uuid.UUID | None, TelemetryPacket]] = []
    plumbing.capture_sink = lambda p, s, packet: observed.append((p, s, packet))
    packet = TelemetryPacket(device_id="fixture", timestamp=datetime.now(UTC), values={"x": 1})
    await plumbing.ingest(project, packet, session_id=session)
    assert observed == [(project, session, packet)]


@pytest.mark.asyncio
async def test_import_retains_manifest_and_refuses_other_tenants(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    from solus_api.livebench.runs.router import router
    from solus_api.models import Artifact, User
    from solus_api.services.artifacts import create_artifact
    from sqlalchemy import select

    if not any(getattr(route, "path", "").endswith("/runs/import") for route in app.routes):
        app.include_router(router)
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    run = manifest()
    run.robot_id = uuid.UUID(robot["id"])
    # Import cannot invent live graph parts. Empty graph metadata is legal,
    # producing an explicit insufficient-evidence result.
    run.parts = []
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user
    artifact = await create_artifact(
        db,
        app.state.artifact_store,
        project_id=uuid.UUID(project),
        created_by=user.id,
        data=run.model_dump_json().encode(),
        media_type="application/json",
        source_tool=None,
        tool_call_id=None,
    )
    await db.commit()
    url = f"/api/v1/projects/{project}/bench/runs"
    body = {
        "robot_id": robot["id"],
        "artifact_id": str(artifact.id),
        "name": "Synthetic baseline",
        "origin": "synthetic",
    }
    assert (await client.post(url + "/import", json=body)).status_code == 401
    assert (await client.post(url + "/import", headers=bob_headers, json=body)).status_code == 404
    result = await client.post(url + "/import", headers=alice_headers, json=body)
    assert result.status_code == 201, result.text
    summary = result.json()["data"]
    assert summary["origin"] == "synthetic"
    assert summary["status"] == "completed"
    saved = await db.get(Artifact, uuid.UUID(summary["artifact_id"]), populate_existing=True)
    assert saved and saved.retained
    detail = await client.get(url + "/" + summary["id"], headers=alice_headers)
    assert detail.status_code == 200
    assert len(detail.json()["data"]["manifest"]["packets"]) == 3
    listing = await client.get(url, headers=alice_headers)
    assert listing.json()["data"]["runs"][0]["id"] == summary["id"]
    found = await client.get(url + "/" + summary["id"] + "/findings", headers=alice_headers)
    assert found.json()["data"]["findings"] == []
    assert found.json()["data"]["evidence_origin"] == "synthetic"
    narrated = await client.post(url + "/" + summary["id"] + "/narrate", headers=alice_headers)
    assert narrated.json()["data"]["mode"] == "deterministic"
    compared = await client.post(
        url + "/compare",
        headers=alice_headers,
        json={"baseline_id": summary["id"], "candidate_id": summary["id"]},
    )
    assert compared.status_code == 200, compared.text
    assert compared.json()["data"]["divergences"] == []
    assert (await client.get(url + "/" + summary["id"], headers=bob_headers)).status_code == 404
    assert (await client.post(url + "/" + summary["id"] + "/stop", headers=alice_headers)).json()[
        "data"
    ]["status"] == "completed"


@pytest.mark.asyncio
async def test_capture_is_bounded_and_session_scoped() -> None:
    from solus_api.graph.packet import TelemetryPacket
    from solus_api.livebench.runs.capture import Capture, RunCaptureManager
    from solus_api.livebench.runs.models import MAX_PACKETS, RunSummary

    project, session_id, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run = manifest()
    run.packets = []
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=run.robot_id,
        session_id=session_id,
        name="Bounded",
        origin="live",
        status="running",
        started_at=run.started_at,
    )
    capture = Capture(project, user, info, run, 100)
    manager = RunCaptureManager(AsyncMock(), AsyncMock(), AsyncMock())
    manager.active[info.id] = capture
    packet = TelemetryPacket(device_id="fixture", timestamp=datetime.now(UTC), values={"x": 1})
    manager.ingest(uuid.uuid4(), session_id, packet)
    manager.ingest(project, uuid.uuid4(), packet)
    manager.ingest(project, None, packet)
    assert not run.packets
    for _ in range(MAX_PACKETS + 1):
        manager.ingest(project, session_id, packet)
    assert len(run.packets) == MAX_PACKETS
    assert info.status == "truncated" and info.drop_count == 1


@pytest.mark.asyncio
async def test_capture_checkpoint_restores_interrupted_count(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
) -> None:
    from solus_api.livebench.runs import store
    from solus_api.livebench.runs.models import RunSummary
    from solus_api.livebench.runs.router import router
    from solus_api.models import User
    from sqlalchemy import select

    if not any(getattr(route, "path", "").endswith("/runs/import") for route in app.routes):
        app.include_router(router)
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user
    run = manifest()
    run.robot_id = uuid.UUID(robot["id"])
    run.parts = []
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=run.robot_id,
        name="Lost process",
        origin="live",
        status="running",
        started_at=run.started_at,
    )
    record = store.new_record(uuid.UUID(project), info, user.id)
    db.add(record)
    await db.flush()
    await store.save(db, app.state.artifact_store, record, info, run, user.id, final=False)
    url = f"/api/v1/projects/{project}/bench/runs/{info.id}"
    result = await client.get(url, headers=alice_headers)
    assert result.json()["data"]["summary"]["status"] == "interrupted"
    assert result.json()["data"]["summary"]["packet_count"] == 3
    compared = await client.post(
        f"/api/v1/projects/{project}/bench/runs/compare",
        headers=alice_headers,
        json={"baseline_id": str(info.id), "candidate_id": str(info.id)},
    )
    assert compared.status_code == 200, compared.text
    stopped = await client.post(url + "/stop", headers=alice_headers)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["status"] == "interrupted"
    assert stopped.json()["data"]["artifact_id"]
    repeated = await client.post(url + "/stop", headers=alice_headers)
    assert repeated.json()["data"] == stopped.json()["data"]


@pytest.mark.asyncio
async def test_run_route_inputs_and_unknown_scope(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    unverified_headers: dict[str, str],
) -> None:
    from solus_api.livebench.runs.router import router

    if not any(getattr(route, "path", "").endswith("/runs/import") for route in app.routes):
        app.include_router(router)
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    url = f"/api/v1/projects/{project}/bench/runs"
    body = {"robot_id": robot["id"], "session_id": str(uuid.uuid4()), "name": "Unknown"}
    assert (await client.post(url, json=body, headers=alice_headers)).status_code == 404
    assert (
        await client.get(url + "/" + str(uuid.uuid4()), headers=alice_headers)
    ).status_code == 404
    assert (await client.get(url + "?limit=51", headers=alice_headers)).status_code == 422
    assert (
        await client.post(url, json={**body, "execute": True}, headers=alice_headers)
    ).status_code == 422
    assert (await client.get(url, headers=unverified_headers)).status_code == 403


@pytest.mark.asyncio
async def test_start_capture_stop_files_exact_session_packets(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.graph.packet import TelemetryPacket
    from solus_api.livebench.runs.router import router
    from solus_api.livebench.sessions import BenchSessionOut
    from test_hardware_router import _saved_serial_arm

    if not any(getattr(route, "path", "").endswith("/runs/import") for route in app.routes):
        app.include_router(router)
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    configured = await client.put(
        f"/api/v1/projects/{project}/hardware/robots/{robot['id']}/config",
        headers=alice_headers,
        json={"config": config},
    )
    assert configured.status_code == 200, configured.text
    session_id = uuid.uuid4()
    bench = BenchSessionOut(
        id=session_id,
        mode="real",
        provider="robot",
        status="active",
        link="connected",
        label="Fixture read-only stream",
        created_at=datetime.now(UTC),
        ended_at=None,
        device={"device_ref": "usb:" + config["identity"]["binding"]},
        device_ids=[],
        counts={},
        last_summary=None,
    )
    monkeypatch.setattr(app.state.bench_sessions, "get", lambda p, s: bench)
    url = f"/api/v1/projects/{project}/bench/runs"
    body = {"robot_id": robot["id"], "session_id": str(session_id), "name": "Read-only fixture"}
    result = await client.post(url, headers=alice_headers, json=body)
    assert result.status_code == 201, result.text
    identity = result.json()["data"]["id"]
    try:
        packet = TelemetryPacket(
            device_id="fixture",
            timestamp=datetime.now(UTC),
            values={"position": 4},
            units={"position": "deg"},
        )
        app.state.bench_runs.ingest(uuid.UUID(project), uuid.uuid4(), packet)
        await app.state.telemetry_plumbing.ingest(uuid.UUID(project), packet, session_id=session_id)
        stop = await client.post(url + "/" + identity + "/stop", headers=alice_headers)
        assert stop.status_code == 200, stop.text
        assert stop.json()["data"]["packet_count"] == 1
        assert stop.json()["data"]["artifact_id"]
        assert stop.json()["data"]["status"] == "completed"
        detail = await client.get(url + "/" + identity, headers=alice_headers)
        assert detail.json()["data"]["manifest"]["snapshots"]
        # every run read says whether it is the robot's baseline; a capture is saved without it
        from solus_api.models import GraphEntity

        assert detail.json()["data"]["summary"]["baseline"] is False
        row = await db.get(GraphEntity, uuid.UUID(identity), populate_existing=True)
        assert row is not None and "baseline" not in row.attrs["summary"]
    finally:
        await app.state.bench_runs.aclose()


@pytest.mark.asyncio
async def test_manifest_sensor_artifacts_are_retained_transitively(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
) -> None:
    from solus_api.livebench.runs import store
    from solus_api.livebench.runs.models import RunSummary, SensorReference
    from solus_api.models import User
    from solus_api.services.artifacts import create_artifact
    from sqlalchemy import select

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user
    sensor = await create_artifact(
        db,
        app.state.artifact_store,
        project_id=uuid.UUID(project),
        created_by=user.id,
        data=b"fixture image",
        media_type="image/png",
        source_tool=None,
        tool_call_id=None,
    )
    run = manifest()
    run.robot_id = uuid.UUID(robot["id"])
    run.sensors = [
        SensorReference(
            artifact_id=sensor.id, timestamp=run.started_at, kind="camera", device_id="fixture"
        )
    ]
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=run.robot_id,
        name="Sensor",
        origin="synthetic",
        status="completed",
        started_at=run.started_at,
    )
    record = store.new_record(uuid.UUID(project), info, user.id)
    db.add(record)
    await db.flush()
    await store.save(db, app.state.artifact_store, record, info, run, user.id, final=True)
    await db.refresh(sensor)
    assert sensor.retained


@pytest.mark.asyncio
async def test_imported_part_reference_must_belong_to_selected_robot(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
) -> None:
    from solus_api.core.errors import APIError
    from solus_api.livebench.runs.snapshot import validate_references

    project, _ = await _hw_project(client, alice_headers)
    first = await _robot(client, alice_headers, project)
    second = await _robot(client, alice_headers, project)
    run = manifest()
    run.robot_id = uuid.UUID(first["id"])
    run.parts[0].entity_id = uuid.UUID(second["id"])
    with pytest.raises(APIError):
        await validate_references(db, uuid.UUID(project), run)


@pytest.mark.asyncio
async def test_checkpoint_cannot_overwrite_terminal_run_or_drop_truncation(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
) -> None:
    from solus_api.livebench.runs import store
    from solus_api.livebench.runs.capture import Capture
    from solus_api.livebench.runs.models import RunSummary
    from solus_api.models import User
    from sqlalchemy import select

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user
    run = manifest()
    run.robot_id = uuid.UUID(robot["id"])
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=run.robot_id,
        name="Terminal",
        origin="live",
        status="completed",
        started_at=run.started_at,
    )
    record = store.new_record(uuid.UUID(project), info, user.id)
    db.add(record)
    await db.flush()
    await store.save(db, app.state.artifact_store, record, info, run, user.id, final=True)
    artifact = info.artifact_id
    stale = info.model_copy(update={"status": "running"})
    capture = Capture(uuid.UUID(project), user.id, stale, run, 100)
    app.state.bench_runs.active[info.id] = capture
    saved = await app.state.bench_runs.persist(capture, final=False)
    assert saved.status == "completed"
    assert saved.artifact_id == artifact
    assert not app.state.bench_runs.contains(info.id)


def test_snapshot_redacts_private_paths_and_secret_shaped_metadata() -> None:
    from solus_api.livebench.runs.snapshot import portable_json

    text = portable_json(
        {
            "source": "/home/operator/private/control.py",
            "nested": {"access_token": "private", "source": "C:\\Users\\operator\\private"},
            "calibration": {"source": "~/.local/calibration.json"},
            "code_site": "control.py:12",
            "value": 4,
        }
    )
    assert "/home/operator" not in text
    assert "C:" not in text
    assert "~/.local" not in text
    assert "access_token" not in text
    assert "control.py:12" in text


def test_explicit_graph_rating_and_config_channels_populate_evidence() -> None:
    from solus_api.hardware.config import PartConfig
    from solus_api.livebench.runs.snapshot import part_evidence
    from solus_api.models import Domain, GraphEntity

    part = GraphEntity(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        kind="part",
        domain=Domain.ELECTRICAL,
        name="Rated fixture",
        origin="manual",
        external_ref="fixture/joint",
        attrs={
            "specs": {"stall_current_a": 2},
            "code_site": "control.py:12",
            "cad_revision": "fixture-m1",
        },
    )
    config = PartConfig.model_validate(
        {
            "telemetry": [
                {"name": "position", "unit": "deg"},
                {"name": "current", "unit": "A"},
                {"name": "command", "unit": "deg"},
            ],
            "limits": {"values": {"position_min_deg": -90, "position_max_deg": 90}},
        }
    )
    evidence = part_evidence(part, config)
    assert evidence.stall_current_a == 2
    assert evidence.current_signal == "current"
    assert evidence.position_signal == "position"
    assert evidence.command_signal == "command"
    assert evidence.position_max == 90
    assert evidence.code_site == "control.py:12"


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        (
            "post",
            "",
            {"robot_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "name": "Probe"},
        ),
        ("get", "", None),
        ("post", "/00000000-0000-0000-0000-000000000001/stop", None),
        ("post", "/compare", {"baseline_id": str(uuid.uuid4()), "candidate_id": str(uuid.uuid4())}),
        ("get", "/00000000-0000-0000-0000-000000000001/findings", None),
        ("post", "/00000000-0000-0000-0000-000000000001/narrate", None),
    ],
)
@pytest.mark.asyncio
async def test_all_run_operations_enforce_auth_and_project_isolation(
    method: str,
    suffix: str,
    body: dict[str, str] | None,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    url = f"/api/v1/projects/{project}/bench/runs" + suffix
    assert (await client.request(method, url, json=body)).status_code == 401
    assert (await client.request(method, url, json=body, headers=bob_headers)).status_code == 404
    own = await client.request(method, url, json=body, headers=alice_headers)
    assert own.status_code == (200 if method == "get" and suffix == "" else 404)


@pytest.mark.parametrize("value", [{"data": [0] * 257}, {"data": "x" * 4097}, {"data": object()}])
def test_portable_snapshot_rejects_unbounded_or_non_json_values(value: dict[str, object]) -> None:
    from solus_api.livebench.runs.snapshot import portable_json

    with pytest.raises(ValueError):
        portable_json(value)


@pytest.mark.asyncio
async def test_imported_snapshot_rejects_unknown_source(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
) -> None:
    from solus_api.core.errors import APIError
    from solus_api.livebench.runs.models import RevisionSnapshot
    from solus_api.livebench.runs.snapshot import validate_references

    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    run = manifest()
    run.robot_id = uuid.UUID(robot["id"])
    run.parts = []
    run.snapshots = [
        RevisionSnapshot(
            entity_id=run.robot_id, kind="code", name="Unknown source", source_id=uuid.uuid4()
        )
    ]
    with pytest.raises(APIError):
        await validate_references(db, uuid.UUID(project), run)


@pytest.mark.asyncio
async def test_checkpoint_worker_detects_ended_session_without_completing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from solus_api.livebench.runs.capture import Capture, RunCaptureManager
    from solus_api.livebench.runs.models import RunSummary

    run = manifest()
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=run.robot_id,
        session_id=uuid.uuid4(),
        name="Ended",
        origin="live",
        status="running",
        started_at=run.started_at,
    )
    capture = Capture(uuid.uuid4(), uuid.uuid4(), info, run, 100)
    manager = RunCaptureManager(
        AsyncMock(),
        AsyncMock(),
        Mock(get=lambda *_: SimpleNamespace(status="ended")),
        checkpoint_seconds=0.001,
    )

    async def persist(item: Capture, *, final: bool) -> RunSummary:
        assert final and item.info.status == "interrupted"
        manager.active.pop(item.info.id)
        return item.info

    persisted = AsyncMock(side_effect=persist)
    monkeypatch.setattr(manager, "persist", persisted)
    manager.add(capture)
    assert capture.task
    await asyncio.wait_for(capture.task, timeout=1)
    persisted.assert_awaited_once()


def test_imported_metadata_is_portable_and_malformed_metadata_is_rejected() -> None:
    from solus_api.livebench.runs.models import RevisionSnapshot
    from solus_api.livebench.runs.snapshot import portable_manifest

    run = manifest()
    run.parts[0].code_site = "/home/private/control.py:12"
    run.snapshots = [
        RevisionSnapshot(
            entity_id=run.robot_id,
            kind="config",
            name="Config",
            data='{"source":"/home/private/calibration.json","gain":1}',
        )
    ]
    portable = portable_manifest(run)
    assert portable.parts[0].code_site is None
    assert portable.snapshots[0].data is not None
    assert "/home/private" not in portable.snapshots[0].data
    assert run.parts[0].code_site == "/home/private/control.py:12"
    run.snapshots[0].data = "not JSON"
    with pytest.raises(ValueError):
        portable_manifest(run)


def test_missing_or_invalid_rating_never_becomes_positive_evidence() -> None:
    from solus_api.livebench.runs.snapshot import part_evidence
    from solus_api.models import Domain, GraphEntity

    entity = GraphEntity(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        kind="part",
        domain=Domain.ELECTRICAL,
        name="Unrated",
        origin="manual",
        external_ref="fixture",
        attrs={"specs": {"stall_current_a": True}},
    )
    assert part_evidence(entity, None).stall_current_a is None
    entity.attrs = {"specs": {"stall_current_a": 10**400}}
    assert part_evidence(entity, None).stall_current_a is None


@pytest.mark.asyncio
async def test_the_runs_narration_speaks_in_the_askers_register(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOLUSDEV-321 P6 fix 1 (m8, R141): the narrate route hands `narrate` the asker's levels as
    the SOL route reads them (`turn_expertise`): a member whose stored software level is `expert`
    gets the terse register after the mode's note, and one with none the neutral text."""
    from types import SimpleNamespace
    from typing import Any

    from solus_api.agent.expertise import Expertise, register_line
    from solus_api.livebench.runs import analysis, narration
    from solus_api.livebench.runs.router import router
    from solus_api.models import User
    from solus_api.services.artifacts import create_artifact
    from solus_api.services.machines import ensure_member
    from sqlalchemy import select

    if not any(getattr(route, "path", "").endswith("/runs/import") for route in app.routes):
        app.include_router(router)
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    run = manifest()
    run.robot_id, run.parts = uuid.UUID(robot["id"]), []
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user
    artifact = await create_artifact(
        db,
        app.state.artifact_store,
        project_id=uuid.UUID(project),
        created_by=user.id,
        data=run.model_dump_json().encode(),
        media_type="application/json",
        source_tool=None,
        tool_call_id=None,
    )
    await db.commit()
    url = f"/api/v1/projects/{project}/bench/runs"
    body = {
        "robot_id": robot["id"],
        "artifact_id": str(artifact.id),
        "name": "Register",
        "origin": "synthetic",
    }
    imported = await client.post(url + "/import", headers=alice_headers, json=body)
    assert imported.status_code == 201, imported.text
    narrate = f"{url}/{imported.json()['data']['id']}/narrate"
    card = {
        "entity_id": str(uuid.uuid4()),
        "headline": "Possible stall",
        "explanation": "Current reached the rating.",
        "detail": "Cause is unknown.",
        "evidence": {"stall_current_a": 1.5},
    }
    monkeypatch.setattr(analysis, "findings", lambda _: {"findings": [card], "insufficient": []})
    systems: list[str] = []

    async def complete(query: str, **kwargs: Any) -> Any:
        systems.append(kwargs["conversation"].system)
        return SimpleNamespace(text='["Possible stall; the cause remains uncertain."]')

    monkeypatch.setattr(narration, "complete", complete)

    assert (await client.post(narrate, headers=alice_headers)).json()["data"]["mode"] == "model"
    member = await ensure_member(db, uuid.UUID(project), user.id)
    member.attrs = {**member.attrs, "expertise": Expertise(software="expert").model_dump()}
    await db.commit()
    assert (await client.post(narrate, headers=alice_headers)).json()["data"]["mode"] == "model"

    neutral, registered = systems
    register = register_line(Expertise(software="expert"))
    assert register == "By domain: be terse and skip basics in software (expert)."
    assert "By domain" not in neutral and registered == f"{neutral} {register}"
