"""SOL bench.session_start / bench.session_stop (SOLUSDEV-319 B6): docs/api/bench-view.md §6,
§6.1. Both park a card with the route's own label; approval runs the same opener as
`POST /sessions`; refusals use the route's codes before anything is parked."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolErrorCode
from test_bench_router import FakeLocal
from test_bench_view_tools import Bench, error, make_bench, value, viewer_bench


@pytest.fixture
def fake_local(app: FastAPI) -> FakeLocal:
    fake = FakeLocal()
    app.state.bench_local = fake
    return fake


SERIAL = {"mode": "real", "config": {"provider": "serial", "serial_number": "ARM0000001"}}
MUJOCO = {"mode": "sim", "config": {"provider": "mujoco", "scene_name": "arm"}}


async def test_start_parks_a_card_with_the_route_label_then_starts_on_approval(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    parked = await bench.park("bench.session_start", **SERIAL)
    assert parked.confirmation_id is not None
    assert parked.preview == [
        {"label": "Action", "before": None, "after": "Start session"},
        {"label": "Source", "before": None, "after": "serial"},
        {"label": "Mode", "before": None, "after": "real"},
        {"label": "Device", "before": None, "after": "Serial ARM0000001"},
        {"label": "Window", "before": None, "after": "1 s"},
        {"label": "Serial number", "before": None, "after": "ARM0000001"},
    ]
    assert fake_local.opened == []  # nothing opened before approval
    record = value(await bench.decide(parked.confirmation_id))
    assert record["label"] == "Serial ARM0000001" and record["provider"] == "serial"
    assert [o["kind"] for o in fake_local.opened] == ["serial"]
    (event,) = await bench.events("bench.session_started")
    assert event.payload == {
        "provider": "serial",
        "mode": "real",
        "session_id": record["id"],
        "actor": "sol",
    }


async def test_sim_card_names_the_simulator(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    parked = await bench.park("bench.session_start", **MUJOCO)
    assert {"label": "Simulator", "before": None, "after": "MuJoCo arm"} in parked.preview


async def test_start_without_local_bench_is_refused_before_parking(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    app.state.bench_local = None
    bench = await make_bench(client, app, alice_headers)
    parked = await bench.park("bench.session_start", **SERIAL)
    assert parked.confirmation_id is None
    assert parked.result.error.message.startswith("source_unavailable")


async def test_start_with_an_unknown_robot_is_refused_before_parking(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    body = {"mode": "real", "config": {"provider": "robot", "robot_entity_id": str(uuid.uuid4())}}
    parked = await bench.park("bench.session_start", **body)
    assert parked.confirmation_id is None and "not found" in parked.result.error.message.lower()


async def test_start_rejects_args_outside_bench_session_in(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    bad = {"mode": "sim", "config": {"provider": "serial", "serial_number": "X"}, "extra": 1}
    parked = await bench.park("bench.session_start", **bad)
    assert parked.confirmation_id is None
    assert parked.result.error.code is ToolErrorCode.INVALID_ARGS


async def test_too_many_sessions_is_refused_before_parking(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    for n in range(4):
        body = {"mode": "real", "config": {"provider": "serial", "serial_number": f"ARM000000{n}"}}
        resp = await client.post(
            f"/api/v1/projects/{bench.scope.project_id}/bench/sessions",
            headers=alice_headers,
            json=body,
        )
        assert resp.status_code == 201, resp.text
    parked = await bench.park("bench.session_start", **SERIAL)
    assert parked.confirmation_id is None
    assert parked.result.error.message.startswith("too_many_sessions")


async def _started(bench: Bench) -> str:
    parked = await bench.park("bench.session_start", **SERIAL)
    return str(value(await bench.decide(parked.confirmation_id))["id"])


async def test_stop_parks_then_stops_on_approval(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    session_id = await _started(bench)
    parked = await bench.park("bench.session_stop", session_id=session_id)
    assert parked.preview == [
        {"label": "Action", "before": None, "after": "Stop session"},
        {"label": "Session", "before": "Serial ARM0000001", "after": "stopped"},
        {"label": "Provider", "before": "serial", "after": None},
    ]
    closed_at_park = fake_local.conns[0].closed
    assert closed_at_park is False
    record = value(await bench.decide(parked.confirmation_id))
    assert record["status"] == "ended" and fake_local.conns[0].closed is True
    (event,) = await bench.events("bench.session_stopped")
    assert event.payload["actor"] == "sol"


async def test_cross_team_session_id_is_not_found(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    fake_local: FakeLocal,
) -> None:
    alice = await make_bench(client, app, alice_headers)
    session_id = await _started(alice)
    bob = await make_bench(client, app, bob_headers)
    parked = await bob.park("bench.session_stop", session_id=session_id)
    assert parked.confirmation_id is None
    assert parked.result.error.code is ToolErrorCode.NOT_FOUND
    unknown = await alice.park("bench.session_stop", session_id=str(uuid.uuid4()))
    assert unknown.result.error.code is ToolErrorCode.NOT_FOUND
    assert fake_local.conns[0].closed is False


async def test_viewer_cannot_start_or_stop(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    fake_local: FakeLocal,
) -> None:
    owner = await make_bench(client, app, alice_headers)
    session_id = await _started(owner)
    viewer = await viewer_bench(client, app, owner, alice_headers, bob_headers)
    for tool, args in (
        ("bench.session_start", SERIAL),
        ("bench.session_stop", {"session_id": session_id}),
    ):
        parked = await viewer.park(tool, **args)
        assert parked.confirmation_id is None
        assert "member role" in parked.result.error.message
    error(
        await viewer.call("bench.session_stop", session_id=session_id), ToolErrorCode.UNAUTHORIZED
    )
    assert len(fake_local.opened) == 1 and fake_local.conns[0].closed is False


async def test_decide_reruns_the_route_checks(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    parked = await bench.park("bench.session_start", **SERIAL)
    app.state.bench_local = None  # the local bench went away while the card waited
    result = await bench.decide(parked.confirmation_id)
    assert not result.ok
    assert fake_local.opened == []
