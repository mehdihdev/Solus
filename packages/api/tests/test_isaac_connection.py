"""Read-only application status projection; no simulator or GPU is launched."""

import asyncio
from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.tool import Tool
from solus_api.bridge.registry import BridgeSession, BridgeSessionRegistry, ScopeKey
from solus_api.services.isaac_connection import observe_connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def bridge() -> tuple[MagicMock, BridgeSession]:
    registry = MagicMock()
    current = SimpleNamespace(session_id="current")
    registry.get.return_value = current
    return registry, cast(BridgeSession, current)


def tools() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            descriptor=SimpleNamespace(name="isaac.probe"),
            invoke=AsyncMock(return_value={"available": True, "path": "private"}),
        ),
        SimpleNamespace(
            descriptor=SimpleNamespace(name="isaac.status"),
            invoke=AsyncMock(return_value={"state": "running", "model": "private"}),
        ),
        SimpleNamespace(descriptor=SimpleNamespace(name="isaac.start"), invoke=AsyncMock()),
    ]


async def test_projection_calls_only_read_operations_and_drops_raw_data() -> None:
    registry, current = bridge()
    owned = tools()
    result = await observe_connection(
        registry, (uuid4(), uuid4(), uuid4()), current, cast(Sequence[Tool], owned)
    )
    assert result.model_dump() == {
        "bridge": "connected",
        "installation": "installed",
        "owned_session": "running",
        "streaming": "none",
        "reason": None,
    }
    assert "private" not in result.model_dump_json()
    owned[2].invoke.assert_not_awaited()
    for tool in owned[:2]:
        tool.invoke.assert_awaited_once_with({})


async def test_false_probe_is_unknown_not_a_claim_of_missing_installation() -> None:
    registry, current = bridge()
    owned = tools()
    owned[0].invoke.return_value = {"available": False}
    owned[1].invoke.return_value = {"state": "stopped"}
    result = await observe_connection(
        registry, (uuid4(), uuid4(), uuid4()), current, cast(Sequence[Tool], owned)
    )
    assert result.installation == "unknown" and result.owned_session == "not_running"
    assert result.reason == "runtime_unverified"


async def test_replaced_bridge_discards_all_observations() -> None:
    registry, current = bridge()
    registry.get.return_value = SimpleNamespace(session_id="replacement")
    result = await observe_connection(
        registry, (uuid4(), uuid4(), uuid4()), current, cast(Sequence[Tool], tools())
    )
    assert result.bridge == "unavailable" and result.owned_session == "unknown"


async def test_timeout_is_bounded_and_has_no_mutating_fallback() -> None:
    registry, current = bridge()
    owned = tools()

    async def hang(_args: dict[str, object]) -> None:
        await asyncio.Event().wait()

    owned[0].invoke.side_effect = hang
    result = await observe_connection(
        registry, (uuid4(), uuid4(), uuid4()), current, cast(Sequence[Tool], owned), timeout=0.01
    )
    assert result.installation == "unknown" and result.reason == "observation_failed"
    owned[2].invoke.assert_not_awaited()


async def setup_route(
    client: AsyncClient, headers: dict[str, str], app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, list[SimpleNamespace], BridgeSession, ScopeKey]:
    from datetime import UTC, datetime, timedelta

    from conftest import me
    from solus_api.agent.tools.isaac_tools import build_isaac_tools
    from solus_api.routers import isaac_connection
    from test_hardware_router import _hw_project

    project, team = await _hw_project(client, headers)
    user = await me(client, headers)
    scope = (UUID(user["id"]), UUID(team), UUID(project))
    current = cast(
        BridgeSession,
        SimpleNamespace(
            scope=scope,
            session_id="read-only-session",
            token_exp=datetime.now(UTC) + timedelta(seconds=60),
        ),
    )
    app.state.bridge_sessions.bind(current)
    native = tools()
    native[1].invoke.return_value = {"state": "stopped", "model_entity_id": "private"}

    def owned(
        sessionmaker: async_sessionmaker[AsyncSession],
        project_id: UUID,
        registry: BridgeSessionRegistry,
        user_id: UUID,
        team_id: UUID,
        _cap: int,
    ) -> list[Tool]:
        assert (user_id, team_id, project_id) == scope
        assert registry.get(*scope) is current
        return build_isaac_tools(
            sessionmaker, project_id, {tool.descriptor.name: cast(Tool, tool) for tool in native}
        )

    monkeypatch.setattr(isaac_connection, "_owned_isaac_tools", owned)
    return f"/api/v1/projects/{project}/isaac/connection-status", native, current, scope


async def test_real_project_route_uses_owned_reads_and_safe_projection(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route, native, _, _ = await setup_route(client, alice_headers, app, monkeypatch)
    result = await client.get(route, headers=alice_headers)
    assert result.status_code == 200, result.text
    assert result.json()["data"] == {
        "bridge": "connected",
        "installation": "installed",
        "owned_session": "not_running",
        "streaming": "none",
        "reason": None,
    }
    assert "private" not in result.text
    native[2].invoke.assert_not_awaited()


@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("other_team", 404)])
async def test_auth_and_cross_tenant_never_reach_local_tools(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    actor: str,
    status: int,
) -> None:
    route, native, _, _ = await setup_route(client, alice_headers, app, monkeypatch)
    result = await client.get(route, headers={} if actor == "anonymous" else bob_headers)
    assert result.status_code == status, result.text
    for tool in native:
        tool.invoke.assert_not_awaited()


async def test_shared_project_still_uses_exact_users_bridge(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import BOB, add_member, me

    route, native, _, scope = await setup_route(client, alice_headers, app, monkeypatch)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, str(scope[1]), role="member")
    result = await client.get(route, headers=bob_headers)
    assert result.status_code == 200 and result.json()["data"]["bridge"] == "unavailable"
    for tool in native:
        tool.invoke.assert_not_awaited()


async def test_rate_limit_does_not_dispatch_extra_reads(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.services import artifacts

    route, native, _, _ = await setup_route(client, alice_headers, app, monkeypatch)
    # Keep the burst in one fixed window regardless of the wall-clock minute.
    clock = [1200.0]
    monkeypatch.setattr(artifacts, "time", SimpleNamespace(time=lambda: clock[0]))
    for _ in range(20):
        assert (await client.get(route, headers=alice_headers)).status_code == 200
    result = await client.get(route, headers=alice_headers)
    assert result.status_code == 429 and result.headers["Retry-After"] == "60"
    assert native[0].invoke.await_count == native[1].invoke.await_count == 20
    native[2].invoke.assert_not_awaited()
    clock[0] += 60
    assert (await client.get(route, headers=alice_headers)).status_code == 200
    assert native[0].invoke.await_count == native[1].invoke.await_count == 21


async def test_disconnect_during_read_discards_status(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route, native, current, _ = await setup_route(client, alice_headers, app, monkeypatch)

    async def disappear(_args: dict[str, object]) -> dict[str, bool]:
        app.state.bridge_sessions.remove(current)
        return {"available": True}

    native[0].invoke.side_effect = disappear
    result = await client.get(route, headers=alice_headers)
    assert result.status_code == 200 and result.json()["data"]["bridge"] == "unavailable"
    assert result.json()["data"]["installation"] == "unknown"
