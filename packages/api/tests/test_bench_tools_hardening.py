"""SOL bench tools — Phase 4 hardening (SOLUSDEV-319 F2a).

- H-1: `bench_view.read` values are evaluated off the event loop under a total-work budget and a
  deadline; over either, `latest` is null with a reason code.
- M-2: `bench.session_start` cards show every non-default field that changes what is opened, so
  the stale-divergence check covers them.
- M-3: SOL's direct view writes share the REST PATCH limiter; setpoint previews go through the
  teleop preview limiter.
- L-6: `bench_view.read` refuses a caller who is no longer a member.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools import bench_view_tools
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.graph.packet import DeviceRecentView, RecentSample, SignalSeries
from solus_api.livebench.setpoint import SetpointManager, setpoint_manager
from solus_api.models import ConfirmationStatus, ToolConfirmation
from test_bench_router import FakeLocal
from test_bench_setpoint import PAN, SetpointLocal
from test_bench_view_tools import (
    DEV,
    LIFT,
    Bench,
    bench_for,
    error,
    make_bench,
    sig,
    value,
)

TOOLS_DIR = Path(bench_view_tools.__file__).parent


@pytest.fixture(name="bench")
async def _bench(client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]) -> Bench:
    return await make_bench(client, app, alice_headers)


# ── the split ───────────────────────────────────────────────────────────────────


def test_bench_modules_stay_under_the_file_limit_and_keep_public_paths() -> None:
    for path in TOOLS_DIR.glob("bench_*.py"):
        assert len(path.read_text().splitlines()) <= 800, path.name
    view = importlib.import_module("solus_api.agent.tools.bench_view")
    for name in (
        "BenchScope",
        "build_bench_view_tools",
        "bench_descriptors",
        "SETPOINTS_PER_MINUTE",
        "BenchViewOperations",
        "BenchSessionOperations",
        "SetpointOperations",
        "setpoint_limiters",
    ):
        assert hasattr(view, name), name
    sessions = importlib.import_module("solus_api.agent.tools.bench_session_tools")
    setpoint = importlib.import_module("solus_api.agent.tools.bench_setpoint_tool")
    assert view.BenchSessionOperations is sessions.BenchSessionOperations
    assert view.SetpointOperations is setpoint.SetpointOperations
    assert view.BenchViewOperations is bench_view_tools.BenchViewOperations


# ── H-1: bounded, off-loop value evaluation ─────────────────────────────────────


def _heavy(n: int) -> str:
    """A valid worst-case expression: 4 refs under 8 filters (parser depth limit 12)."""
    refs = [f'sig("{DEV}", "s{n}_{i}")' for i in range(4)]
    expr = f"({refs[0]} + {refs[1]}) + ({refs[2]} + {refs[3]})"
    for wrap in (
        "ma({}, 10)",
        "lowpass({}, 1)",
        "ma({}, 10)",
        "deriv({})",
        "ma({}, 10)",
        "integ({}, 1)",
        "ma({}, 10)",
        "lowpass({}, 1)",
    ):
        expr = wrap.format(expr)
    return expr


def _full_buffer(signal_names: list[str]) -> Any:
    base = 1_800_000_000.0

    points = [
        RecentSample(timestamp=datetime.fromtimestamp(base + k * 0.005, tz=UTC), value=k % 7)
        for k in range(2000)
    ]
    view = DeviceRecentView(  # built once, outside the timed read
        device_id=DEV,
        resolved_entity_id=None,
        signals=[SignalSeries(signal=name, points=points) for name in signal_names],
    )

    async def recent(project_id: uuid.UUID, device_id: str, *, limit: int | None = None) -> Any:
        assert limit == 2000
        return view

    return recent


async def _seed_heavy(bench: Bench, count: int) -> list[str]:
    names: list[str] = []
    for n in range(count):
        value(
            await bench.call("bench_view.upsert_derived", name=f"Heavy {n}", expression=_heavy(n))
        )
        names += [f"s{n}_{i}" for i in range(4)]
    return names


async def test_worst_case_read_is_bounded_and_never_blocks_the_loop(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = await _seed_heavy(bench, 32)
    monkeypatch.setattr(
        bench.app.state.telemetry_plumbing, "get_device_recent", _full_buffer(names)
    )
    gaps: list[float] = []
    done = asyncio.Event()

    async def ticker() -> None:
        last = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    tick = asyncio.create_task(ticker())
    started = time.monotonic()
    data = value(await bench.call("bench_view.read"))
    elapsed = time.monotonic() - started
    done.set()
    await tick
    assert elapsed < 6.0
    assert max(gaps) < 0.5, max(gaps)
    latest = [d["latest"] for d in data["derived"]]
    reasons = {d.get("latest_reason") for d in data["derived"]}
    assert len(latest) == 32
    assert "budget" in reasons  # 32 worst-case signals exceed the total-work budget
    assert any(v is not None and v["value"] is not None for v in latest)  # the first ones ran


async def test_over_budget_entries_are_null_with_reason_budget(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    value(await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT))
    monkeypatch.setattr(
        bench.app.state.telemetry_plumbing,
        "get_device_recent",
        _full_buffer(["shoulder_lift.goal", "shoulder_lift.position"]),
    )
    monkeypatch.setattr(bench_view_tools, "WORK_BUDGET", 10)
    (entry,) = value(await bench.call("bench_view.read"))["derived"]
    assert entry["latest"] is None and entry["latest_reason"] == "budget"


async def test_past_the_deadline_entries_are_null_with_reason_deadline(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    value(await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT))
    monkeypatch.setattr(
        bench.app.state.telemetry_plumbing,
        "get_device_recent",
        _full_buffer(["shoulder_lift.goal", "shoulder_lift.position"]),
    )
    monkeypatch.setattr(bench_view_tools, "DEADLINE_SECONDS", 0.0)
    (entry,) = value(await bench.call("bench_view.read"))["derived"]
    assert entry["latest"] is None and entry["latest_reason"] == "deadline"


async def test_within_budget_values_carry_no_reason(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    value(await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT))
    monkeypatch.setattr(
        bench.app.state.telemetry_plumbing,
        "get_device_recent",
        _full_buffer(["shoulder_lift.goal", "shoulder_lift.position"]),
    )
    (entry,) = value(await bench.call("bench_view.read"))["derived"]
    assert entry["latest"]["value"] == pytest.approx(0.0)
    assert "latest_reason" not in entry


# ── M-2: complete session_start card rows ───────────────────────────────────────


@pytest.fixture
def fake_local(app: FastAPI) -> FakeLocal:
    fake = FakeLocal()
    app.state.bench_local = fake
    return fake


def _rows(preview: list[dict[str, Any]]) -> dict[str, Any]:
    return {row["label"]: row["after"] for row in preview}


MJCF = "<mujoco><worldbody/></mujoco>"


async def test_mujoco_card_shows_scene_rate_duration_and_mjcf_digest(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    config = {
        "provider": "mujoco",
        "scene_name": "arm",
        "sample_hz": 100.0,
        "duration_seconds": 60.0,
        "mjcf_xml": MJCF,
    }
    parked = await bench.park("bench.session_start", mode="sim", config=config)
    rows = _rows(parked.preview)
    digest = hashlib.sha256(MJCF.encode()).hexdigest()[:12]
    assert rows["Scene"] == "arm"
    assert rows["Sample rate"] == "100 Hz"
    assert rows["Duration"] == "60 s"
    assert rows["MJCF"] == f"sha256 {digest} ({len(MJCF.encode())} bytes)"
    assert MJCF not in str(parked.preview)  # the XML itself never reaches the card


async def test_serial_card_shows_device_baud_and_driver(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    config = {
        "provider": "serial",
        "serial_number": "ARM0000001",
        "baud": 1_000_000,
        "driver_id": "feetech-sts",
        "driver_params": {"ids": "1-6", "note": "line\nbreak <b>"},
    }
    parked = await bench.park("bench.session_start", mode="real", config=config)
    rows = _rows(parked.preview)
    assert rows["Serial number"] == "ARM0000001"
    assert rows["Baud"] == "1000000"
    assert rows["Driver"] == "feetech-sts"
    params = rows["Driver params"]
    assert "\n" not in params and '"ids":"1-6"' in params and len(params) <= 200


async def test_default_fields_add_no_rows(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    bench = await make_bench(client, app, alice_headers)
    parked = await bench.park("bench.session_start", mode="sim", config={"provider": "mujoco"})
    assert [r["label"] for r in parked.preview] == [
        "Action",
        "Source",
        "Mode",
        "Simulator",
        "Window",
    ]


@pytest.mark.parametrize(
    ("config", "field", "changed"),
    [
        ({"provider": "mujoco", "scene_name": "arm"}, "scene_name", "other"),
        ({"provider": "mujoco"}, "sample_hz", 25.0),
        ({"provider": "mujoco"}, "duration_seconds", 10.0),
        ({"provider": "mujoco", "mjcf_xml": MJCF}, "mjcf_xml", MJCF.replace("/", " /")),
        ({"provider": "serial", "serial_number": "ARM0000001"}, "baud", 9600),
        ({"provider": "serial", "serial_number": "ARM0000001"}, "driver_id", "feetech-sts"),
        (
            {"provider": "serial", "serial_number": "ARM0000001"},
            "driver_params",
            {"ids": "1-6"},
        ),
        ({"provider": "serial", "serial_number": "ARM0000001"}, "serial_number", "ARM0000002"),
        (
            {"provider": "serial", "serial_number": "ARM0000001"},
            "confirmed_device_path",
            "/dev/tty.other",
        ),
    ],
)
async def test_changing_any_opened_field_between_park_and_decide_voids_the_card(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    fake_local: FakeLocal,
    config: dict[str, Any],
    field: str,
    changed: Any,
) -> None:
    bench = await make_bench(client, app, alice_headers)
    mode = "sim" if config["provider"] == "mujoco" else "real"
    parked = await bench.park("bench.session_start", mode=mode, config=config)
    assert parked.confirmation_id is not None
    async with app.state.sessionmaker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
        assert row is not None
        row.args = {**row.args, "config": {**row.args["config"], field: changed}}
        await db.commit()
    result = await bench.decide(parked.confirmation_id)
    assert not result.ok
    async with app.state.sessionmaker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
        assert row is not None and row.status is ConfirmationStatus.STALE
    assert fake_local.opened == []


# ── M-3: shared rate limits ─────────────────────────────────────────────────────


async def test_sol_direct_writes_share_the_rest_patch_limiter(
    client: AsyncClient, app: FastAPI, bench: Bench, alice_headers: dict[str, str]
) -> None:
    app.state.bench_view_limiter = ConnectRateLimiter(1)
    resp = await client.patch(
        f"/api/v1/projects/{bench.scope.project_id}/bench/view",
        headers=alice_headers,
        json={
            "version": 0,
            "ops": [{"kind": "set_display", "target": sig("a"), "patch": {"pinned": True}}],
        },
    )
    assert resp.status_code == 200, resp.text
    op = {"kind": "set_display", "target": sig("b"), "patch": {"pinned": True}}
    result = await bench.call("bench_view.update_display", ops=[op])
    assert error(result, ToolErrorCode.UNAVAILABLE).startswith("rate_limited")
    assert result.error is not None and result.error.retryable is True
    upsert = await bench.call("bench_view.upsert_derived", name="x", expression=LIFT)
    assert error(upsert, ToolErrorCode.UNAVAILABLE).startswith("rate_limited")
    assert value(await bench.call("bench_view.read"))["version"] == 1  # only the REST edit


async def test_sol_direct_writes_create_the_limiter_with_the_route_rate(bench: Bench) -> None:
    from solus_api.livebench.view.router import PATCHES_PER_MINUTE

    op = {"kind": "set_display", "target": sig("a"), "patch": {"pinned": True}}
    value(await bench.call("bench_view.update_display", ops=[op]))
    limiter = bench.app.state.bench_view_limiter
    assert limiter._limit == PATCHES_PER_MINUTE
    assert limiter._counts[str(bench.scope.user_id)][1] == 1


@pytest.fixture
def setpoint_local(app: FastAPI) -> SetpointLocal:
    fake = SetpointLocal()
    app.state.bench_local = fake
    return fake


@pytest.fixture
def manager(app: FastAPI, setpoint_local: SetpointLocal) -> SetpointManager:
    return setpoint_manager(app)


async def test_setpoint_preview_goes_through_the_teleop_preview_limiter(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    setpoint_local: SetpointLocal,
    manager: SetpointManager,
) -> None:
    bench = await make_bench(client, app, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{bench.scope.project_id}/bench/sessions",
        headers=alice_headers,
        json={"mode": "real", "config": {"provider": "serial", "serial_number": "ARM0000001"}},
    )
    assert resp.status_code == 201, resp.text
    session = resp.json()["data"]["id"]
    parked = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=40.0)
    assert parked.confirmation_id is not None
    preview = app.state.bench_teleop_limits["preview"]
    assert preview._counts[str(bench.scope.user_id)][1] >= 1
    app.state.bench_teleop_limits["preview"] = ConnectRateLimiter(0)
    refused = await bench.park("bench.setpoint", session_id=session, joint=PAN, target=41.0)
    assert refused.confirmation_id is None
    assert refused.result.error.message.startswith("rate_limited")
    assert setpoint_local.handles == []


# ── L-6: read needs a live membership ───────────────────────────────────────────


async def test_read_refuses_a_caller_without_membership(
    client: AsyncClient, app: FastAPI, bench: Bench, bob_headers: dict[str, str]
) -> None:
    other = await make_bench(client, app, bob_headers)
    outsider = bench_for(
        app, type(bench.scope)(bench.scope.project_id, bench.scope.team_id, other.scope.user_id)
    )
    error(await outsider.call("bench_view.read"), ToolErrorCode.UNAUTHORIZED)
