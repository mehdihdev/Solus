"""SOL setpoint manager and routes (SOLUSDEV-319, ADR-014 amendment 2026-10-31).

docs/api/bench-view.md §5 (GET /setpoint, POST /setpoint/stop) and §6.2 (refusal codes);
docs/architecture/bench-view.md §6. The move itself is tested in livebench over fake actuators;
here a fake `livebench.local` proves the manager's rules: single-use 30 s previews, one move in
flight per physical robot, refusals decided against teleoperation, stop on session end, and the
routes' auth, tenant isolation, role and idempotence.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.livebench.setpoint import (
    REFUSALS,
    SetpointManager,
    SetpointNotFoundError,
    SetpointRefusedError,
    emit_setpoint_event,
    router,
    setpoint_manager,
)
from solus_api.livebench.teleop import NotActuatedError, PreviewExpiredError
from solus_api.models import DataEvent
from sqlalchemy import select
from test_bench_router import TapConn
from test_teleop_router import TeleopLocal

PAN = "arm-shoulder_pan.position"


class FakeHandle:
    def __init__(self, target: float, on_ended: Callable[[str], object]) -> None:
        self.state = "moving"
        self.reason: str | None = None
        self.target = min(target, 95.0)
        self.clamped = target > 95.0
        self.unit = "deg"
        self.on_ended = on_ended

    def end(self, state: str, reason: str | None = None) -> None:
        if self.state == "moving":
            self.state, self.reason = state, reason
            self.on_ended(state)


class SetpointLocal(TeleopLocal):
    def __init__(self) -> None:
        super().__init__()
        self.refusal: Exception | None = None
        self.apply_refusal: Exception | None = None
        self.handles: list[FakeHandle] = []
        self.guards: list[Callable[[], str | None]] = []

    def setpoint_preview(self, conn: TapConn, joint: str, target: float) -> dict[str, Any]:
        if self.refusal is not None:
            raise self.refusal
        if joint != PAN:
            raise SetpointNotFoundError("joint")
        return {
            "address": 1,
            "joint": joint,
            "unit": "deg",
            "current": 12.4,
            "target": min(target, 95.0),
            "requested": target,
            "clamped": target > 95.0,
            "goal_ticks": 950,
            "max_step_ticks": 68,
            "max_step": 6.0,
        }

    async def setpoint_apply(
        self,
        conn: TapConn,
        joint: str,
        target: float,
        *,
        on_ended: Callable[[str], object],
        guard: Callable[[], str | None] | None = None,
        rate_hz: float | None = None,
    ) -> FakeHandle:
        if self.apply_refusal is not None:
            raise self.apply_refusal
        handle = FakeHandle(target, on_ended)
        self.handles.append(handle)
        if guard is not None:
            self.guards.append(guard)
        return handle

    async def setpoint_stop(self, handle: FakeHandle, reason: str = "user") -> None:
        handle.end("stopped", reason)


@pytest.fixture
def local(app: FastAPI) -> SetpointLocal:
    fake = SetpointLocal()
    app.state.bench_local = fake
    if not any(getattr(r, "path", "").endswith("/bench/setpoint") for r in app.routes):
        app.include_router(router)
    return fake


@pytest.fixture
def manager(app: FastAPI, local: SetpointLocal) -> SetpointManager:
    return setpoint_manager(app)


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[uuid.UUID, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"]), str(team["id"])


async def _session(
    client: AsyncClient, headers: dict[str, str], project: uuid.UUID, serial: str
) -> uuid.UUID:
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions",
        headers=headers,
        json={"mode": "real", "config": {"provider": "serial", "serial_number": serial}},
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["id"])


async def _robot(
    client: AsyncClient, headers: dict[str, str], serial: str = "ARM0000001"
) -> tuple[uuid.UUID, uuid.UUID, str]:
    project, team = await _project(client, headers)
    return project, await _session(client, headers, project, serial), team


async def _refused(code: str, call: Any) -> SetpointRefusedError:
    with pytest.raises(SetpointRefusedError) as caught:
        await call
    assert caught.value.code == code
    assert str(caught.value).startswith(f"setpoint refused ({code}): ")
    return caught.value


# ── manager: preview ─────────────────────────────────────────────────────────────


async def test_preview_names_the_robot_joint_current_and_clamped_target(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    data = await manager.preview(project, session, PAN, 120.0)
    uuid.UUID(data["preview_id"])
    assert data["session_id"] == str(session) and data["robot"] and data["expires_at"]
    assert (data["joint"], data["unit"], data["current"]) == (PAN, "deg", 12.4)
    assert (data["target"], data["requested"], data["clamped"]) == (95.0, 120.0, True)
    assert (data["max_step_ticks"], data["max_step"]) == (68, 6.0)


async def test_preview_unknown_session_or_joint_is_not_found(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    manager: SetpointManager,
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    with pytest.raises(SetpointNotFoundError):
        await manager.preview(project, uuid.uuid4(), PAN, 1.0)
    with pytest.raises(SetpointNotFoundError):
        await manager.preview(project, session, "arm-elbow.position", 1.0)
    bob_project, _, _ = await _robot(client, bob_headers, "BOBARM0001")
    with pytest.raises(SetpointNotFoundError):  # another team's session: not found, never moved
        await manager.preview(bob_project, session, PAN, 1.0)


async def test_preview_refuses_a_non_finite_target(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            await manager.preview(project, session, PAN, bad)


async def test_no_local_bench_is_unavailable(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    manager: SetpointManager,
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    app.state.bench_local = None
    await _refused("unavailable", manager.preview(project, session, PAN, 1.0))
    await _refused("unavailable", manager.start(project, uuid.uuid4()))


async def test_an_ended_session_is_not_connected(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    stopped = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{session}/stop", headers=alice_headers
    )
    assert stopped.status_code == 200, stopped.text
    await _refused("not_connected", manager.preview(project, session, PAN, 1.0))


@pytest.mark.parametrize("code", ["not_connected", "uncalibrated", "torque_off"])
async def test_bus_refusals_from_livebench_pass_through(
    client: AsyncClient,
    alice_headers: dict[str, str],
    manager: SetpointManager,
    local: Any,
    code: str,
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    local.refusal = SetpointRefusedError(code, unit="deg")
    refusal = await _refused(code, manager.preview(project, session, PAN, 1.0))
    assert refusal.unit == "deg"


async def test_a_driver_without_an_actuator_is_uncalibrated(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    local.refusal = NotActuatedError("read only")
    await _refused("uncalibrated", manager.preview(project, session, PAN, 1.0))


def test_refusal_codes_are_the_frozen_set() -> None:
    assert set(REFUSALS) == {
        "unavailable",
        "not_connected",
        "teleop_active",
        "follower",
        "uncalibrated",
        "torque_off",
        "in_flight",
    }
    with pytest.raises(ValueError):
        SetpointRefusedError("made_up")


# ── manager: start, single use, expiry, in flight ───────────────────────────────


async def test_start_consumes_the_preview_once_and_runs_one_move(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    preview = await manager.preview(project, session, PAN, 120.0)
    move = await manager.start(project, uuid.UUID(preview["preview_id"]))
    assert (move["state"], move["target"], move["clamped"], move["unit"]) == (
        "moving",
        95.0,
        True,
        "deg",
    )
    assert move["session_id"] == str(session) and move["joint"] == PAN
    assert manager.current(project) == {k: v for k, v in move.items() if k != "clamped"}
    with pytest.raises(PreviewExpiredError):
        await manager.start(project, uuid.UUID(preview["preview_id"]))
    assert len(local.handles) == 1


async def test_an_expired_or_foreign_preview_is_refused(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    manager: SetpointManager,
    local: Any,
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    now = [1000.0]
    manager.clock = lambda: now[0]
    preview = await manager.preview(project, session, PAN, 10.0)
    now[0] += 31
    with pytest.raises(PreviewExpiredError):
        await manager.start(project, uuid.UUID(preview["preview_id"]))
    fresh = await manager.preview(project, session, PAN, 10.0)
    bob_project, _, _ = await _robot(client, bob_headers, "BOBARM0001")
    with pytest.raises(PreviewExpiredError):  # previews are per project
        await manager.start(bob_project, uuid.UUID(fresh["preview_id"]))
    assert local.handles == []


async def test_one_move_in_flight_per_physical_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    manager: SetpointManager,
    local: Any,
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    first = await manager.preview(project, session, PAN, 10.0)
    second = await manager.preview(project, session, PAN, 20.0)
    await manager.start(project, uuid.UUID(first["preview_id"]))
    await _refused("in_flight", manager.preview(project, session, PAN, 30.0))
    await _refused("in_flight", manager.start(project, uuid.UUID(second["preview_id"])))
    bob_project, bob_same_arm, _ = await _robot(client, bob_headers, "ARM0000001")
    await _refused("in_flight", manager.preview(bob_project, bob_same_arm, PAN, 1.0))
    local.handles[0].end("reached")
    assert manager.current(project)["state"] == "reached"  # type: ignore[index]
    assert manager.current(project)["ended_at"] is not None  # type: ignore[index]
    again = await manager.preview(project, session, PAN, 30.0)
    assert (await manager.start(project, uuid.UUID(again["preview_id"])))["state"] == "moving"


async def test_a_refusal_at_apply_releases_the_reservation(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    preview = await manager.preview(project, session, PAN, 10.0)
    local.apply_refusal = SetpointRefusedError("torque_off", unit="deg")
    await _refused("torque_off", manager.start(project, uuid.UUID(preview["preview_id"])))
    local.apply_refusal = None
    assert manager.current(project) is None
    fresh = await manager.preview(project, session, PAN, 10.0)
    assert (await manager.start(project, uuid.UUID(fresh["preview_id"])))["state"] == "moving"


# ── teleoperation ────────────────────────────────────────────────────────────────


async def _teleop(
    client: AsyncClient,
    headers: dict[str, str],
    project: uuid.UUID,
    leader: uuid.UUID,
    follower: uuid.UUID,
) -> None:
    preview = await client.post(
        f"/api/v1/projects/{project}/bench/teleop/preview",
        headers=headers,
        json={"leader_session_id": str(leader), "follower_session_id": str(follower)},
    )
    started = await client.post(
        f"/api/v1/projects/{project}/bench/teleop",
        headers=headers,
        json={"preview_id": preview.json()["data"]["preview_id"], "confirm": True},
    )
    assert started.status_code == 201, started.text


async def test_refused_while_teleop_runs_in_the_project_or_drives_the_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    manager: SetpointManager,
) -> None:
    project, _ = await _project(client, alice_headers)
    leader = await _session(client, alice_headers, project, "LEADER0001")
    follower = await _session(client, alice_headers, project, "FOLLOW0001")
    spare = await _session(client, alice_headers, project, "SPARE00001")
    ready = await manager.preview(project, spare, PAN, 1.0)
    await _teleop(client, alice_headers, project, leader, follower)
    await _refused("teleop_active", manager.preview(project, spare, PAN, 1.0))
    await _refused("teleop_active", manager.start(project, uuid.UUID(ready["preview_id"])))
    bob_project, _ = await _project(client, bob_headers)
    same_follower = await _session(client, bob_headers, bob_project, "FOLLOW0001")
    same_leader = await _session(client, bob_headers, bob_project, "LEADER0001")
    await _refused("follower", manager.preview(bob_project, same_follower, PAN, 1.0))
    await _refused("teleop_active", manager.preview(bob_project, same_leader, PAN, 1.0))


async def test_a_teleop_starting_preempts_the_move_through_its_guard(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, _ = await _project(client, alice_headers)
    leader = await _session(client, alice_headers, project, "LEADER0001")
    follower = await _session(client, alice_headers, project, "FOLLOW0001")
    preview = await manager.preview(project, follower, PAN, 10.0)
    await manager.start(project, uuid.UUID(preview["preview_id"]))
    assert local.guards[0]() is None
    await _teleop(client, alice_headers, project, leader, follower)
    assert local.guards[0]() == "teleop"


async def test_stop_robots_stops_a_move_on_those_robots(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    preview = await manager.preview(project, session, PAN, 10.0)
    await manager.start(project, uuid.UUID(preview["preview_id"]))
    await manager.stop_robots({"usb:OTHER"}, "teleop")
    assert local.handles[0].state == "moving"
    await manager.stop_robots({"usb:ARM0000001"}, "release")
    assert (local.handles[0].state, local.handles[0].reason) == ("stopped", "release")


async def test_a_session_ending_stops_its_move(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    preview = await manager.preview(project, session, PAN, 10.0)
    await manager.start(project, uuid.UUID(preview["preview_id"]))
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{session}/stop", headers=alice_headers
    )
    assert resp.status_code == 200
    assert (local.handles[0].state, local.handles[0].reason) == ("stopped", "session_ended")


async def test_aclose_stops_moving_moves(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    preview = await manager.preview(project, session, PAN, 10.0)
    await manager.start(project, uuid.UUID(preview["preview_id"]))
    await manager.aclose()
    assert local.handles[0].reason == "shutdown"


# ── routes ───────────────────────────────────────────────────────────────────────


async def test_get_and_stop_routes(
    client: AsyncClient, alice_headers: dict[str, str], manager: SetpointManager, local: Any
) -> None:
    project, session, _ = await _robot(client, alice_headers)
    base = f"/api/v1/projects/{project}/bench/setpoint"
    assert (await client.get(base, headers=alice_headers)).json()["data"] is None
    assert (await client.post(f"{base}/stop", headers=alice_headers)).json()["data"] is None
    preview = await manager.preview(project, session, PAN, 40.0)
    move = await manager.start(project, uuid.UUID(preview["preview_id"]))
    got = (await client.get(base, headers=alice_headers)).json()["data"]
    assert set(got) == {
        "id",
        "session_id",
        "robot",
        "joint",
        "unit",
        "target",
        "state",
        "started_at",
        "ended_at",
    }
    assert got["id"] == move["id"] and got["state"] == "moving"
    for _ in range(3):  # idempotent, and never rate-limited
        stopped = await client.post(f"{base}/stop", headers=alice_headers)
        assert stopped.status_code == 200 and stopped.json()["data"]["state"] == "stopped"
    assert local.handles[0].reason == "user"


async def test_routes_without_a_local_bench_are_503(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, local: Any
) -> None:
    project, _ = await _project(client, alice_headers)
    app.state.bench_local = None
    base = f"/api/v1/projects/{project}/bench/setpoint"
    for resp in (
        await client.get(base, headers=alice_headers),
        await client.post(f"{base}/stop", headers=alice_headers),
    ):
        assert resp.status_code == 503 and resp.json()["error"]["code"] == "source_unavailable"


async def test_routes_auth_tenant_and_role(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    manager: SetpointManager,
    local: Any,
) -> None:
    project, session, team = await _robot(client, alice_headers)
    preview = await manager.preview(project, session, PAN, 10.0)
    await manager.start(project, uuid.UUID(preview["preview_id"]))
    base = f"/api/v1/projects/{project}/bench/setpoint"
    calls = [("GET", base), ("POST", f"{base}/stop")]
    for method, url in calls:
        assert (await client.request(method, url)).status_code == 401, url
    await me(client, bob_headers)
    for method, url in calls:
        assert (await client.request(method, url, headers=bob_headers)).status_code == 404, url
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    assert (await client.get(base, headers=bob_headers)).status_code == 200  # viewers read
    assert (await client.post(f"{base}/stop", headers=bob_headers)).status_code == 403
    assert local.handles[0].state == "moving"


# ── data events ──────────────────────────────────────────────────────────────────


async def test_setpoint_events_carry_only_unit_clamped_and_code(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    project, team = await _project(client, alice_headers)
    async with app.state.sessionmaker() as db:
        from solus_api.models import User

        user = (await db.execute(select(User).limit(1))).scalar_one()
        user.data_collection_consent = True
        emit_setpoint_event(
            db,
            user=user,
            team_id=uuid.UUID(team),
            project_id=project,
            kind="refused",
            unit=None,
            clamped=None,
            code="teleop_active",
        )
        emit_setpoint_event(
            db,
            user=user,
            team_id=uuid.UUID(team),
            project_id=project,
            kind="applied",
            unit="deg",
            clamped=True,
        )
        await db.commit()
        rows = (
            (await db.execute(select(DataEvent).where(DataEvent.project_id == project)))
            .scalars()
            .all()
        )
    events = {r.event_type: r.payload for r in rows if r.event_type.startswith("bench.setpoint")}
    assert events == {
        "bench.setpoint_refused": {"unit": None, "clamped": None, "code": "teleop_active"},
        "bench.setpoint_applied": {"unit": "deg", "clamped": True, "code": None},
    }
