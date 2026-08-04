"""Supervisor: real MCP stdio protocol against the vendored mock fixture."""

import asyncio
import contextlib
import os
import signal
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from solus_companion.config import ServerLaunch
from solus_companion.supervisor import (
    ServerState,
    Supervisor,
    UnknownToolError,
    _child_env,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mcp_root"
LAUNCH = FIXTURE_ROOT / "mock" / "bin" / "launch"

EXPECTED_TOOLS = {"echo", "add", "boom", "sleepy", "plain", "pic", "badschema"}


# --- H3 (companion half): _child_env passes SOLUS_MCP_WORKSPACE through ---------


def test_child_env_passes_solus_mcp_workspace_through_when_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/solus")
    env = _child_env({"SOLUS_MCP_WORKSPACE": "/projects/robot"})
    assert env["SOLUS_MCP_WORKSPACE"] == "/projects/robot"
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/solus"


def test_child_env_omits_solus_mcp_workspace_when_not_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = _child_env({})
    assert "SOLUS_MCP_WORKSPACE" not in env


def _make_supervisor(pid_file: Path | None = None) -> Supervisor:
    env = {"MCP_MOCK_PID_FILE": str(pid_file)} if pid_file is not None else {}
    launch = ServerLaunch(name="mock", command=LAUNCH, env=env)
    return Supervisor((launch,), ping_timeout=2.0)


@pytest.fixture
async def supervisor() -> AsyncIterator[Supervisor]:
    sup = _make_supervisor()
    await sup.start_all()
    yield sup
    await sup.stop_all()


async def _wait_for_reap(pid: int) -> None:
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"child {pid} still alive")


def test_inventory_is_verbatim_no_prefiltering(supervisor: Supervisor) -> None:
    inventory = supervisor.inventory()
    assert [entry["server"] for entry in inventory] == ["mock"]
    tools: list[dict[str, Any]] = inventory[0]["tools"]
    by_name = {tool["name"]: tool for tool in tools}
    # VERBATIM: badschema advertised too — the cloud allowlist is the gate.
    assert set(by_name) == EXPECTED_TOOLS
    assert by_name["badschema"]["input_schema"] == {"type": "not-a-real-type"}
    for tool in tools:
        assert set(tool) == {"name", "description", "input_schema", "output_schema"}
    assert by_name["add"]["output_schema"] is not None


async def test_call_tool_echo_structured(supervisor: Supervisor) -> None:
    result = await supervisor.call_tool("mock", "echo", {"text": "hi"})
    assert result.isError is False
    assert result.structuredContent == {"result": "hi"}


async def test_call_tool_boom_is_error_result(supervisor: Supervisor) -> None:
    result = await supervisor.call_tool("mock", "boom", {})
    assert result.isError is True


async def test_unknown_server_and_tool_raise(supervisor: Supervisor) -> None:
    with pytest.raises(UnknownToolError):
        await supervisor.call_tool("ghost", "echo", {})
    with pytest.raises(UnknownToolError):
        await supervisor.call_tool("mock", "no_such_tool", {})


