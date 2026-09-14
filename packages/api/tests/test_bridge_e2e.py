"""End-to-end: real companion ↔ real uvicorn ↔ real mock MCP server (BRG-01/02).

The full chain the epic's done-check names: the companion discovers and
launches the vendored mock server (real MCP stdio), dials the bridge over a
real WebSocket with header-bearer auth, the cloud validates its inventory
against the allowlist, a SOL-registry ToolCall round-trips, failures stay
structured, timeouts are cloud-owned, and companion death fails fast.
"""

import asyncio
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from conftest import ALICE, TEST_DATABASE_URL, bearer, make_token
from fastapi import FastAPI
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools import ToolCall, ToolErrorCode, ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.bridge.service import fetch_artifact
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_companion.channel import ChannelState, run_channel
from solus_companion.config import INTERPRETER_ENV, CompanionConfig, discover_servers
from solus_companion.supervisor import Supervisor
from sqlalchemy.ext.asyncio import AsyncEngine

# One directory serves both ends: the companion discovers/launches from it and
# the cloud loads its allowlist.yaml files from it.
MCP_ROOT = Path(__file__).parent.parent.parent / "companion" / "tests" / "fixtures" / "mcp_root"


@pytest.fixture
async def e2e_server(engine: AsyncEngine) -> Any:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret="dummy-jwt-signing-value-tests-only",
        supabase_jwt_audience="authenticated",
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
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
    # The committed private-env fixture is a shell shim, not an installed MCP
    # runtime. Use this test process's interpreter, as the supervisor tests do,
    # so launching pytest by absolute path does not select /usr/bin/python3.
    launches = tuple(
        replace(launch, env={**launch.env, INTERPRETER_ENV: sys.executable}) for launch in launches
    )
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

        # 3b. SOLUS-CAD-00c: binary output is STAGED, never inlined, and the
        # cloud pulls the real bytes back over the channel. This is the path a
        # STEP export takes for CAD-02/03/04 — before it existed the companion
        # dropped every non-text block outright.
        pic = await registry.invoke(ToolCall(tool="mock.pic", args={}))
        assert pic.ok is True and pic.value is not None
        block = pic.value["content"][0]
        assert block["inlined"] is False
        assert "BINARYSENTINEL" not in json.dumps(pic.value)  # bytes never rode the frame
        fetched = await fetch_artifact(session, block["artifact_id"])
        assert fetched == b"BINARYSENTINEL"

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


async def test_code_preview_shows_the_real_plan_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real I3 planning crosses the bridge without running scripts or creating venvs."""
    import importlib
    import sys

    from solus_api.agent.confirmations import _build_preview
    from solus_api.agent.runtime import _bridge_reader
    from solus_api.bridge.allowlist import BridgeToolSpec
    from solus_api.bridge.previews import preview_builder
    from solus_api.bridge.registry import InMemoryBridgeSessionRegistry
    from solus_api.bridge.tool import BridgeTool

    code_tests = Path(__file__).resolve().parents[3] / "integrations/mcp/code/tests"
    monkeypatch.syspath_prepend(str(code_tests))
    code_server = importlib.import_module("code_paths").overlay_module("server")
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        code_server, "pinned_which", lambda name: sys.executable if name == "python3.12" else None
    )
    built = code_server.build_server()
    scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    sessions = InMemoryBridgeSessionRegistry()
    dispatched: list[str] = []
    session = _code_session(built, scope, dispatched)
    inventory = {tool.name: tool for tool in await built.list_tools()}
    plan_spec = inventory["plan"]
    session.inventory = (
        BridgeToolSpec(
            server="code",
            remote_name="plan",
            descriptor=ToolDescriptor(
                name="code.plan",
                description=plan_spec.description or "Plan",
                params=plan_spec.inputSchema,
                returns=plan_spec.outputSchema or {"type": "object"},
            ),
        ),
    )
    sessions.bind(session)

    def tool(name: str) -> BridgeTool:
        spec = inventory[name]
        return BridgeTool(
            descriptor=ToolDescriptor(
                name=f"code.{name}",
                description=spec.description or name,
                params=spec.inputSchema,
                returns=spec.outputSchema or {"type": "object"},
                requires_confirmation=True,
                consent_summary="Run the approved I3 command",
            ),
            sessions=sessions,
            user_id=scope[0],
            team_id=scope[1],
            project_id=scope[2],
            call_cap_bytes=262_144,
            preview=preview_builder(
                f"code.{name}", _bridge_reader(sessions, *scope, 262_144, None)
            ),
        )

    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/pyvenv.cfg").write_text("home = /usr/bin\n")
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    script = tmp_path / "run.py"
    script.write_text("from pathlib import Path\nPath('executed').write_text('ran')\n")
    original = script.read_bytes()
    rows = await _build_preview(tool("run"), {"script": "run.py", "args": ["two words"]})
    by = {row["label"]: row["after"] for row in rows}
    assert by["command"] == ".venv/bin/python run.py 'two words'"
    assert by["cwd"] == "." and by["plan fingerprint"]
    steps = await _build_preview(tool("create_environment"), {"path": "vision", "python": "3.12"})
    by = {row["label"]: row["after"] for row in steps}
    assert by["command"] == "python3.12 -m venv vision"
    assert by["cwd"] == "." and by["plan fingerprint"]
    assert dispatched == ["code.plan", "code.plan"]
    assert not (tmp_path / "vision").exists()
    assert not (tmp_path / "executed").exists()
    assert script.read_bytes() == original


def _code_session(
    machine: Any, scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID], dispatched: list[str]
) -> Any:
    """A bound session dispatching real FastMCP tool calls through bridge ingestion."""
    from datetime import UTC, datetime

    from solus_api.bridge.registry import BridgeSession
    from solus_api.bridge.service import ingest_result

    session: BridgeSession

    async def _send(frame: str) -> None:
        call = json.loads(frame)["data"]
        dispatched.append(call["tool"])
        _content, structured = await machine.call_tool(call["tool"].split(".")[-1], call["args"])
        ingest_result(session, ToolResult.success(call["call_id"], structured))

    async def _close(code: int) -> None:
        return None

    session = BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(),
        send=_send,
        close=_close,
        max_inflight=8,
    )
    return session
