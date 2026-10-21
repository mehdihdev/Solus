"""SOLUSDEV-317 — the `code` server's command tools over the MCP wire
(docs/api/code-command-execution.md §2): strict schemas, plan == execution,
denied programs never run, processes and profiles end to end, the never-raises
rule, and process cleanup wired into `main()`. HOME is always a temp dir."""

import asyncio
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

server = overlay_module("server")
execute = overlay_module("execute")
roster = overlay_module("roster")


def _recording(reached: list[object]) -> Any:
    def record(*args: object, **_kwargs: object) -> dict[str, Any]:
        reached.append(args)
        return {}

    return record


NEW_TOOLS = (
    "exec",
    "process_start",
    "process_stop",
    "process_status",
    "profile_capture",
    "profile_list",
    "profile_delete",
)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "ws"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    monkeypatch.setattr(server, "_REGISTRY", None)
    tool = root / "tool.sh"
    tool.write_text('#!/bin/sh\necho "args:$*"\nexit 2\n')
    tool.chmod(0o755)
    yield root.resolve()
    if server._REGISTRY is not None:
        server._REGISTRY.stop_all()


async def test_new_tools_are_registered_with_strict_schemas() -> None:
    tools = {tool.name: tool for tool in await server.build_server().list_tools()}
    assert set(NEW_TOOLS) <= set(tools)
    assert set(tools["exec"].inputSchema["required"]) == {"argv"}
    assert set(tools["process_start"].inputSchema["required"]) == {"argv"}
    assert set(tools["process_stop"].inputSchema["required"]) == {"process_id"}
    assert "required" not in tools["process_status"].inputSchema
    assert set(tools["profile_capture"].inputSchema["required"]) == {"name", "setup_file"}
    assert set(tools["profile_delete"].inputSchema["required"]) == {"name"}
    assert roster.READ_TOOLS >= {"process_status", "profile_list"}
    assert roster.GATED_TOOLS >= {
        "exec",
        "process_start",
        "process_stop",
        "profile_capture",
        "profile_delete",
    }


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("exec", {"argv": ["ls"], "shell": True}),
        ("exec", {"argv": "ls"}),
        ("exec", {"argv": ["ls"], "timeout_seconds": "5"}),
        ("process_status", {"cursor": "1"}),
        ("profile_delete", {"name": "ros", "force": True}),
    ],
)
async def test_extra_fields_and_coercion_are_rejected(
    ws: Path, monkeypatch: pytest.MonkeyPatch, tool: str, arguments: dict[str, Any]
) -> None:
    reached: list[object] = []
    monkeypatch.setattr(server, "execute_plan", _recording(reached))
    with pytest.raises(ToolError):
        await server.build_server().call_tool(tool, arguments)
    assert reached == []


