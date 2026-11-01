"""Teleop start and release end any in-flight setpoint first (SOLUSDEV-319 B5b).

docs/api/bench-view.md §6: "A teleop start, a session stop, a release or `POST /setpoint/stop`
ends the move". The TeleopManager calls its optional `setpoints.stop_robots(keys, reason)` before
the follower is held (teleop start) and before torque goes off (release); with no setpoint
manager wired its behaviour is unchanged.
"""

import uuid
from collections.abc import Iterable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.livebench.teleop import TeleopManager, _device_key
from test_teleop_router import TeleopLocal, _pair, _preview, _start


class FakeSetpoints:
    def __init__(self, local: TeleopLocal) -> None:
        self.local = local
        self.calls: list[tuple[set[str], str]] = []
        self.error: Exception | None = None

    async def stop_robots(self, keys: Iterable[str], reason: str) -> None:
        self.calls.append((set(keys), reason))
        self.local.events.append(f"setpoint_stop:{reason}")
        if self.error is not None:
            raise self.error


@pytest.fixture
def teleop_local(app: FastAPI) -> TeleopLocal:
    fake = TeleopLocal()
    app.state.bench_local = fake
    return fake


@pytest.fixture
def setpoints(app: FastAPI, teleop_local: TeleopLocal) -> FakeSetpoints:
    fake = FakeSetpoints(teleop_local)
    app.state.bench_teleop.setpoints = fake
    return fake


def _key(app: FastAPI, project: str, session: str) -> str:
    out, _ = app.state.bench_sessions.connection(uuid.UUID(project), uuid.UUID(session))
    return _device_key(out)


def _record_start_and_release(local: TeleopLocal) -> None:
    start, release = local.teleop_start, local.robot_release

    async def recorded_start(*args: Any, **kwargs: Any) -> Any:
        local.events.append("hold")
        return await start(*args, **kwargs)

    def recorded_release(conn: Any) -> None:
        local.events.append("torque_off")
        release(conn)

    setattr(local, "teleop_start", recorded_start)  # noqa: B010
    setattr(local, "robot_release", recorded_release)  # noqa: B010


async def test_teleop_start_stops_a_setpoint_on_its_robots_before_holding(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    teleop_local: TeleopLocal,
    setpoints: FakeSetpoints,
) -> None:
    _record_start_and_release(teleop_local)
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 201, resp.text
    keys = {_key(app, project, leader), _key(app, project, follower)}
    assert setpoints.calls == [(keys, "teleop")]
    assert teleop_local.events[:2] == ["setpoint_stop:teleop", "hold"]


async def test_release_stops_a_setpoint_before_torque_off(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    teleop_local: TeleopLocal,
    setpoints: FakeSetpoints,
) -> None:
    _record_start_and_release(teleop_local)
    project, leader, _ = await _pair(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{leader}/release",
        headers=alice_headers,
        json={"confirm": True},
    )
    assert resp.status_code == 200, resp.text
    assert setpoints.calls == [({_key(app, project, leader)}, "release")]
    assert teleop_local.events == ["setpoint_stop:release", "torque_off"]


async def test_a_setpoint_stop_that_fails_aborts_the_release_before_torque_off(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    teleop_local: TeleopLocal,
    setpoints: FakeSetpoints,
) -> None:
    project, leader, _ = await _pair(client, alice_headers)
    setpoints.error = RuntimeError("stop failed")
    manager: TeleopManager = app.state.bench_teleop
    with pytest.raises(RuntimeError):
        await manager.release(uuid.UUID(project), uuid.UUID(leader))
    assert teleop_local.released == []
    assert manager.robot_role(_key(app, project, leader)) is None  # the claim was dropped


async def test_without_a_setpoint_manager_start_and_release_are_unchanged(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    app.state.bench_teleop.setpoints = None  # main.py's manager wires itself; unwire it
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    assert (await _start(client, alice_headers, project, preview["preview_id"])).status_code == 201
    await client.post(f"/api/v1/projects/{project}/bench/teleop/stop", headers=alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{follower}/release",
        headers=alice_headers,
        json={"confirm": True},
    )
    assert resp.status_code == 200 and teleop_local.released == [teleop_local.conns[1]]


async def test_read_accessors_report_project_and_robot_state(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    manager: TeleopManager = app.state.bench_teleop
    project, leader, follower = await _pair(client, alice_headers)
    leader_key, follower_key = _key(app, project, leader), _key(app, project, follower)
    assert isinstance(manager.start_lock, type(manager._start_lock))
    assert manager.project_active(uuid.UUID(project)) is False
    assert manager.robot_role(leader_key) is None
    preview = await _preview(client, alice_headers, project, leader, follower)
    await _start(client, alice_headers, project, preview["preview_id"])
    assert manager.project_active(uuid.UUID(project)) is True
    assert manager.project_active(uuid.uuid4()) is False
    assert manager.robot_role(leader_key) == "leader"
    assert manager.robot_role(follower_key) == "follower"
    await client.post(f"/api/v1/projects/{project}/bench/teleop/stop", headers=alice_headers)
    assert manager.project_active(uuid.UUID(project)) is False
    assert manager.robot_role(follower_key) is None
    manager._releasing.add(follower_key)
    assert manager.robot_role(follower_key) == "releasing"
