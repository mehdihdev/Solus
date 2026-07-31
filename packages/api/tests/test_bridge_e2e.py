"""End-to-end: real companion ↔ real uvicorn ↔ real mock MCP server (BRG-01/02).

The full chain the epic's done-check names: the companion discovers and
launches the vendored mock server (real MCP stdio), dials the bridge over a
real WebSocket with header-bearer auth, the cloud validates its inventory
against the allowlist, a SOL-registry ToolCall round-trips, failures stay
structured, timeouts are cloud-owned, and companion death fails fast.
"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from conftest import ALICE, TEST_DATABASE_URL, bearer, make_token
from fastapi import FastAPI
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools import ToolCall, ToolErrorCode, ToolRegistry
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_companion.channel import ChannelState, run_channel
from solus_companion.config import CompanionConfig, discover_servers
from solus_companion.supervisor import Supervisor
from sqlalchemy.ext.asyncio import AsyncEngine

# One directory serves both ends: the companion discovers/launches from it and
# the cloud loads its allowlist.yaml files from it.
MCP_ROOT = Path(__file__).parent.parent.parent / "companion" / "tests" / "fixtures" / "mcp_root"


@pytest.fixture
async def e2e_server(engine: AsyncEngine) -> Any:
    settings = Settings(
        supabase_jwt_secret="dummy-jwt-signing-value-tests-only",
        supabase_jwt_audience="authenticated",
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        sync_inline=True,
        bridge_allowlist_root=str(MCP_ROOT),
    )
    app = create_app(settings=settings, engine=engine)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield app, port
    finally:
        server.should_exit = True
        await task


async def _setup_project(port: int) -> tuple[dict[str, str], uuid.UUID, uuid.UUID, uuid.UUID]:
    headers = bearer(**ALICE)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        me = (await client.get("/api/v1/users/me", headers=headers)).json()["data"]
        team = (await client.post("/api/v1/teams", json={"name": "T"}, headers=headers)).json()[
            "data"
        ]
        project = (
            await client.post(
                f"/api/v1/teams/{team['id']}/projects", json={"name": "P"}, headers=headers
            )
        ).json()["data"]
    return headers, uuid.UUID(me["id"]), uuid.UUID(team["id"]), uuid.UUID(project["id"])


async def _wait_for(predicate: Any, timeout: float = 15.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


def _registry_for(
    app: FastAPI,
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    timeout: float | None = None,
) -> ToolRegistry:
    registry = build_sol_registry(
        app.state.sessionmaker,
        scope[2],
        bridge=app.state.bridge_sessions,
        user_id=scope[0],
        team_id=scope[1],
    )
    if timeout is not None:
        # Rebuild with a short registry timeout for the sleepy phase — the
        # cloud owns the bound (contract §5); tools are re-registered as-is.
        short = ToolRegistry(default_timeout=timeout)
        for registration in registry._registry.values():  # noqa: SLF001
            short.register(registration.tool)
        return short
    return registry


async def test_full_companion_cloud_round_trip(e2e_server: Any) -> None:
    app, port = e2e_server
    _headers, user_id, team_id, project_id = await _setup_project(port)
    scope = (user_id, team_id, project_id)

    launches = discover_servers(MCP_ROOT)
    assert [launch.name for launch in launches] == ["mock"]
    supervisor = Supervisor(launches)
    await supervisor.start_all()
    config = CompanionConfig(
        url=f"ws://127.0.0.1:{port}/api/v1/projects/{project_id}/bridge",
        token_source=lambda: make_token(ALICE["sub"], ALICE["email"]),
        integrations_root=MCP_ROOT,
        instance_id="e2e-instance",
        servers=launches,
        ping_interval=1.0,
    )
    state = ChannelState()
    channel = asyncio.create_task(run_channel(config, supervisor, state=state, backoff_base=0.05))
    try:
        # 1. The session binds and the validated inventory reaches SOL's tool set.
        await _wait_for(lambda: app.state.bridge_sessions.get(*scope) is not None)
        session = app.state.bridge_sessions.get(*scope)
        assert session.companion_instance_id == "e2e-instance"
        names = {spec.descriptor.name for spec in session.inventory}
        assert {"mock.echo", "mock.add", "mock.boom", "mock.sleepy"} <= names
        assert "mock.badschema" not in names  # corrupted schema gated cloud-side

        # 2. Happy round-trip: SOL registry → wire → companion → MCP → back.
        registry = _registry_for(app, scope)
        result = await registry.invoke(ToolCall(tool="mock.echo", args={"text": "hi"}))
        assert result.ok is True and result.value == {"result": "hi"}
        add = await registry.invoke(ToolCall(tool="mock.add", args={"a": 2, "b": 3}))
        assert add.ok is True and add.value == {"total": 5}

        # 3. A server-side failure stays a structured ToolResult, never a raise.
        boom = await registry.invoke(ToolCall(tool="mock.boom", args={}))
        assert boom.ok is False and boom.error is not None
        assert boom.error.code is ToolErrorCode.TOOL_ERROR

        # 4. Timeouts are cloud-owned; the late result is dropped as unknown.
        short = _registry_for(app, scope, timeout=0.5)
        sleepy = await short.invoke(ToolCall(tool="mock.sleepy", args={}))
        assert sleepy.ok is False and sleepy.error is not None
        assert sleepy.error.code is ToolErrorCode.TIMEOUT
        assert sleepy.error.retryable is True
        assert app.state.bridge_sessions.get(*scope).inflight == {}

        # 5. Companion death → bridge offline: fail fast, retryable.
        channel.cancel()
        await asyncio.gather(channel, return_exceptions=True)
        await _wait_for(lambda: app.state.bridge_sessions.get(*scope) is None)
        offline = await registry.invoke(ToolCall(tool="mock.echo", args={"text": "x"}))
        assert offline.ok is False and offline.error is not None
        assert offline.error.retryable is True
        assert "bridge offline" in offline.error.message
    finally:
        if not channel.done():
            channel.cancel()
            await asyncio.gather(channel, return_exceptions=True)
        await supervisor.stop_all()
