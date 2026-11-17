"""SOLUSDEV-326 P1-T5: one opener for a hardware subject's bench session.

The bench route (`provider: robot|hardware`), the confirm-and-connect coordinator and the session
a bound suggestion starts all open through `hardware/local_runtime.py`: the host check, then one
v1 driver document per brain (`per_brain()`). Each brain this host can reach is opened; the others
are reported as unreachable instead of failing the session — unless none opens. One robot is one
session (a merged connection over its brains, one window evaluator); a lone part's session streams
its own channels and runs no robot evaluator.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

import pytest
from conftest import me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.live import LiveStatus
from solus_api.graph.codec import from_wire
from solus_api.hardware import detection_service
from solus_api.hardware.connections import HardwareConnections, connection_state
from solus_api.hardware.host_topology import LocalHostProvider
from solus_api.hardware.local_runtime import BrainsConnection
from solus_api.livebench.sessions import (
    DeviceBusyError,
    DeviceNotFoundError,
    SessionManager,
    SessionView,
)
from solus_api.models import GraphEntity
from sqlalchemy.ext.asyncio import AsyncSession
from test_bench_robot_provider import _configure, _robot_project, _robot_session_body
from test_bench_router import FakeLocal, TapConn, wire_packet
from test_hardware_identity_list import _brain, _two_brains
from test_sessions import FakeConn

USER = {"by": "user", "source": None}
NOT_CONNECTED = "The configured device is not connected."


class _BrainsLocal(FakeLocal):
    """A local runner whose `absent` bindings are not plugged in."""

    def __init__(self, *absent: str) -> None:
        super().__init__()
        self.absent = set(absent)
        self.attempts: list[str] = []

    async def open_robot(
        self, config: dict[str, Any], *, project_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> TapConn:
        binding = config["identity"]["binding"]
        self.attempts.append(binding)
        if binding in self.absent:
            raise DeviceNotFoundError(f"no device with binding {binding!r}")
        return await self._open("robot", config=config, project_id=project_id, user_id=user_id)


async def _save_config(
    client: AsyncClient, headers: dict[str, str], project: str, config: dict[str, Any]
) -> None:
    response = await client.put(
        f"/api/v1/projects/{project}/hardware/entities/{config['entity_id']}/config",
        headers={**headers, "If-Match": "0"},
        json={"config": config},
    )
    assert response.status_code == 200, response.text


async def _start(
    client: AsyncClient, headers: dict[str, str], project: str, config: dict[str, Any]
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project}/bench/sessions",
        headers=headers,
        json={"mode": "real", "config": config},
    )


async def _connect(
    app: FastAPI, coordinator: HardwareConnections, project: str, robot: str, account: str
) -> dict[str, Any]:
    """One confirm-and-connect attempt, as `confirm_detected` schedules it; its outcome."""
    runtime = await coordinator.ensure_owner()
    attempt = uuid.uuid4()
    async with app.state.sessionmaker() as session:
        entity = await session.get(GraphEntity, uuid.UUID(robot))
        assert entity is not None
        entity.attrs = {**entity.attrs, "connection": connection_state(attempt, runtime_id=runtime)}
        await session.commit()
    coordinator.schedule(uuid.UUID(project), uuid.UUID(account), uuid.UUID(robot), attempt, 1.0)
    await coordinator.drain()
    async with app.state.sessionmaker() as session:
        entity = await session.get(GraphEntity, uuid.UUID(robot))
        assert entity is not None
        return dict(entity.attrs["connection"])


def _coordinator(app: FastAPI, local: Any) -> HardwareConnections:
    return HardwareConnections(
        sessions=app.state.sessionmaker,
        manager=app.state.bench_sessions,
        local=local,
        hub=app.state.graph_hub,
        owner=app.state.hardware_connections.owner,
    )


# ------------------------------------------------------------------------- several brains


async def test_a_robot_with_two_brains_opens_the_one_it_reaches_and_reports_the_other(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    local = app.state.bench_local = _BrainsLocal("BBB")
    project, robot = await _robot_project(client, alice_headers)
    await _save_config(client, alice_headers, project, _two_brains(uuid.UUID(robot)))

    response = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )

    assert response.status_code == 201, response.text
    record = response.json()["data"]
    assert local.attempts == ["AAA", "BBB"]
    assert record["device"]["device_ref"] == "usb:AAA"
    assert record["device"]["unreachable"] == [{"device_ref": "usb:BBB", "error": NOT_CONNECTED}]
    assert [opened["config"]["identity"]["binding"] for opened in local.opened] == ["AAA"]
    listed = await client.get(
        f"/api/v1/projects/{project}/bench/sessions/{record['id']}", headers=alice_headers
    )
    assert listed.json()["data"]["device"]["unreachable"] == record["device"]["unreachable"]


async def test_a_robot_none_of_whose_brains_opens_does_not_start(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    app.state.bench_local = _BrainsLocal("AAA", "BBB")
    project, robot = await _robot_project(client, alice_headers)
    await _save_config(client, alice_headers, project, _two_brains(uuid.UUID(robot)))

    response = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "device_not_found"
    assert app.state.bench_sessions.list(uuid.UUID(project)) == []


async def test_both_brains_stream_through_one_session(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """One robot is one session: one cap slot, one tap over both brains' packets, one close."""
    local = app.state.bench_local = _BrainsLocal()
    project, robot = await _robot_project(client, alice_headers)
    await _save_config(client, alice_headers, project, _two_brains(uuid.UUID(robot)))

    response = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )

    assert response.status_code == 201, response.text
    record = response.json()["data"]
    assert "unreachable" not in record["device"]
    left, right = local.conns
    assert left.tap is not None and left.tap is right.tap
    await left.tap(from_wire(wire_packet("usb:AAA/1", 0, {"x": 1.0})))
    await right.tap(from_wire(wire_packet("usb:BBB/1", 0, {"y": 2.0})))
    url = f"/api/v1/projects/{project}/bench/sessions/{record['id']}"
    detail = (await client.get(url, headers=alice_headers)).json()["data"]
    assert sorted(detail["device_ids"]) == ["usb:AAA/1", "usb:BBB/1"]
    assert len(app.state.bench_sessions.list(uuid.UUID(project), status="active")) == 1
    stopped = await client.post(f"{url}/stop", headers=alice_headers)
    assert stopped.status_code == 200, stopped.text
    assert left.closed and right.closed