async def test_exec_executes_exactly_what_plan_answers(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans: list[Any] = []

    def record(root: Path, plan: Any, **_kwargs: object) -> dict[str, Any]:
        plans.append(plan)
        return {**execute.refusal("unused"), "ok": True, "argv": list(plan.argv)}

    monkeypatch.setattr(server, "execute_plan", record)
    built = server.build_server()
    args = {"argv": ["./tool.sh", "a"], "timeout_seconds": 9}
    _content, planned = await built.call_tool("plan", {"action": "exec", "args": args})
    _content, result = await built.call_tool("exec", args)
    assert planned["ok"] is True and result["argv"] == planned["argv"]
    assert planned["argv"] == [str(ws / "tool.sh"), "a"]
    assert plans[0].timeout_seconds == 9 and plans[0].sandbox is not None


async def test_denied_exec_never_executes(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached: list[object] = []
    monkeypatch.setattr(server, "execute_plan", _recording(reached))
    _content, result = await server.build_server().call_tool(
        "exec", {"argv": ["bash", "-c", "rm -rf ~"]}
    )
    assert result["ok"] is False and "no shell" in result["reason"]
    assert result["sandbox"] is None and result["git_metadata_changed"] is False
    assert reached == []


@pytest.mark.real_sandbox
async def test_exec_runs_for_real_inside_the_sandbox(ws: Path) -> None:
    _content, result = await server.build_server().call_tool(
        "exec", {"argv": ["./tool.sh", "x"], "timeout_seconds": 30}
    )
    assert result["exit_code"] == 2 and result["stdout_tail"] == "args:x\n"
    assert result["argv"][0] == str(ws / "tool.sh") and result["sandbox"]
    assert result["git_metadata_changed"] is False


@pytest.mark.real_sandbox
async def test_process_lifecycle_over_the_wire(ws: Path) -> None:
    script = ws / "serve.sh"
    script.write_text("#!/bin/sh\necho ready\nexec /bin/sleep 30\n")
    script.chmod(0o755)
    built = server.build_server()
    _content, started = await built.call_tool(
        "process_start", {"argv": ["./serve.sh"], "name": "srv", "max_runtime_seconds": 60}
    )
    assert started["ok"] is True, started
    process_id = started["process_id"]
    output: dict[str, Any] = {}
    for _ in range(100):
        _content, status = await built.call_tool("process_status", {"process_id": process_id})
        output = status["output"]
        if output["chunks"]:
            break
        await asyncio.sleep(0.05)
    assert output["chunks"][0]["text"] == "ready\n"
    assert status["processes"][0]["state"] == "running"
    assert status["processes"][0]["name"] == "srv"
    assert status["processes"][0]["git_metadata_changed"] is False
    _content, stopped = await built.call_tool("process_stop", {"process_id": process_id})
    assert stopped["ok"] is True and stopped["state"] == "stopped"
    assert stopped["git_metadata_changed"] is False


async def test_process_start_refusals(ws: Path) -> None:
    _content, result = await server.build_server().call_tool(
        "process_start", {"argv": ["sudo", "x"]}
    )
    assert result["ok"] is False and result["process_id"] is None and result["reason"]
    _content, status = await server.build_server().call_tool(
        "process_status", {"process_id": "nope", "cursor": 0}
    )
    assert status == {"processes": [], "output": None}
    _content, stop = await server.build_server().call_tool("process_stop", {"process_id": "nope"})
    assert stop["ok"] is False and stop["reason"] == "unknown process"
    assert stop["git_metadata_changed"] is False


@pytest.mark.real_sandbox
async def test_profile_capture_list_delete_over_the_wire(ws: Path) -> None:
    (ws / "setup.bash").write_text("export ROS_DISTRO=jazzy\nexport MY_TOKEN=secret\n")
    built = server.build_server()
    _content, captured = await built.call_tool(
        "profile_capture", {"name": "ros", "setup_file": "setup.bash"}
    )
    assert captured["ok"] is True, captured
    assert "ROS_DISTRO" in captured["variables"] and "MY_TOKEN" in captured["dropped"]
    assert "secret" not in str(captured) and "jazzy" not in str(captured)
    _content, listed = await built.call_tool("profile_list", {})
    assert [p["name"] for p in listed["profiles"]] == ["ros"]
    _content, planned = await built.call_tool(
        "plan", {"action": "exec", "args": {"argv": ["./tool.sh"], "profile": "ros"}}
    )
    assert planned["profile"]["name"] == "ros" and len(planned["profile"]["digest"]) == 64
    _content, deleted = await built.call_tool("profile_delete", {"name": "ros"})
    assert deleted["ok"] is True
    _content, listed = await built.call_tool("profile_list", {})
    assert listed == {"profiles": []}


async def test_profile_capture_refusal_shape(ws: Path) -> None:
    _content, result = await server.build_server().call_tool(
        "profile_capture", {"name": "ros", "setup_file": "/etc/profile"}
    )
    assert result == {
        "ok": False,
        "name": "ros",
        "variables": [],
        "dropped": [],
        "path_entries": 0,
        "reason": result["reason"],
    }
    assert result["reason"]


def test_new_tools_never_raise(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("on fire")

    for name in ("workspace_root", "plan_action", "execute_plan", "_registry"):
        monkeypatch.setattr(server, name, boom)
    monkeypatch.setattr(server.profiles, "list_profiles", boom)
    monkeypatch.setattr(server.profiles, "delete", boom)
    assert server.tool_exec(["ls"])["ok"] is False
    assert server.tool_process_start(["ls"])["ok"] is False
    assert server.tool_process_stop("x")["ok"] is False
    assert server.tool_process_stop("x")["git_metadata_changed"] is False
    assert server.tool_process_status() == {"processes": [], "output": None}
    assert server.tool_profile_capture("ros", "x.bash")["ok"] is False
    assert server.tool_profile_list() == {"profiles": []}
    assert server.tool_profile_delete("ros")["ok"] is False


def test_negative_cursor_is_refused_without_raising(ws: Path) -> None:
    result = server.tool_process_status(process_id="x", cursor=-1)
    assert result["output"] is None and result["reason"]


def test_main_reaps_orphans_first_and_stops_processes_on_exit(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class FakeRegistry:
        def reap_orphans(self) -> None:
            events.append("reap")

        def stop_all(self, *, grace_seconds: float = 5.0) -> None:
            events.append(f"stop_all:{grace_seconds}")

    class FakeServer:
        def run(self, transport: str) -> None:
            events.append(f"run:{transport}")
            raise KeyboardInterrupt

    monkeypatch.setattr(server, "_REGISTRY", FakeRegistry())
    monkeypatch.setattr(server, "build_server", lambda: FakeServer())
    monkeypatch.setattr(server, "_install_signal_handlers", lambda: events.append("signals"))
    monkeypatch.setattr(server, "_ignore_shutdown_signals", lambda: events.append("ignore"))
    with pytest.raises(KeyboardInterrupt):
        server.main()
    grace = server.SHUTDOWN_GRACE_SECONDS
    assert events == ["signals", "reap", "run:stdio", "ignore", f"stop_all:{grace}"]
    assert grace <= 1.0, "SIGKILL lands within 1.5 s of shutdown (§9.13)"


def test_sigterm_handler_ignores_signals_stops_processes_then_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(server, "_ignore_shutdown_signals", lambda: events.append("ignore"))
    monkeypatch.setattr(server, "_stop_processes", lambda: events.append("stop"))
    monkeypatch.setattr(server, "_hard_exit", lambda code: events.append(f"exit:{code}"))
    server._exit_on_signal(15, None)
    assert events == ["ignore", "stop", "exit:143"]


@pytest.mark.real_sandbox
def test_real_server_process_exits_stop_their_children(tmp_path: Path) -> None:
    """stdin EOF ends the server; its started processes die with it."""
    import json
    import os
    import subprocess

    from code_paths import FORK_DIR

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "s.sh").write_text("#!/bin/sh\nexec /bin/sleep 60\n")
    (workspace / "s.sh").chmod(0o755)
    env = {"SOLUS_MCP_WORKSPACE": str(workspace), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, str(FORK_DIR / "solus" / "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "process_start", "arguments": {"argv": ["./s.sh"]}},
        },
    ]
    for message in messages:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        proc.stdin.flush()
    pid = None
    for _ in range(2):
        reply = json.loads(proc.stdout.readline())
        if reply.get("id") == 2:
            pid = reply["result"]["structuredContent"]["pid"]
    assert isinstance(pid, int)
    proc.stdin.close()
    proc.wait(timeout=20)
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the server left its process running after stdin EOF")


def test_server_uses_only_public_refusal_helpers() -> None:
    """Phase 4 LOW: no reach into another module's private helpers."""
    assert server.__file__ is not None
    source = Path(server.__file__).read_text()
    assert "._start_refusal" not in source and "._capture_refusal" not in source
    assert server.Registry.start_refusal("x")["reason"] == "x"
    assert server.profiles.capture_refusal("ros", "x")["reason"] == "x"


@pytest.mark.real_sandbox
def test_real_server_sigterm_kills_a_term_ignoring_process_within_the_sdk_window(
    tmp_path: Path,
) -> None:
    """§9.13: SIGTERM to the server during stop_all is ignored, and a started process
    that ignores SIGTERM is SIGKILLed well inside the SDK's 2 s termination window."""
    import json
    import os
    import signal
    import subprocess

    from code_paths import FORK_DIR

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "home").mkdir()
    (workspace / "s.sh").write_text("#!/bin/sh\ntrap '' TERM\nwhile :; do /bin/sleep 0.1; done\n")
    (workspace / "s.sh").chmod(0o755)
    env = {
        "SOLUS_MCP_WORKSPACE": str(workspace),
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
    }
    proc = subprocess.Popen(
        [sys.executable, str(FORK_DIR / "solus" / "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "process_start", "arguments": {"argv": ["./s.sh"]}},
        },
    ]
    for message in messages:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        proc.stdin.flush()
    pid = None
    for _ in range(2):
        reply = json.loads(proc.stdout.readline())
        if reply.get("id") == 2:
            pid = reply["result"]["structuredContent"]["pid"]
    assert isinstance(pid, int)
    time.sleep(0.3)  # the script has installed its TERM trap
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.2)
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)  # a second SIGTERM must not cut cleanup short
    dead_at = None
    try:
        while time.monotonic() - started < 10:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                dead_at = time.monotonic() - started
                break
            time.sleep(0.02)
        assert proc.wait(timeout=10) == 128 + signal.SIGTERM
    finally:
        if dead_at is None:
            os.killpg(pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
    assert dead_at is not None, "the TERM-ignoring process survived the server"
    assert dead_at < 2.0, f"SIGKILL took {dead_at:.2f} s"
