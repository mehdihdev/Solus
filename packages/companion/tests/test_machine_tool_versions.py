"""SOLUSDEV-320 P5-T1: `machine.tool_versions` — argv-only `--version` over a fixed list,
absent binaries omitted (never invented), bounded output, never raises, advertised even
without a workspace."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent
from solus_companion.config import DEFAULT_VERSION_BINARIES, CompanionConfig
from solus_companion.machine.server import (
    VERSION_LINE_CAP,
    VERSION_PROBE_TIMEOUT,
    MachineServer,
    absolute_path_which,
    capture_version,
    redact_version_line,
)
from solus_companion.supervisor import Supervisor
from test_companion_machine import _allowlist_names

WHICH = {"python3": "/usr/bin/python3", "git": "/usr/bin/git", "node": "/opt/node/bin/node"}
OUTPUT: dict[str, str | None] = {
    "/usr/bin/python3": "Python 3.12.3\nextra line never shown",
    "/usr/bin/git": None,  # timed out / non-zero exit: the capture answers None
    "/opt/node/bin/node": "\x00\x01\x02",  # garbage: nothing printable survives
}


def _which_fixture(name: str) -> str | None:
    return WHICH.get(name)


def _result_text(result: CallToolResult) -> str:
    return " ".join(b.text for b in result.content if isinstance(b, TextContent))


def _versions_server(
    capture: Any = None, binaries: tuple[str, ...] = DEFAULT_VERSION_BINARIES
) -> tuple[MachineServer, list[tuple[list[str], float]]]:
    calls: list[tuple[list[str], float]] = []

    def _fake_capture(argv: list[str], timeout_seconds: float) -> str | None:
        calls.append((argv, timeout_seconds))
        return OUTPUT.get(argv[0])

    server = MachineServer(
        None, version_binaries=binaries, which=_which_fixture, capture=capture or _fake_capture
    )
    return server, calls


def test_config_default_binaries_are_the_fixed_tuple() -> None:
    assert CompanionConfig.__dataclass_fields__["version_binaries"].default == (
        DEFAULT_VERSION_BINARIES
    )
    assert DEFAULT_VERSION_BINARIES == (
        "python3",
        "node",
        "git",
        "kicad-cli",
        "arduino-cli",
        "ros2",
        "docker",
        "uv",
        "pip",
        "conda",
    )


async def test_present_absent_timeout_and_garbage() -> None:
    server, calls = _versions_server()
    result = await server.call_tool("tool_versions", {})
    assert result.isError is False
    assert result.structuredContent == {"tool_versions": {"python3": "Python 3.12.3"}}
    # argv-only `[exe, "--version"]` over resolved paths, each with the 2 s bound;
    # binaries `which` cannot find are never run.
    assert calls == [
        (["/usr/bin/python3", "--version"], VERSION_PROBE_TIMEOUT),
        (["/opt/node/bin/node", "--version"], VERSION_PROBE_TIMEOUT),
        (["/usr/bin/git", "--version"], VERSION_PROBE_TIMEOUT),
    ]


async def test_output_is_first_line_capped() -> None:
    server, _ = _versions_server(
        capture=lambda argv, t: "x" * 1000 + "\nmore", binaries=("python3",)
    )
    result = await server.call_tool("tool_versions", {})
    assert result.structuredContent == {"tool_versions": {"python3": "x" * VERSION_LINE_CAP}}


async def test_capture_raising_never_escapes() -> None:
    def boom(argv: list[str], timeout_seconds: float) -> str | None:
        raise OSError("exec format error")

    server, _ = _versions_server(capture=boom)
    result = await server.call_tool("tool_versions", {})
    assert result.isError is False
    assert result.structuredContent == {"tool_versions": {}}


async def test_rejects_arguments() -> None:
    server, calls = _versions_server()
    result = await server.call_tool("tool_versions", {"binary": "rm"})
    assert result.isError is True and "invalid arguments" in _result_text(result)
    assert calls == []


def test_advertised_without_a_workspace_and_only_that() -> None:
    server, _ = _versions_server()
    inventory = server.inventory()
    assert inventory is not None
    assert [t["name"] for t in inventory["tools"]] == ["tool_versions"]
    assert inventory["tools"][0]["input_schema"]["additionalProperties"] is False
    sup = Supervisor((), builtins=(server,))
    assert [t["name"] for t in sup.inventory()[0]["tools"]] == ["tool_versions"]


async def test_workspace_tools_still_fail_closed_without_one() -> None:
    server, _ = _versions_server()
    result = await server.call_tool("read_file", {"path": "x"})
    assert result.isError is True and "no project workspace" in _result_text(result)


def test_capture_version_runs_argv_without_a_shell(tmp_path: Path) -> None:
    line = capture_version([sys.executable, "--version"], VERSION_PROBE_TIMEOUT)
    assert line is not None and line.startswith("Python ")
    assert capture_version([str(tmp_path / "missing-binary"), "--version"], 1) is None
    assert capture_version([sys.executable, "-c", "import sys; sys.exit(3)"], 1) is None
    assert capture_version([sys.executable, "-c", "import time; time.sleep(5)"], 0.2) is None


def test_tool_versions_is_in_the_allowlist() -> None:
    assert "tool_versions" in _allowlist_names()


PIP_LINE = "pip 24.0 from /home/alice/.venv/lib/python3.12/site-packages/pip (python 3.12)"


def test_redaction_cuts_the_from_clause_and_every_absolute_path() -> None:
    assert redact_version_line(PIP_LINE) == "pip 24.0"
    assert redact_version_line("node v20.11.1") == "node v20.11.1"
    assert redact_version_line("uv 0.4.0 (/opt/uv/bin)") == "uv 0.4.0 (<path>)"
    assert (
        redact_version_line("conda 24.1 C:\\Users\\bob\\miniconda3\\Scripts") == "conda 24.1 <path>"
    )
    assert redact_version_line("   ") == ""


async def test_tool_versions_never_carries_a_local_path(monkeypatch: Any) -> None:
    monkeypatch.setitem(OUTPUT, "/usr/bin/pip", PIP_LINE + "\nsecond line")
    monkeypatch.setitem(WHICH, "pip", "/usr/bin/pip")
    server, _ = _versions_server(binaries=("pip", "python3"))
    result = await server.call_tool("tool_versions", {})
    versions = (result.structuredContent or {})["tool_versions"]
    assert versions == {"pip": "pip 24.0", "python3": "Python 3.12.3"}
    assert not any("/" in v or "\\" in v for v in versions.values())


def test_binaries_resolve_only_through_absolute_path_entries(
    tmp_path: Path, monkeypatch: Any
) -> None:
    planted = tmp_path / "python3"
    planted.write_text("#!/bin/sh\necho pwned\n")
    planted.chmod(planted.stat().st_mode | stat.S_IXUSR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", "relative/bin", str(tmp_path / "nope")]))
    assert absolute_path_which("python3") is None
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tmp_path)]))
    assert absolute_path_which("python3") == str(planted)
    assert MachineServer(None)._which is absolute_path_which
