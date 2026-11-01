"""SOL bench.setpoint (SOLUSDEV-319 B6): docs/api/bench-view.md §6.1 card rows, §6.2 refusals,
§8 events, and the 30/min rate limit. A fake `livebench.local` (test_bench_setpoint) stands in
for the bus; the confirmation gate is the real one."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.bench_view import SETPOINTS_PER_MINUTE
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.livebench.setpoint import (
    REFUSALS,
    SetpointManager,
    SetpointRefusedError,
    setpoint_manager,
)
from test_bench_setpoint import PAN, SetpointLocal
from test_bench_view_tools import Bench, error, make_bench, value, viewer_bench


@pytest.fixture
def local(app: FastAPI) -> SetpointLocal:
    fake = SetpointLocal()
    app.state.bench_local = fake
    return fake


@pytest.fixture
def manager(app: FastAPI, local: SetpointLocal) -> SetpointManager:
    return setpoint_manager(app)


async def _robot(client: AsyncClient, app: FastAPI, headers: dict[str, str]) -> tuple[Bench, str]:
    bench = await make_bench(client, app, headers)
    resp = await client.post(
        f"/api/v1/projects/{bench.scope.project_id}/bench/sessions",
        headers=headers,
        json={"mode": "real", "config": {"provider": "serial", "serial_number": "ARM0000001"}},
    )
    assert resp.status_code == 201, resp.text
    return bench, resp.json()["data"]["id"]


def _rows(preview: list[dict[str, Any]]) -> dict[str, Any]:
    return {row["label"]: row["after"] for row in preview}


async def _payloads(bench: Bench, kind: str) -> list[dict[str, Any]]:
    return [e.payload for e in await bench.events(f"bench.setpoint_{kind}")]


async def test_card_rows_name_robot_joint_current_value_target_and_motion(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], manager: SetpointManager
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    parked = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=40.0)
    assert parked.confirmation_id is not None
    assert [r["label"] for r in parked.preview] == [
        "Robot",
        "Joint",
        "Current value",
        "Target",
        "Motion",
    ]
    assert all(r["before"] is None for r in parked.preview)
    rows = _rows(parked.preview)
    assert rows["Robot"] == "Serial ARM0000001" and rows["Joint"] == PAN
    assert (rows["Current value"], rows["Target"]) == ("12.4 deg", "40.0 deg")
    assert rows["Motion"] == "One move, at most 6.0 deg per tick; ends at the target or after 5 s"
    assert await _payloads(bench, "requested") == [{"unit": "deg", "clamped": False, "code": None}]


async def test_clamped_target_row_and_approval_moves_once(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    parked = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=120.0)
    assert (
        _rows(parked.preview)["Target"]
        == "95.0 deg (requested 120.0 deg, clamped to calibrated range)"
    )
    assert local.handles == []  # nothing moves at park time
    move = value(await bench.decide(parked.confirmation_id))
    assert move["state"] == "moving" and move["target"] == 95.0 and move["clamped"] is True
    uuid.UUID(move["id"])
    assert len(local.handles) == 1
    assert len(await _payloads(bench, "requested")) == 1  # the decide-time re-preview is not one
    assert await _payloads(bench, "applied") == [{"unit": "deg", "clamped": True, "code": None}]


async def test_current_value_change_does_not_stale_but_target_change_does(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    original = local.setpoint_preview

    def moved(conn: Any, joint: str, target: float) -> dict[str, Any]:
        return {**original(conn, joint, target), "current": 30.0}

    first = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=40.0)
    monkeypatch.setattr(local, "setpoint_preview", moved)
    value(await bench.decide(first.confirmation_id))  # Current value moved: still approvable
    local.handles[0].end("reached")

    second = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=50.0)

    def recalibrated(conn: Any, joint: str, target: float) -> dict[str, Any]:
        return {**original(conn, joint, target), "target": 45.0, "clamped": True}

    monkeypatch.setattr(local, "setpoint_preview", recalibrated)
    error(await bench.decide(second.confirmation_id), ToolErrorCode.UNAUTHORIZED)  # stale
    assert len(local.handles) == 1


@pytest.mark.parametrize("code", sorted(set(REFUSALS) - {"unavailable", "in_flight"}))
async def test_each_bus_refusal_is_refused_before_parking_and_evented(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
    code: str,
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    local.refusal = SetpointRefusedError(code, unit="deg")
    parked = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=1.0)
    assert parked.confirmation_id is None
    assert parked.result.error.message.startswith(f"setpoint refused ({code}): ")
    (refused,) = await _payloads(bench, "refused")
    assert refused == {"unit": "deg", "clamped": None, "code": code}
    # Invoked directly (the decide-time execution path) the codes map exactly.
    expected = ToolErrorCode.INVALID_ARGS if code == "uncalibrated" else ToolErrorCode.UNAVAILABLE
    message = error(
        await bench.call("bench.setpoint", session_id=session, joint=PAN, target=1.0), expected
    )
    assert message.startswith(f"setpoint refused ({code}): ")
    assert local.handles == []


async def test_no_local_bench_is_unavailable(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    app.state.bench_local = None
    parked = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=1.0)
    assert parked.confirmation_id is None
    assert parked.result.error.message.startswith("setpoint refused (unavailable): ")
    error(
        await bench.call("bench.setpoint", session_id=session, joint=PAN, target=1.0),
        ToolErrorCode.UNAVAILABLE,
    )
    assert (await _payloads(bench, "refused"))[0]["code"] == "unavailable"


async def test_in_flight_and_teleop_started_after_park_refuse_at_decision(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    first = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=40.0)
    second = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=50.0)
    value(await bench.decide(first.confirmation_id))
    result = await bench.decide(second.confirmation_id)  # first is still moving
    assert result.error is not None and "setpoint refused (in_flight)" in result.error.message
    assert len(local.handles) == 1
    assert (await _payloads(bench, "refused"))[-1]["code"] == "in_flight"


async def test_unknown_or_cross_team_session_and_unknown_joint_are_not_found(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    alice, session = await _robot(client, app, alice_headers)
    bob = await make_bench(client, app, bob_headers)
    for bench, sid in ((bob, session), (alice, str(uuid.uuid4()))):
        parked = await bench.park("bench.setpoint", session_id=sid, joint=PAN, target=1.0)
        assert parked.confirmation_id is None
        assert parked.result.error.code is ToolErrorCode.NOT_FOUND
        error(
            await bench.call("bench.setpoint", session_id=sid, joint=PAN, target=1.0),
            ToolErrorCode.NOT_FOUND,
        )
    joint = await alice.park("bench.setpoint", session_id=session, joint="elbow.pos", target=1.0)
    assert joint.confirmation_id is None and "not found" in joint.result.error.message
    error(
        await alice.call("bench.setpoint", session_id=session, joint="elbow.pos", target=1.0),
        ToolErrorCode.NOT_FOUND,
    )
    assert local.handles == []


async def test_bad_args_are_refused_by_the_schema(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], manager: SetpointManager
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    for args in (
        {"session_id": session, "joint": PAN},
        {"session_id": session, "joint": PAN, "target": "40"},
        {"session_id": session, "joint": PAN, "target": 1.0, "speed": 9},
        {"session_id": "nope", "joint": PAN, "target": 1.0},
    ):
        parked = await bench.park("bench.setpoint", **args)
        assert parked.confirmation_id is None
        assert parked.result.error.code is ToolErrorCode.INVALID_ARGS


async def test_viewer_is_refused(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    owner, session = await _robot(client, app, alice_headers)
    viewer = await viewer_bench(client, app, owner, alice_headers, bob_headers)
    parked = await viewer.park("bench.setpoint", session_id=session, joint=PAN, target=1.0)
    assert parked.confirmation_id is None and "member role" in parked.result.error.message
    error(
        await viewer.call("bench.setpoint", session_id=session, joint=PAN, target=1.0),
        ToolErrorCode.UNAUTHORIZED,
    )
    assert local.handles == []


async def test_rate_limit_is_30_a_minute_and_shares_the_teleop_drive_budget(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    bench, session = await _robot(client, app, alice_headers)
    for _ in range(SETPOINTS_PER_MINUTE):
        value(await bench.call("bench.setpoint", session_id=session, joint=PAN, target=1.0))
        local.handles[-1].end("reached")
    message = error(
        await bench.call("bench.setpoint", session_id=session, joint=PAN, target=1.0),
        ToolErrorCode.UNAVAILABLE,
    )
    assert message.startswith("rate_limited")
    assert len(local.handles) == SETPOINTS_PER_MINUTE
    drive = app.state.bench_teleop_limits["drive"]
    assert drive._counts[str(bench.scope.user_id)][1] == SETPOINTS_PER_MINUTE