async def test_a_brain_this_host_cannot_open_is_reported_and_never_opened(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """A brain reached through another computer, or one with no device bound yet, is not this
    host's to open."""
    local = app.state.bench_local = _BrainsLocal()
    project, robot = await _robot_project(client, alice_headers)
    onboard = {
        "kind": "onboard",
        "binding": {"kind": "usb_serial", "binding": "CCC"},
        "via": "usb:AAA",
        "protocol": {"driver_id": "relay", "params": {}},
    }
    config = {
        "schema_version": 2,
        "entity_id": robot,
        "identity": [_brain("AAA", "left-driver"), onboard, {"kind": "mcu"}],
        "provenance": {"identity": USER},
    }
    await _save_config(client, alice_headers, project, config)

    response = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )

    assert response.status_code == 201, response.text
    assert local.attempts == ["AAA"]
    assert response.json()["data"]["device"]["unreachable"] == [
        {"device_ref": "usb:CCC", "error": "This brain is reached through another computer."},
        {"device_ref": None, "error": "No device is bound to this brain yet."},
    ]
    # With nothing left this host can open, the session does not start and says why.
    elsewhere, remote = await _robot_project(client, alice_headers)
    config = {
        **config,
        "entity_id": remote,
        "identity": [onboard, {"kind": "mcu", "binding": {"kind": "usb_serial", "binding": "AAA"}}],
    }
    await _save_config(client, alice_headers, elsewhere, config)
    refused = await _start(
        client, alice_headers, elsewhere, {"provider": "robot", "robot_entity_id": remote}
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["message"] == "This brain is reached through another computer."
    assert local.attempts == ["AAA"]


async def test_the_coordinator_keeps_connection_state_per_brain(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """A robot of several brains says how each fared; a one-brain robot keeps today's keys."""
    local = app.state.bench_local = _BrainsLocal("BBB")
    user = await me(client, alice_headers)
    project, robot = await _robot_project(client, alice_headers)
    await _save_config(client, alice_headers, project, _two_brains(uuid.UUID(robot)))
    single = (
        await client.post(
            f"/api/v1/projects/{project}/entities",
            headers=alice_headers,
            json={"type": "physical_robot", "name": "Single"},
        )
    ).json()["data"]["id"]
    await _configure(client, alice_headers, project, single)
    coordinator = _coordinator(app, local)
    try:
        several = await _connect(app, coordinator, project, robot, user["id"])
        one = await _connect(app, coordinator, project, single, user["id"])
    finally:
        await coordinator.aclose()

    assert several["status"] == "connected" and several["session_id"] is not None
    assert several["brains"] == [
        {"device_ref": "usb:AAA", "status": "connected", "error": None},
        {"device_ref": "usb:BBB", "status": "unreachable", "error": NOT_CONNECTED},
    ]
    assert one["status"] == "connected"
    assert set(one) == {"managed_by", "attempt_id", "status", "session_id", "error", "runtime_id"}


async def test_every_brain_opens_for_the_requesting_member(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """SOLUSDEV-326: the serial owner keys a claim by project AND member — a teammate's session
    may be on hardware hidden from the other (docs/api/hardware.md §1a) — so the requesting
    user's id reaches every brain's open, through the bench route and the coordinator alike."""
    local = app.state.bench_local = _BrainsLocal()
    alice = (await me(client, alice_headers))["id"]
    project, robot = await _robot_project(client, alice_headers)
    await _save_config(client, alice_headers, project, _two_brains(uuid.UUID(robot)))
    started = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )
    assert started.status_code == 201, started.text
    single = (
        await client.post(
            f"/api/v1/projects/{project}/entities",
            headers=alice_headers,
            json={"type": "physical_robot", "name": "Single"},
        )
    ).json()["data"]["id"]
    await _configure(client, alice_headers, project, single)
    coordinator = _coordinator(app, local)
    try:
        connected = await _connect(app, coordinator, project, single, alice)
    finally:
        await coordinator.aclose()

    assert connected["status"] == "connected"
    claims = [(opened["project_id"], opened["user_id"]) for opened in local.opened]
    assert claims == [(uuid.UUID(project), uuid.UUID(alice))] * 3  # two brains, then the single


# ------------------------------------------------------------------------- a busy device


class _BusyLocal(_BrainsLocal):
    """A local runner on which the `busy` bindings are held by something else (the serial owner
    refuses a second holder with a typed error, SOLUSDEV-326)."""

    def __init__(self, *busy: str) -> None:
        super().__init__()
        self.busy = set(busy)

    async def open_robot(
        self, config: dict[str, Any], *, project_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> TapConn:
        binding = config["identity"]["binding"]
        if binding in self.busy:
            self.attempts.append(binding)
            raise DeviceBusyError(f"usb:{binding}", "session")
        return await super().open_robot(config, project_id=project_id, user_id=user_id)


async def test_a_busy_device_refuses_the_session_with_409_device_busy(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    app.state.bench_local = _BusyLocal("5B42134331")
    project, robot = await _robot_project(client, alice_headers)
    await _configure(client, alice_headers, project, robot)

    response = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "device_busy"
    assert error["details"] == [{"device_ref": "usb:5B42134331", "holder": "session"}]
    assert app.state.bench_sessions.list(uuid.UUID(project)) == []


async def test_a_busy_brain_is_reported_and_the_robot_opens_on_the_other(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    local = app.state.bench_local = _BusyLocal("BBB")
    project, robot = await _robot_project(client, alice_headers)
    await _save_config(client, alice_headers, project, _two_brains(uuid.UUID(robot)))

    response = await _start(
        client, alice_headers, project, {"provider": "robot", "robot_entity_id": robot}
    )

    assert response.status_code == 201, response.text
    assert local.attempts == ["AAA", "BBB"]
    [unreachable] = response.json()["data"]["device"]["unreachable"]
    assert unreachable["device_ref"] == "usb:BBB" and "busy" in unreachable["error"]


async def test_the_coordinator_says_a_busy_device_is_in_use(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    local = _BusyLocal("5B42134331")
    user = await me(client, alice_headers)
    project, robot = await _robot_project(client, alice_headers)
    await _configure(client, alice_headers, project, robot)
    coordinator = _coordinator(app, local)
    try:
        state = await _connect(app, coordinator, project, robot, user["id"])
    finally:
        await coordinator.aclose()

    assert state["status"] == "failed" and state["session_id"] is None
    assert state["error"] == "The device is already in use."


# ------------------------------------------------------------------------- the host check


async def test_every_start_path_refuses_a_robot_confirmed_on_another_machine(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def this_host(self: LocalHostProvider) -> str | None:
        return "b" * 32

    monkeypatch.setattr(LocalHostProvider, "identity", this_host)
    local = app.state.bench_local = _BrainsLocal()
    user = await me(client, alice_headers)
    project, robot = await _robot_project(client, alice_headers)
    await _configure(client, alice_headers, project, robot)
    entity = await db.get(GraphEntity, uuid.UUID(robot))
    assert entity is not None
    entity.attrs = {**entity.attrs, "host_machine_id": "a" * 32}
    await db.commit()

    # The bench route.
    bench = await client.post(
        f"/api/v1/projects/{project}/bench/sessions",
        headers=alice_headers,
        json=_robot_session_body(robot),
    )
    assert bench.status_code == 409 and bench.json()["error"]["code"] == "host_mismatch"
    # The confirm-and-connect coordinator.
    coordinator = _coordinator(app, local)
    try:
        state = await _connect(app, coordinator, project, robot, user["id"])
    finally:
        await coordinator.aclose()
    assert state["status"] == "failed"
    assert state["error"] == "This robot runs on another machine; connect it there."
    # The session an accepted device suggestion starts.
    async with app.state.sessionmaker() as session:
        subject = await session.get(GraphEntity, uuid.UUID(robot))
        assert subject is not None
        started = await detection_service.start_robot_session(
            cast(Any, None),
            local,
            uuid.UUID(project),
            subject,
            1.0,
            session=session,
            account_id=uuid.UUID(user["id"]),
        )
    assert started == (None, "This robot is bound to another host machine; start the session there")
    assert local.attempts == []


# --------------------------------------------------------------------------- a lone part


async def test_a_lone_parts_session_resolves_its_telemetry_and_runs_no_robot_evaluator(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """A detected board kept as a part on its own is keyed by its device ref, so what it streams
    lands on it; its session carries its own channels and is not a robot's to judge."""
    views: list[SessionView] = []

    class _EvaluatorRecorder:
        def start(self, view: SessionView) -> asyncio.Task[None]:
            views.append(view)
            return asyncio.create_task(asyncio.sleep(3600))

    app.state.bench_sessions = SessionManager(
        app.state.telemetry_plumbing, evaluator_factory=lambda view: _EvaluatorRecorder()
    )
    local = app.state.bench_local = _BrainsLocal()
    project, _ = await _robot_project(client, alice_headers)
    created = await client.post(
        f"/api/v1/projects/{project}/hardware/entities",
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "kind": "part",
            "name": "Sensor board",
            "config": {
                "identity": [_brain("LONE", "lines")],
                "component": {"telemetry": [{"name": "a0", "unit": "V"}], "lifecycle": "live"},
                "provenance": {"identity": USER, "component": USER},
            },
        },
    )
    assert created.status_code == 201, created.text
    part = created.json()["data"]["entity"]
    assert part["source_key"] == "usb:LONE"  # the wire name of `external_ref`

    response = await _start(
        client, alice_headers, project, {"provider": "hardware", "entity_id": part["id"]}
    )

    assert response.status_code == 201, response.text
    record = response.json()["data"]
    assert record["robot_entity_id"] == part["id"]
    (opened,) = local.opened
    assert opened["config"]["parts"][part["id"]]["telemetry"] == [{"name": "a0", "unit": "V"}]
    (conn,) = local.conns
    await conn.tap(from_wire(wire_packet("usb:LONE", 0, {"a0": 1.25})))
    detail = (
        await client.get(
            f"/api/v1/projects/{project}/bench/sessions/{record['id']}", headers=alice_headers
        )
    ).json()["data"]
    assert detail["counts"] == {"ingested": 1, "unresolved": 0}
    assert views == []
    await app.state.bench_sessions.aclose_all()


# ------------------------------------------------------------------- the merged connection


async def test_the_merged_connection_reads_as_its_best_brain_and_closes_them_all() -> None:
    left, right = FakeConn(), FakeConn()
    left.device_facts = {"channel_roles": {"usb:A/1": {"x": "primary"}}}
    right.device_facts = {"channel_display": {"usb:B/1": {"y": {"display": "angle"}}}}
    merged = BrainsConnection([left, right])

    async def tap(packet: Any) -> None:
        return None

    merged.tap = tap
    assert left.tap is tap and right.tap is tap
    handle = await merged.subscribe(cast(Any, None))
    merged.on_batch(handle, cast(Any, None))
    assert merged.device_facts == {
        "channel_roles": {"usb:A/1": {"x": "primary"}},
        "channel_display": {"usb:B/1": {"y": {"display": "angle"}}},
    }
    right._status = LiveStatus.STREAMING
    await left.aclose()
    assert merged.status() is LiveStatus.STREAMING  # one brain's link down is not the robot's
    await merged.aclose()
    assert right.closed and merged.status() is LiveStatus.DISCONNECTED
