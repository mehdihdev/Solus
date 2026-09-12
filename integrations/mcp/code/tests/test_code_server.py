"""SOLUSDEV-250 — the FastMCP server registers exactly the roster, every tool
returns a dict, a gated tool executes EXACTLY what `plan` answers, refusals
never execute, and NOTHING raises even when every internal step explodes."""

from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from venv_fixture import fake_venv  # isort: skip

server = overlay_module("server")
roster = overlay_module("roster")
execute = overlay_module("execute")


def _venv(root: Path) -> None:
    fake_venv(root)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(server, "pinned_which", lambda _name: None)
    _venv(tmp_path)
    (tmp_path / "a.py").write_text("print(1)\n")
    (tmp_path / "tests").mkdir()
    return tmp_path


class ExecRecorder:
    def __init__(self) -> None:
        self.plans: list[Any] = []

    def __call__(self, root: Path, plan: Any, **_kwargs: object) -> dict[str, Any]:
        self.plans.append(plan)
        return {**execute.refusal("unused"), "ok": True, "argv": list(plan.argv), "exit_code": 0}


def test_build_server_registers_exactly_the_roster() -> None:
    built = server.build_server()
    assert {tool.name for tool in built._tool_manager.list_tools()} == roster.TOOL_ROSTER
    assert built.name == "Solus Code"


async def test_tools_advertise_object_schemas_and_required_args() -> None:
    tools = {tool.name: tool for tool in await server.build_server().list_tools()}
    for name in roster.TOOL_ROSTER:
        assert tools[name].outputSchema is not None and tools[name].outputSchema["type"] == "object"
    assert tools["probe_environment"].inputSchema["properties"]["environment"]["default"] is None
    assert "required" not in tools["probe_environment"].inputSchema
    assert set(tools["plan"].inputSchema["required"]) == {"action"}
    assert set(tools["install"].inputSchema["required"]) == {"packages"}
    assert set(tools["run"].inputSchema["required"]) == {"script"}
    assert "required" not in tools["create_environment"].inputSchema
    assert "required" not in tools["test"].inputSchema


async def test_plan_over_the_wire(ws: Path) -> None:
    built = server.build_server()
    _content, structured = await built.call_tool(
        "plan", {"action": "install", "args": {"packages": ["numpy"]}}
    )
    assert structured == {
        "argv": [".venv/bin/python", "-m", "pip", "install", "--", "numpy"],
        "cwd": ".",
        "ok": True,
        "reason": None,
    }
    _content, refused = await built.call_tool("plan", {"action": "run", "args": {"script": "../x"}})
    assert refused["ok"] is False and refused["argv"] == [] and refused["reason"]