async def test_kill_then_ensure_healthy_restarts(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    sup = _make_supervisor(pid_file)
    await sup.start_all()
    try:
        first_pid = int(pid_file.read_text())
        os.kill(first_pid, signal.SIGKILL)
        await sup.ensure_healthy()
        assert sup.handles["mock"].state is ServerState.READY
        result = await sup.call_tool("mock", "echo", {"text": "again"})
        assert result.structuredContent == {"result": "again"}
        second_pid = int(pid_file.read_text())
        assert second_pid != first_pid
    finally:
        await sup.stop_all()


async def test_concurrent_calls_after_crash_cause_exactly_one_restart(tmp_path: Path) -> None:
    """H1 review: two calls racing into a dead server must serialize their
    revives — one restart, both calls served, no orphaned child."""
    pid_file = tmp_path / "pid"
    starts_file = tmp_path / "starts"
    wrapper = tmp_path / "launch"
    wrapper.write_text(f'#!/bin/sh\necho x >> "{starts_file}"\nexec "{LAUNCH}"\n')
    wrapper.chmod(0o755)
    launch = ServerLaunch(name="mock", command=wrapper, env={"MCP_MOCK_PID_FILE": str(pid_file)})
    sup = Supervisor((launch,), ping_timeout=2.0)
    await sup.start_all()
    try:
        first_pid = int(pid_file.read_text())
        os.kill(first_pid, signal.SIGKILL)
        await asyncio.sleep(0.1)  # let the transport observe the EOF
        results = await asyncio.gather(
            asyncio.wait_for(sup.call_tool("mock", "echo", {"text": "a"}), 20),
            asyncio.wait_for(sup.call_tool("mock", "echo", {"text": "b"}), 20),
        )
        assert [r.structuredContent for r in results] == [{"result": "a"}, {"result": "b"}]
        # initial start + exactly ONE revive — the loser reused the winner's session
        assert starts_file.read_text().count("x") == 2
        second_pid = int(pid_file.read_text())
        assert second_pid != first_pid
    finally:
        await sup.stop_all()
    for pid in (first_pid, second_pid):
        await _wait_for_reap(pid)  # no orphans: both children are gone


async def test_stop_all_reaps_the_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    sup = _make_supervisor(pid_file)
    await sup.start_all()
    pid = int(pid_file.read_text())
    os.kill(pid, 0)  # alive while supervised
    await sup.stop_all()
    await _wait_for_reap(pid)
    assert sup.handles["mock"].state is ServerState.NOT_LAUNCHED
    assert sup.inventory() == []


async def test_launch_failure_counts_toward_failed_state(tmp_path: Path) -> None:
    broken = tmp_path / "launch"
    broken.write_text("#!/bin/sh\nexit 7\n")
    broken.chmod(0o755)
    sup = Supervisor((ServerLaunch(name="broken", command=broken),), ping_timeout=1.0)
    handle = sup.handles["broken"]
    assert not await handle.start()
    assert not await handle.restart()
    assert not await handle.restart()
    assert handle.state is ServerState.FAILED
    assert sup.inventory() == []
    # BRG-03: FAILED maps to wire "error" with a short hygienic detail
    entry = sup.status_snapshot()[0]
    assert entry["state"] == "error"
    assert entry["detail"] is not None
    assert len(entry["detail"]) <= 512
    assert str(tmp_path) not in entry["detail"]  # no local paths on the wire


def test_status_snapshot_shape(supervisor: Supervisor) -> None:
    snapshot = supervisor.status_snapshot()
    assert len(snapshot) == 1
    entry = snapshot[0]
    assert set(entry) == {"name", "state", "detail", "updated_at"}
    assert entry["name"] == "mock"
    assert entry["state"] == "ready"
    assert entry["detail"] is None
    parsed = datetime.fromisoformat(entry["updated_at"])
    assert parsed.tzinfo is not None  # ISO-8601, UTC-aware


async def test_transitions_poke_status_event() -> None:
    sup = _make_supervisor()
    assert not sup.status_changed.is_set()
    await sup.start_all()
    try:
        assert sup.status_changed.is_set()  # launching → ready transitions
        sup.status_changed.clear()
    finally:
        await sup.stop_all()
    assert sup.status_changed.is_set()  # stop is a transition too
    assert sup.status_snapshot()[0]["state"] == "not_launched"


async def test_busy_while_call_in_flight(supervisor: Supervisor) -> None:
    supervisor.status_changed.clear()
    call = asyncio.create_task(supervisor.call_tool("mock", "sleepy", {}))
    await asyncio.sleep(0.3)
    try:
        assert supervisor.status_snapshot()[0]["state"] == "busy"
        assert supervisor.status_changed.is_set()  # the ready→busy edge poked it
    finally:
        call.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await call
    assert supervisor.status_snapshot()[0]["state"] == "ready"  # busy cleared
