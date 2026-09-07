"""SOLUSDEV-249 — the FastMCP server registers exactly the roster, every tool
returns a dict as structuredContent, and NOTHING raises: with every internal
step exploding the tools still answer the documented failure shapes."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from .local_paths import overlay_module  # isort: skip

server = overlay_module("server")
roster = overlay_module("roster")

EMPTY_DIGEST = hashlib.blake2b(digest_size=16).hexdigest()


def _registered(built: Any) -> set[str]:
    return {tool.name for tool in built._tool_manager.list_tools()}


def test_build_server_registers_exactly_the_roster() -> None:
    built = server.build_server()
    assert _registered(built) == roster.TOOL_ROSTER
    assert built.name == "Solus Local"


async def test_tools_advertise_object_output_schemas() -> None:
    built = server.build_server()
    tools = {tool.name: tool for tool in await built.list_tools()}
    for name in roster.TOOL_ROSTER:
        assert tools[name].outputSchema is not None, name
        assert tools[name].outputSchema["type"] == "object"
    assert set(tools["open_in_tool"].inputSchema["required"]) == {"path", "tool"}
    assert tools["scan_folder"].inputSchema["properties"] == {}


async def test_scan_folder_over_the_wire(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    (tmp_path / "a.py").write_text("x")
    built = server.build_server()
    _content, structured = await built.call_tool("scan_folder", {})
    assert isinstance(structured, dict)
    assert structured["root_name"] == tmp_path.name
    assert [entry["parts"] for entry in structured["files"]] == [["a.py"]]
    _content, digest = await built.call_tool("folder_digest", {})
    assert digest == {"digest": structured["digest"], "truncated": False}


async def test_open_in_tool_over_the_wire_refuses_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    built = server.build_server()
    _content, structured = await built.call_tool(
        "open_in_tool", {"path": "../etc/passwd", "tool": "kicad"}
    )
    assert structured == {
        "launched": False,
        "tool": "kicad",
        "reason": "path is outside the linked folder",
    }


def test_unconfigured_workspace_yields_the_empty_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    scan = server.tool_scan_folder()
    assert scan["files"] == [] and scan["truncated"] is False and scan["git"] is None
    assert scan["root_name"] == ""
    assert scan["digest"] == EMPTY_DIGEST
    assert set(scan["tools_installed"]) == {"kicad", "altium", "vscode"}
    assert server.tool_folder_digest() == {"digest": EMPTY_DIGEST, "truncated": False}
    opened = server.tool_open_in_tool("a.py", "kicad")
    assert opened["launched"] is False and opened["tool"] == "kicad" and opened["reason"]


def test_never_raises_when_every_internal_step_explodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("everything is on fire")

    for name in (
        "workspace_root",
        "scan_folder",
        "folder_digest",
        "open_in_tool",
        "tools_installed",
    ):
        monkeypatch.setattr(server, name, boom)

    scan = server.tool_scan_folder()
    assert scan["schema_version"] == 1
    assert scan["files"] == [] and scan["git"] is None and scan["truncated"] is False
    assert scan["digest"] == EMPTY_DIGEST
    assert scan["tools_installed"] == {"kicad": False, "altium": False, "vscode": False}
    assert "reason" not in scan
    assert server.tool_folder_digest() == {"digest": EMPTY_DIGEST, "truncated": False}
    opened = server.tool_open_in_tool("a.py", "kicad")
    assert opened["launched"] is False and opened["tool"] == "kicad"
    assert isinstance(opened["reason"], str) and opened["reason"]


def test_open_in_tool_rejects_non_string_arguments_without_raising() -> None:
    result = server.tool_open_in_tool(None, 42)  # type: ignore[arg-type, unused-ignore]
    assert result["launched"] is False and isinstance(result["reason"], str)
    assert result["tool"] == ""


def test_open_in_tool_bounds_the_echoed_tool_name() -> None:
    result = server.tool_open_in_tool("a.py", "x" * 1000)
    assert result["launched"] is False
    assert len(result["tool"]) <= server.MAX_TOOL_NAME_ECHO


def test_empty_scan_carries_the_dependency_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """docs/api/code-environment.md §3: the failure shape has the same keys as
    a real scan, so the cloud never key-errors on an unconfigured workspace."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    scan = server.tool_scan_folder()
    assert scan["dependencies"] == [] and scan["truncated_dependencies"] is False


async def test_scan_folder_dependencies_over_the_wire(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    (tmp_path / "requirements.txt").write_text("torch==2.1.0\n")
    built = server.build_server()
    _content, structured = await built.call_tool("scan_folder", {})
    assert structured["dependencies"] == [
        {
            "parts": ["requirements.txt"],
            "ecosystem": "python",
            "name": "torch",
            "specifier": "==2.1.0",
            "extras": [],
            "line": 1,
        }
    ]
    assert structured["truncated_dependencies"] is False