def test_gated_tools_execute_exactly_what_plan_answers(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = ExecRecorder()
    monkeypatch.setattr(server, "execute_plan", recorder)
    monkeypatch.setattr(server, "pinned_which", lambda name: "/opt/x/uv" if name == "uv" else None)
    cases = [
        (
            server.tool_install(["numpy", "torch==2.1.0"]),
            "install",
            {"packages": ["numpy", "torch==2.1.0"]},
        ),
        (
            server.tool_run("a.py", ["--x"], timeout_seconds=9),
            "run",
            {"script": "a.py", "args": ["--x"], "timeout_seconds": 9},
        ),
        (server.tool_test(), "test", {}),
        (
            server.tool_create_environment("env2", "3.11"),
            "create_environment",
            {"path": "env2", "python": "3.11"},
        ),
    ]
    for result, action, args in cases:
        planned = server.tool_plan(action, args)
        assert result["ok"] is True and result["argv"] == planned["argv"], action
    assert [p.argv for p in recorder.plans] == [c[0]["argv"] for c in cases]
    assert recorder.plans[1].timeout_seconds == 9
    assert recorder.plans[3].argv == ["uv", "venv", "--python", "3.11", "env2"]
    assert cases[3][0]["path"] == "env2" and "path" not in cases[0][0]


def test_create_environment_carries_its_path(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "pinned_which", lambda name: "/opt/x/uv" if name == "uv" else None)
    recorder = ExecRecorder()
    monkeypatch.setattr(server, "execute_plan", recorder)
    result = server.tool_create_environment("env2")
    assert result["path"] == "env2" and result["argv"] == ["uv", "venv", "--python", "3.12", "env2"]


async def test_refusals_over_the_wire_never_execute(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = ExecRecorder()
    monkeypatch.setattr(server, "execute_plan", recorder)
    built = server.build_server()
    _content, structured = await built.call_tool("install", {"packages": ["-e", "."]})
    assert structured["ok"] is False and structured["exit_code"] is None
    assert structured["reason"] == "package may not start with '-': -e"
    _content, structured = await built.call_tool("run", {"script": "../etc/passwd"})
    assert structured["ok"] is False
    _content, structured = await built.call_tool("test", {"timeout_seconds": 9999})
    assert structured["ok"] is False
    assert recorder.plans == [], "a refused plan must never reach the executor"


async def test_run_executes_for_real_over_the_wire(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one true end-to-end path: the workspace venv `python` is a shell
    script that echoes its argv, so the exact planned argv is observable."""
    (ws / ".venv" / "bin" / "python").write_text('#!/bin/sh\necho "argv:$*"\nexit 3\n')
    _content, structured = await server.build_server().call_tool(
        "run", {"script": "a.py", "args": ["--n", "2"]}
    )
    assert structured["exit_code"] == 3 and structured["ok"] is False
    assert structured["stdout_tail"] == "argv:a.py --n 2\n"
    assert structured["argv"] == [".venv/bin/python", "a.py", "--n", "2"]
    assert structured["timed_out"] is False and structured["reason"] is None


def test_unconfigured_workspace_yields_the_refusal_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert server.tool_probe_environment() == {
        "python": None,
        "interpreters": [],
        "venv": None,
        "conda": None,
        "uv": None,
    }
    assert server.tool_plan("install", {"packages": ["numpy"]}) == {
        "argv": [],
        "cwd": ".",
        "ok": False,
        "reason": "plan failed",
    }
    for result in (
        server.tool_install(["numpy"]),
        server.tool_run("a.py"),
        server.tool_test(),
        server.tool_create_environment(),
    ):
        assert result["ok"] is False and result["exit_code"] is None and result["reason"]


def test_never_raises_when_every_internal_step_explodes(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("everything is on fire")

    for name in ("workspace_root", "plan_action", "execute_plan", "probe_environment"):
        monkeypatch.setattr(server, name, boom)
    assert server.tool_probe_environment()["interpreters"] == []
    assert server.tool_plan("run", {"script": "a.py"})["ok"] is False
    for result in (
        server.tool_install(["numpy"]),
        server.tool_run("a.py"),
        server.tool_test(),
        server.tool_create_environment(),
    ):
        assert (
            result["ok"] is False
            and result["exit_code"] is None
            and isinstance(result["reason"], str)
        )


def test_plan_rejects_non_string_actions_without_raising(ws: Path) -> None:
    assert server.tool_plan(None, {})["ok"] is False
    assert server.tool_plan("run", "not-a-dict")["ok"] is False


@pytest.mark.parametrize("arguments", [{}, {"environment": "sim"}])
async def test_probe_forwards_optional_named_environment(
    ws: Path, monkeypatch: pytest.MonkeyPatch, arguments: dict[str, str]
) -> None:
    seen: list[tuple[Path, str | None]] = []

    def observe(root: Path, *, environment: str | None = None) -> dict[str, Any]:
        seen.append((root, environment))
        return dict(server.empty_probe())

    monkeypatch.setattr(server, "probe_environment", observe)
    _, structured = await server.build_server().call_tool("probe_environment", arguments)
    assert structured == server.empty_probe()
    assert seen == [(ws, arguments.get("environment"))]
