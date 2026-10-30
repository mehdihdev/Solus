"""Leader → follower teleoperation routes (SOLUSDEV-319, ADR-014 amendment 2026-10-30).

API-implementation.md §15 "Teleoperation amendment". The loop itself lives in livebench (tested
there over fake actuators); these tests drive the routes and the manager through a fake
`livebench.local` and prove the gates: explicit confirmation of a fresh, ready preview; tenant
isolation; member role; stop holds (never releases); release refused on a running follower; and
every way a teleop ends.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.livebench.teleop import NotActuatedError, TeleopNotReadyError
from test_bench_router import FakeLocal, TapConn


def _wire(ready: bool = True, blockers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "ready": ready,
        "blockers": blockers or [],
        "pairs": [
            {
                "address": 1,
                "leader_signal": "leader-shoulder_pan.position",
                "follower_signal": "follower-shoulder_pan.position",
                "unit": "deg",
                "leader_value": 10.0,
                "follower_value": 12.0 if ready else 40.0,
                "delta": -2.0 if ready else -30.0,
                "within_tolerance": ready,
            }
        ],
        "tolerance": {"deg": 15.0, "%": 20.0},
    }


class FakeLoop:
    def __init__(self, on_stopped: Callable[[str], object]) -> None:
        self.on_stopped = on_stopped
        self.stop_reason: str | None = None
        self.rate_hz = 30.0
        self.pairs = [
            {"address": 1, "leader_signal": "l.position", "follower_signal": "f.position"}
        ]

    @property
    def running(self) -> bool:
        return self.stop_reason is None

    async def stop(self, reason: str = "user") -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
            self.on_stopped(reason)


class TeleopLocal(FakeLocal):
    def __init__(self) -> None:
        super().__init__()
        self.preview_wire = _wire()
        self.start_refusal: Exception | None = None
        self.release_error: Exception | None = None
        self.loops: list[FakeLoop] = []
        self.started_with: list[tuple[TapConn, TapConn]] = []
        self.released: list[TapConn] = []
        self.events: list[str] = []

    def teleop_preview(self, leader: TapConn, follower: TapConn) -> dict[str, Any]:
        return self.preview_wire

    async def teleop_start(
        self, leader: TapConn, follower: TapConn, *, on_stopped: Callable[[str], object]
    ) -> FakeLoop:
        if self.start_refusal is not None:
            raise self.start_refusal
        self.started_with.append((leader, follower))

        def stopped(reason: str) -> None:
            self.events.append(f"stopped:{reason}")
            on_stopped(reason)

        loop = FakeLoop(stopped)
        self.loops.append(loop)
        return loop

    def robot_release(self, conn: TapConn) -> None:
        if self.release_error is not None:
            raise self.release_error
        self.released.append(conn)


@pytest.fixture
def teleop_local(app: FastAPI) -> TeleopLocal:
    fake = TeleopLocal()
    app.state.bench_local = fake
    return fake


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"]), str(team["id"])


async def _session(client: AsyncClient, headers: dict[str, str], project: str, serial: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions",
        headers=headers,
        json={"mode": "real", "config": {"provider": "serial", "serial_number": serial}},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


async def _pair(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    project, _ = await _project(client, headers)
    leader = await _session(client, headers, project, "LEADER0001")
    follower = await _session(client, headers, project, "FOLLOW0001")
    return project, leader, follower


async def _preview(
    client: AsyncClient, headers: dict[str, str], project: str, leader: str, follower: str
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/teleop/preview",
        headers=headers,
        json={"leader_session_id": leader, "follower_session_id": follower},
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _start(
    client: AsyncClient, headers: dict[str, str], project: str, preview_id: str
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project}/bench/teleop",
        headers=headers,
        json={"preview_id": preview_id, "confirm": True},
    )


async def test_preview_names_both_robots_and_the_paired_joints(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    data = await _preview(client, alice_headers, project, leader, follower)
    uuid.UUID(data["preview_id"])
    assert data["leader"]["session_id"] == leader and data["follower"]["session_id"] == follower
    assert data["leader"]["label"] and data["expires_at"]
    assert data["ready"] is True and data["pairs"][0]["address"] == 1


async def test_preview_refuses_one_session_as_both_ends(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, _ = await _pair(client, alice_headers)
    data = await _preview(client, alice_headers, project, leader, leader)
    assert data["ready"] is False
    assert [b["code"] for b in data["blockers"]] == ["same_session"]


async def test_preview_reports_a_robot_without_an_actuator_as_a_blocker(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)

    def unactuated(leader: TapConn, follower: TapConn) -> dict[str, Any]:
        raise NotActuatedError("this robot's driver cannot be driven")

    teleop_local.teleop_preview = unactuated  # type: ignore[method-assign]
    data = await _preview(client, alice_headers, project, leader, follower)
    assert data["ready"] is False and data["blockers"][0]["code"] == "not_actuated"
    assert (await _start(client, alice_headers, project, data["preview_id"])).status_code == 409


async def test_start_runs_the_loop_on_the_previewed_sessions(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 201, resp.text
    teleop = resp.json()["data"]
    assert teleop["state"] == "running" and teleop["stop_reason"] is None
    assert teleop["leader"]["session_id"] == leader and teleop["follower"]["session_id"] == follower
    assert teleop["rate_hz"] == 30.0 and teleop["pairs"][0]["address"] == 1
    conns = teleop_local.conns
    assert teleop_local.started_with == [(conns[0], conns[1])]
    current = await client.get(f"/api/v1/projects/{project}/bench/teleop", headers=alice_headers)
    assert current.json()["data"]["id"] == teleop["id"]


async def test_start_needs_explicit_confirmation(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    for body in (
        {"preview_id": preview["preview_id"]},
        {"preview_id": preview["preview_id"], "confirm": False},
    ):
        resp = await client.post(
            f"/api/v1/projects/{project}/bench/teleop", headers=alice_headers, json=body
        )
        assert resp.status_code == 422, resp.text
    assert teleop_local.loops == []


async def test_start_refuses_a_preview_that_is_not_ready(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    teleop_local.preview_wire = _wire(ready=False)
    preview = await _preview(client, alice_headers, project, leader, follower)
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "teleop_not_ready"
    assert teleop_local.loops == []


async def test_start_returns_the_fresh_preview_when_the_arms_moved_apart(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    teleop_local.start_refusal = TeleopNotReadyError(_wire(ready=False))
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "teleop_not_ready"
    assert error["details"][0]["pairs"][0]["within_tolerance"] is False


async def test_an_expired_or_unknown_preview_is_gone(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal, app: FastAPI
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    app.state.bench_teleop.clock = lambda: float("inf")
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 410 and resp.json()["error"]["code"] == "preview_expired"
    assert (await _start(client, alice_headers, project, str(uuid.uuid4()))).status_code == 410


async def test_a_preview_is_single_use(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    assert (await _start(client, alice_headers, project, preview["preview_id"])).status_code == 201
    await client.post(f"/api/v1/projects/{project}/bench/teleop/stop", headers=alice_headers)
    assert (await _start(client, alice_headers, project, preview["preview_id"])).status_code == 410


async def test_one_teleop_per_project(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    first = await _preview(client, alice_headers, project, leader, follower)
    second = await _preview(client, alice_headers, project, leader, follower)
    assert (await _start(client, alice_headers, project, first["preview_id"])).status_code == 201
    resp = await _start(client, alice_headers, project, second["preview_id"])
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "teleop_running"
    again = await _preview(client, alice_headers, project, leader, follower)
    assert "teleop_running" in [b["code"] for b in again["blockers"]]


async def test_stop_holds_the_follower_and_is_idempotent(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    await _start(client, alice_headers, project, preview["preview_id"])
    url = f"/api/v1/projects/{project}/bench/teleop/stop"
    resp = await client.post(url, headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] == "stopped"
    assert resp.json()["data"]["stop_reason"] == "user"
    assert teleop_local.released == []  # stop never releases torque
    again = await client.post(url, headers=alice_headers)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["stop_reason"] == "user"


async def test_stop_with_no_teleop_returns_null(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, _ = await _project(client, alice_headers)
    resp = await client.post(f"/api/v1/projects/{project}/bench/teleop/stop", headers=alice_headers)
    assert resp.status_code == 200 and resp.json()["data"] is None
    got = await client.get(f"/api/v1/projects/{project}/bench/teleop", headers=alice_headers)
    assert got.json()["data"] is None


async def test_a_loop_that_stops_itself_reports_why(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    await _start(client, alice_headers, project, preview["preview_id"])
    await teleop_local.loops[0].stop("leader_lost")
    got = await client.get(f"/api/v1/projects/{project}/bench/teleop", headers=alice_headers)
    data = got.json()["data"]
    assert data["state"] == "stopped" and data["stop_reason"] == "leader_lost"
    assert data["stopped_at"] is not None


async def test_ending_either_session_stops_teleop_before_its_link_closes(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    await _start(client, alice_headers, project, preview["preview_id"])
    follower_conn = teleop_local.conns[1]
    original = follower_conn.aclose

    async def closing() -> None:
        teleop_local.events.append("follower_closed")
        await original()

    follower_conn.aclose = closing  # type: ignore[method-assign]
    await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{follower}/stop", headers=alice_headers
    )
    assert teleop_local.events == ["stopped:session_ended", "follower_closed"]


async def test_shutdown_stops_teleop(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal, app: FastAPI
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    await _start(client, alice_headers, project, preview["preview_id"])
    await app.state.bench_teleop.aclose()
    assert teleop_local.loops[0].stop_reason == "shutdown"


async def test_release_needs_confirmation_and_is_refused_on_the_running_follower(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    url = f"/api/v1/projects/{project}/bench/sessions/{follower}/release"
    assert (await client.post(url, headers=alice_headers, json={})).status_code == 422
    preview = await _preview(client, alice_headers, project, leader, follower)
    await _start(client, alice_headers, project, preview["preview_id"])
    resp = await client.post(url, headers=alice_headers, json={"confirm": True})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "teleop_running"
    assert teleop_local.released == []
    await client.post(f"/api/v1/projects/{project}/bench/teleop/stop", headers=alice_headers)
    assert (
        await client.post(url, headers=alice_headers, json={"confirm": True})
    ).status_code == 200
    assert teleop_local.released == [teleop_local.conns[1]]


async def test_release_of_an_unactuated_robot_is_a_conflict(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, _ = await _pair(client, alice_headers)
    teleop_local.release_error = NotActuatedError("no actuator")
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{leader}/release",
        headers=alice_headers,
        json={"confirm": True},
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "not_actuated"


async def test_unauthenticated_viewer_and_other_tenants_are_refused(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    teleop_local: TeleopLocal,
) -> None:
    project, team = await _project(client, alice_headers)
    leader = await _session(client, alice_headers, project, "LEADER0001")
    follower = await _session(client, alice_headers, project, "FOLLOW0001")
    base = f"/api/v1/projects/{project}/bench"
    preview_body = {"leader_session_id": leader, "follower_session_id": follower}
    calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("POST", f"{base}/teleop/preview", preview_body),
        ("POST", f"{base}/teleop", {"preview_id": str(uuid.uuid4()), "confirm": True}),
        ("GET", f"{base}/teleop", None),
        ("POST", f"{base}/teleop/stop", None),
        ("POST", f"{base}/sessions/{follower}/release", {"confirm": True}),
    ]
    for method, url, body in calls:
        assert (await client.request(method, url, json=body)).status_code == 401, url
    await me(client, bob_headers)
    for method, url, body in calls:
        resp = await client.request(method, url, headers=bob_headers, json=body)
        assert resp.status_code == 404, url
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    for method, url, body in calls:
        if method == "GET":
            continue  # viewers may watch a teleop, never drive one
        resp = await client.request(method, url, headers=bob_headers, json=body)
        assert resp.status_code == 403, url
    assert teleop_local.loops == [] and teleop_local.released == []


async def test_another_projects_session_cannot_be_paired(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    teleop_local: TeleopLocal,
) -> None:
    project, leader, _ = await _pair(client, alice_headers)
    bob_project, _ = await _project(client, bob_headers)
    bob_session = await _session(client, bob_headers, bob_project, "BOBARM0001")
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/teleop/preview",
        headers=alice_headers,
        json={"leader_session_id": leader, "follower_session_id": bob_session},
    )
    assert resp.status_code == 404
    released = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{bob_session}/release",
        headers=alice_headers,
        json={"confirm": True},
    )
    assert released.status_code == 404 and teleop_local.released == []


async def test_a_follower_that_cannot_be_held_fails_the_start_honestly(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    teleop_local.start_refusal = RuntimeError("servo 6 did not acknowledge torque on")
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "teleop_failed"
    got = await client.get(f"/api/v1/projects/{project}/bench/teleop", headers=alice_headers)
    assert got.json()["data"] is None


async def test_a_release_the_servos_did_not_acknowledge_is_reported(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, leader, _ = await _pair(client, alice_headers)
    teleop_local.release_error = RuntimeError("servos [6] did not acknowledge torque off")
    resp = await client.post(
        f"/api/v1/projects/{project}/bench/sessions/{leader}/release",
        headers=alice_headers,
        json={"confirm": True},
    )
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "release_failed"


# ── hardening (automated security review of d83eefbc..013670fa) ─────────────────


async def test_concurrent_starts_cannot_both_drive(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    import asyncio

    project, leader, follower = await _pair(client, alice_headers)
    first = await _preview(client, alice_headers, project, leader, follower)
    second = await _preview(client, alice_headers, project, leader, follower)
    gate = asyncio.Event()
    original = teleop_local.teleop_start

    async def slow_start(*args: Any, **kwargs: Any) -> FakeLoop:
        await gate.wait()
        return await original(*args, **kwargs)

    teleop_local.teleop_start = slow_start  # type: ignore[method-assign]
    racing = asyncio.gather(
        _start(client, alice_headers, project, first["preview_id"]),
        _start(client, alice_headers, project, second["preview_id"]),
    )
    await asyncio.sleep(0.05)
    gate.set()
    statuses = sorted(r.status_code for r in await racing)
    assert statuses == [201, 409]
    assert len(teleop_local.loops) == 1


async def test_a_session_ending_while_teleop_starts_stops_it(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal, app: FastAPI
) -> None:
    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    original = teleop_local.teleop_start

    async def start_then_lose_follower(*args: Any, **kwargs: Any) -> FakeLoop:
        loop = await original(*args, **kwargs)
        await app.state.bench_sessions.stop(uuid.UUID(project), uuid.UUID(follower))
        return loop

    teleop_local.teleop_start = start_then_lose_follower  # type: ignore[method-assign]
    resp = await _start(client, alice_headers, project, preview["preview_id"])
    assert resp.status_code == 404
    assert teleop_local.loops[0].stop_reason == "session_ended"
    got = await client.get(f"/api/v1/projects/{project}/bench/teleop", headers=alice_headers)
    assert got.json()["data"]["stop_reason"] == "session_ended"


async def test_the_driven_robot_cannot_be_released_or_paired_through_another_session(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    teleop_local: TeleopLocal,
) -> None:
    project, leader, follower = await _pair(client, alice_headers)  # follower serial FOLLOW0001
    preview = await _preview(client, alice_headers, project, leader, follower)
    assert (await _start(client, alice_headers, project, preview["preview_id"])).status_code == 201
    bob_project, _ = await _project(client, bob_headers)
    same_arm = await _session(client, bob_headers, bob_project, "FOLLOW0001")
    other_arm = await _session(client, bob_headers, bob_project, "BOBARM0001")
    released = await client.post(
        f"/api/v1/projects/{bob_project}/bench/sessions/{same_arm}/release",
        headers=bob_headers,
        json={"confirm": True},
    )
    assert released.status_code == 409 and released.json()["error"]["code"] == "teleop_running"
    assert teleop_local.released == []
    pairing = await _preview(client, bob_headers, bob_project, other_arm, same_arm)
    assert "teleop_running" in [b["code"] for b in pairing["blockers"]]


async def test_two_sessions_on_one_physical_robot_cannot_pair(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    project, _ = await _project(client, alice_headers)
    first = await _session(client, alice_headers, project, "SAMEARM001")
    second = await _session(client, alice_headers, project, "SAMEARM001")
    data = await _preview(client, alice_headers, project, first, second)
    assert data["ready"] is False and data["blockers"][0]["code"] == "same_session"


async def test_stop_pressed_while_teleop_is_starting_wins(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    import asyncio

    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    gate = asyncio.Event()
    original = teleop_local.teleop_start

    async def slow_start(*args: Any, **kwargs: Any) -> FakeLoop:
        await gate.wait()
        return await original(*args, **kwargs)

    teleop_local.teleop_start = slow_start  # type: ignore[method-assign]
    starting = asyncio.ensure_future(_start(client, alice_headers, project, preview["preview_id"]))
    await asyncio.sleep(0.05)
    await client.post(f"/api/v1/projects/{project}/bench/teleop/stop", headers=alice_headers)
    gate.set()
    resp = await starting
    assert resp.status_code == 201 and resp.json()["data"]["state"] == "stopped"
    assert teleop_local.loops[0].stop_reason == "user"


# ── Phase 4 security review ──────────────────────────────────────────────────────


async def test_a_release_in_flight_blocks_a_start_on_the_same_robot(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal
) -> None:
    import asyncio
    import threading

    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    releasing, finish = threading.Event(), threading.Event()
    original = teleop_local.robot_release

    def slow_release(conn: TapConn) -> None:
        releasing.set()
        finish.wait(5)
        original(conn)

    teleop_local.robot_release = slow_release  # type: ignore[method-assign]
    release = asyncio.ensure_future(
        client.post(
            f"/api/v1/projects/{project}/bench/sessions/{follower}/release",
            headers=alice_headers,
            json={"confirm": True},
        )
    )
    while not releasing.is_set():
        await asyncio.sleep(0.01)
    started = await _start(client, alice_headers, project, preview["preview_id"])
    during = await _preview(client, alice_headers, project, leader, follower)
    finish.set()
    assert (await release).status_code == 200
    assert started.status_code == 409 and started.json()["error"]["code"] == "teleop_running"
    assert "teleop_running" in [b["code"] for b in during["blockers"]]
    assert teleop_local.loops == []


async def test_previews_and_driving_routes_are_rate_limited(
    client: AsyncClient, alice_headers: dict[str, str], teleop_local: TeleopLocal, app: FastAPI
) -> None:
    from solus_api.bridge.service import ConnectRateLimiter

    project, leader, follower = await _pair(client, alice_headers)
    app.state.bench_teleop_limits = {
        "preview": ConnectRateLimiter(2),
        "drive": ConnectRateLimiter(1),
    }
    body = {"leader_session_id": leader, "follower_session_id": follower}
    url = f"/api/v1/projects/{project}/bench/teleop/preview"
    codes = [
        (await client.post(url, headers=alice_headers, json=body)).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    release = f"/api/v1/projects/{project}/bench/sessions/{leader}/release"
    ok = await client.post(release, headers=alice_headers, json={"confirm": True})
    assert ok.status_code == 200
    limited = await client.post(release, headers=alice_headers, json={"confirm": True})
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    # Stop is the safety control: never rate limited.
    stop = f"/api/v1/projects/{project}/bench/teleop/stop"
    for _ in range(3):
        assert (await client.post(stop, headers=alice_headers)).status_code == 200


async def test_a_stop_is_logged_with_its_teleop_and_project(
    client: AsyncClient,
    alice_headers: dict[str, str],
    teleop_local: TeleopLocal,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    project, leader, follower = await _pair(client, alice_headers)
    preview = await _preview(client, alice_headers, project, leader, follower)
    teleop = (await _start(client, alice_headers, project, preview["preview_id"])).json()["data"]
    with caplog.at_level(logging.INFO, logger="solus_api.livebench.teleop"):
        await teleop_local.loops[0].stop("leader_lost")
    line = next(r.getMessage() for r in caplog.records if "teleop stopped" in r.getMessage())
    assert teleop["id"] in line and project in line and "leader_lost" in line
