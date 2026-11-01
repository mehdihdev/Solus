"""SOL bench view tools (SOLUSDEV-319 B6): docs/api/bench-view.md §6, §8.

`bench_view.read` (any role, optional live values), the two direct writes (member+, return
`inverse_ops` for Undo, refused in Guide mode), and `bench_view.delete_derived` (parks a card).
Helpers here are shared by the other bench tool suites.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import decide_confirmation, request_confirmation
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.tools.bench_view import BenchScope, build_bench_view_tools
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode, ToolResult
from solus_api.graph.packet import DeviceRecentView, RecentSample, SignalSeries
from solus_api.models import ConfirmationStatus, DataEvent, ToolConfirmation, User
from sqlalchemy import select

DEV = "usb:5A7A/3"
LIFT = 'sig("usb:5A7A/3", "shoulder_lift.goal") - sig("usb:5A7A/3", "shoulder_lift.position")'


@dataclass
class Bench:
    app: FastAPI
    scope: BenchScope
    registry: ToolRegistry

    async def call(self, tool: str, **args: Any) -> ToolResult:
        return await self.registry.invoke(ToolCall(tool=tool, args=args))

    async def park(self, tool: str, **args: Any) -> Any:
        async with self.app.state.sessionmaker() as db:
            parked = await request_confirmation(
                db,
                self.registry,
                ToolCall(tool=tool, args=args),
                project_id=self.scope.project_id,
                team_id=self.scope.team_id,
                user_id=self.scope.user_id,
            )
            await db.commit()
            return parked

    async def decide(self, confirmation_id: uuid.UUID, approve: bool = True) -> ToolResult:
        async with self.app.state.sessionmaker() as db:
            result = await decide_confirmation(
                db,
                self.registry,
                confirmation_id,
                approve=approve,
                project_id=self.scope.project_id,
                user_id=self.scope.user_id,
            )
            await db.commit()
            return result

    async def events(self, prefix: str) -> list[DataEvent]:
        async with self.app.state.sessionmaker() as db:
            rows = await db.scalars(
                select(DataEvent)
                .where(
                    DataEvent.project_id == self.scope.project_id,
                    DataEvent.event_type.startswith(prefix),
                )
                .order_by(DataEvent.created_at)
            )
            return list(rows)


def bench_for(app: FastAPI, scope: BenchScope, state: Any | None = "app") -> Bench:
    registry = ToolRegistry()
    for tool in build_bench_view_tools(
        app.state.sessionmaker, scope, app.state if state == "app" else state
    ):
        registry.register(tool)
    return Bench(app, scope, registry)


async def make_bench(
    client: AsyncClient, app: FastAPI, headers: dict[str, str], state: Any | None = "app"
) -> Bench:
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    scope = BenchScope(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        user_id=uuid.UUID(user["id"]),
    )
    async with app.state.sessionmaker() as db:  # events are stored only with consent
        row = await db.get(User, scope.user_id)
        assert row is not None
        row.data_collection_consent = True
        await db.commit()
    return bench_for(app, scope, state)


async def viewer_bench(
    client: AsyncClient,
    app: FastAPI,
    owner: Bench,
    owner_headers: dict[str, str],
    viewer_headers: dict[str, str],
) -> Bench:
    viewer = await me(client, viewer_headers)
    await add_member(client, owner_headers, viewer_headers, BOB, str(owner.scope.team_id), "viewer")
    scope = BenchScope(owner.scope.project_id, owner.scope.team_id, uuid.UUID(viewer["id"]))
    return bench_for(app, scope)


def sig(signal: str, device_id: str = DEV) -> dict[str, str]:
    return {"kind": "signal", "device_id": device_id, "signal": signal}


@pytest.fixture
async def bench(client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]) -> Bench:
    return await make_bench(client, app, alice_headers)


def value(result: ToolResult) -> dict[str, Any]:
    assert result.ok, result.error
    assert result.value is not None
    return result.value


def error(result: ToolResult, code: ToolErrorCode) -> str:
    assert not result.ok and result.error is not None, result
    assert result.error.code is code, result.error
    return result.error.message


# ── registration ────────────────────────────────────────────────────────────────


def test_descriptors_match_the_frozen_tool_table(bench: Bench) -> None:
    gated = {d.name: d.requires_confirmation for d in bench.registry.list()}
    assert gated == {
        "bench_view.read": False,
        "bench_view.update_display": False,
        "bench_view.upsert_derived": False,
        "bench_view.delete_derived": True,
        "bench.session_start": True,
        "bench.session_stop": True,
        "bench.setpoint": True,
    }
    for descriptor in bench.registry.list():
        assert descriptor.params.get("additionalProperties") is False, descriptor.name


def test_runtime_registers_the_bench_tools_once_per_person() -> None:
    from solus_api.agent.runtime import build_sol_registry
    from sqlalchemy.ext.asyncio import async_sessionmaker

    ids = dict(project_id=uuid.uuid4())
    names = [
        d.name
        for d in build_sol_registry(
            async_sessionmaker(), ids["project_id"], user_id=uuid.uuid4(), team_id=uuid.uuid4()
        ).list()
    ]
    assert names.count("bench_view.read") == 1 and names.count("bench.setpoint") == 1
    anonymous = [d.name for d in build_sol_registry(async_sessionmaker(), uuid.uuid4()).list()]
    assert not any(
        n.startswith(("bench_view.", "bench.session", "bench.setpoint")) for n in anonymous
    )


async def test_the_real_build_registry_offers_the_bench_view_tools(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The deps.get_sol_registry path SOL's turns use (GET /sol/tools reads the same one)."""
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    resp = await client.get(f"/api/v1/projects/{project['id']}/sol/tools", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    offered = {d["name"]: d for d in resp.json()["data"]}
    assert "bench_view.upsert_derived" in offered and "bench_view.read" in offered
    assert "measurement" in offered["bench_view.upsert_derived"]["description"]
    assert "constant" in offered["bench_view.upsert_derived"]["description"]


# ── read ────────────────────────────────────────────────────────────────────────


async def test_read_returns_the_default_view(bench: Bench) -> None:
    data = value(await bench.call("bench_view.read"))
    assert (data["version"], data["display"], data["derived"]) == (0, [], [])


async def test_read_adds_latest_values_from_the_telemetry_buffer(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = value(
        await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT)
    )

    def at(second: float) -> datetime:
        return datetime.fromtimestamp(1_800_000_000 + second, tz=UTC)

    async def recent(project_id: uuid.UUID, device_id: str, *, limit: int | None = None) -> Any:
        assert project_id == bench.scope.project_id and device_id == DEV and limit == 2000
        return DeviceRecentView(
            device_id=device_id,
            resolved_entity_id=None,
            signals=[
                SignalSeries(
                    signal="shoulder_lift.goal",
                    points=[RecentSample(timestamp=at(s), value=v) for s, v in ((0, 10), (1, 12))],
                ),
                SignalSeries(
                    signal="shoulder_lift.position",
                    points=[RecentSample(timestamp=at(s), value=v) for s, v in ((0, 9), (1, 8.5))],
                ),
            ],
        )

    monkeypatch.setattr(bench.app.state.telemetry_plumbing, "get_device_recent", recent)
    (entry,) = value(await bench.call("bench_view.read"))["derived"]
    assert entry["id"] == created["id"]
    assert entry["latest"]["value"] == pytest.approx(3.5)
    assert entry["latest"]["at"].startswith(at(1).isoformat()[:19])
    (bare,) = value(await bench.call("bench_view.read", include_values=False))["derived"]
    assert "latest" not in bare


async def test_read_values_are_null_without_samples_or_app_state(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    bench = await make_bench(client, app, alice_headers, state=None)
    value(await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT))
    (entry,) = value(await bench.call("bench_view.read"))["derived"]
    assert entry["latest"] == {"value": None, "at": None}


async def test_viewer_may_read_but_not_write(
    client: AsyncClient,
    app: FastAPI,
    bench: Bench,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    viewer = await viewer_bench(client, app, bench, alice_headers, bob_headers)
    assert value(await viewer.call("bench_view.read"))["version"] == 0
    op = {"kind": "set_display", "target": sig("a"), "patch": {"pinned": True}}
    error(await viewer.call("bench_view.update_display", ops=[op]), ToolErrorCode.UNAUTHORIZED)
    error(
        await viewer.call("bench_view.upsert_derived", name="x", expression=LIFT),
        ToolErrorCode.UNAUTHORIZED,
    )
    parked = await viewer.park("bench_view.delete_derived", id=str(uuid.uuid4()))
    assert parked.confirmation_id is None  # refused before parking
    assert value(await bench.call("bench_view.read"))["version"] == 0  # nothing written


async def test_another_teams_project_is_not_found(
    client: AsyncClient,
    app: FastAPI,
    bench: Bench,
    bob_headers: dict[str, str],
) -> None:
    other = await make_bench(client, app, bob_headers)
    stray = bench_for(
        app, BenchScope(bench.scope.project_id, other.scope.team_id, other.scope.user_id)
    )
    error(await stray.call("bench_view.read"), ToolErrorCode.NOT_FOUND)


# ── direct writes ───────────────────────────────────────────────────────────────


async def test_update_display_applies_and_returns_inverse_ops(bench: Bench) -> None:
    ops = [
        {"kind": "set_display", "target": sig("a"), "patch": {"pinned": True}},
        {"kind": "set_display", "target": sig("b"), "patch": {"pinned": True, "plot_group": "Arm"}},
    ]
    data = value(await bench.call("bench_view.update_display", ops=ops))
    assert data["version"] == 1
    assert data["summary"] == "Pinned 2 signals; Grouped 1 signal"
    assert data["inverse_ops"][0]["kind"] == "set_display"
    assert data["inverse_ops"][0]["patch"] == {"pinned": None, "plot_group": None}
    view = value(await bench.call("bench_view.read"))
    assert {e["target"]["signal"] for e in view["display"] if e["pinned"]} == {"a", "b"}
    (event,) = await bench.events("bench.view_updated")
    assert event.payload == {"actor": "sol", "op_kinds": ["set_display"], "version": 1}


async def test_update_display_rejects_other_op_kinds_and_bad_args(bench: Bench) -> None:
    error(
        await bench.call(
            "bench_view.update_display", ops=[{"kind": "delete_derived", "id": str(uuid.uuid4())}]
        ),
        ToolErrorCode.INVALID_ARGS,
    )
    error(
        await bench.call(
            "bench_view.update_display",
            ops=[{"kind": "set_display", "target": sig("a"), "patch": {}}],
        ),
        ToolErrorCode.INVALID_ARGS,
    )
    error(await bench.call("bench_view.update_display", ops=[]), ToolErrorCode.INVALID_ARGS)
    assert value(await bench.call("bench_view.read"))["version"] == 0


async def test_upsert_derived_creates_then_replaces(bench: Bench) -> None:
    created = value(
        await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT)
    )
    assert (created["version"], created["node_count"]) == (1, 3)
    assert created["inverse_ops"] == [{"kind": "delete_derived", "id": created["id"]}]
    assert created["summary"] == "Created derived signal ‹Lift error›"
    replaced = value(
        await bench.call(
            "bench_view.upsert_derived",
            id=created["id"],
            name="Lift error",
            expression=f"abs({LIFT})",
            unit="deg",
        )
    )
    assert replaced["id"] == created["id"] and replaced["node_count"] == 4
    assert replaced["inverse_ops"][0]["expression"] == LIFT
    assert replaced["summary"].startswith("Updated derived signal")
    kinds = [e.event_type for e in await bench.events("bench.derived_signal")]
    assert kinds == ["bench.derived_signal_created", "bench.derived_signal_updated"]


async def test_expression_error_is_invalid_args_with_codes_and_positions(bench: Bench) -> None:
    message = error(
        await bench.call("bench_view.upsert_derived", name="bad", expression='sig("a", "b") +'),
        ToolErrorCode.INVALID_ARGS,
    )
    assert message.startswith("expression_error: syntax at ")
    assert 'sig("a"' not in message  # never echoes the expression


async def test_guide_mode_refuses_both_direct_writes_and_every_gated_tool(bench: Bench) -> None:
    calls: list[str] = []

    async def dispatch(call: ToolCall) -> ToolResult:
        calls.append(call.tool)
        return ToolResult.success(call.call_id, {})

    guide = build_mode_dispatch(ActionMode.GUIDE, bench.registry.list(), dispatch)
    for name in [d.name for d in bench.registry.list()]:
        result = await guide(ToolCall(tool=name, args={}))
        assert result.ok is (name == "bench_view.read"), name
    assert calls == ["bench_view.read"]


# ── delete (gated) ──────────────────────────────────────────────────────────────


async def test_delete_parks_a_card_then_runs_on_approval(bench: Bench) -> None:
    created = value(
        await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT)
    )
    target = {"kind": "derived", "id": created["id"]}
    value(
        await bench.call(
            "bench_view.update_display",
            ops=[{"kind": "set_display", "target": target, "patch": {"pinned": True}}],
        )
    )
    parked = await bench.park("bench_view.delete_derived", id=created["id"])
    assert parked.confirmation_id is not None
    assert parked.preview == [
        {"label": "Derived signal", "before": "Lift error", "after": None},
        {"label": "Expression", "before": LIFT, "after": None},
        {"label": "Shown in", "before": "1 display settings", "after": "removed"},
    ]
    assert len(value(await bench.call("bench_view.read"))["derived"]) == 1  # nothing ran yet
    done = value(await bench.decide(parked.confirmation_id))
    assert done["version"] == 3
    assert [op["kind"] for op in done["inverse_ops"]] == ["upsert_derived", "set_display"]
    view = value(await bench.call("bench_view.read"))
    assert view["derived"] == [] and view["display"] == []


async def test_delete_unknown_id_is_refused_before_parking(bench: Bench) -> None:
    parked = await bench.park("bench_view.delete_derived", id=str(uuid.uuid4()))
    assert parked.confirmation_id is None
    assert "not found" in parked.result.error.message.lower()


async def test_delete_card_goes_stale_when_the_signal_changes(bench: Bench) -> None:
    created = value(
        await bench.call("bench_view.upsert_derived", name="Lift error", expression=LIFT)
    )
    parked = await bench.park("bench_view.delete_derived", id=created["id"])
    value(
        await bench.call(
            "bench_view.upsert_derived", id=created["id"], name="Renamed", expression=LIFT
        )
    )
    error(await bench.decide(parked.confirmation_id), ToolErrorCode.UNAUTHORIZED)
    async with bench.app.state.sessionmaker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
        assert row is not None and row.status is ConfirmationStatus.STALE
    assert len(value(await bench.call("bench_view.read"))["derived"]) == 1
