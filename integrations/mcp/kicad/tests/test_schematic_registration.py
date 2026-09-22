"""Owned drawing tools are exposed with safe dry runs and real MCP refusals."""

import inspect
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from test_overlay_support import FakeMCP  # isort: skip
from solus.registration import register_allowlisted_tools

READS = {"get_symbol_definition", "get_schematic_geometry", "check_erc"}
WRITES = {"create_schematic", "add_symbol", "add_wire", "add_net_label", "mark_no_connect"}


@pytest.mark.parametrize("extra", [{"unexpected": True}, {"dry_run": "true"}])
async def test_real_mcp_rejects_extra_fields_and_boolean_coercion(tmp_path, monkeypatch, extra):
    from mcp.server.fastmcp import FastMCP

    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    server = FastMCP("KiCad test")
    register_allowlisted_tools(server)
    with pytest.raises(ToolError):
        await server.call_tool(
            "create_schematic",
            {
                "schematic_path": "robot.kicad_sch",
                "title": "Robot",
                "expected_absent": True,
                "dry_run": True,
                **extra,
            },
        )
    assert list(tmp_path.iterdir()) == []


def test_all_drawing_tools_have_explicit_schemas():
    server = FakeMCP()
    register_allowlisted_tools(server)
    assert READS | WRITES <= server.tools.keys()
    for name in READS | WRITES:
        parameters = inspect.signature(server.tools[name]).parameters
        assert "kwargs" not in parameters
        assert "ctx" not in parameters
        if name in WRITES:
            assert parameters["dry_run"].default is False


def test_registered_create_previews_without_touching_the_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    server = FakeMCP()
    register_allowlisted_tools(server)
    result = server.tools["create_schematic"](
        schematic_path="robot.kicad_sch",
        title="Robot",
        expected_absent=True,
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["preview"]
    assert list(tmp_path.iterdir()) == []


def test_drawing_refusal_is_an_error_not_success(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    server = FakeMCP()
    register_allowlisted_tools(server)
    with pytest.raises(ValueError, match="already_exists"):
        server.tools["create_schematic"](
            schematic_path="robot.kicad_sch",
            title="Robot",
            expected_absent=False,
            dry_run=True,
        )


def test_outside_workspace_is_an_error_before_drawing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    server = FakeMCP()
    register_allowlisted_tools(server)
    with pytest.raises(ValueError, match="path_escapes_workspace"):
        server.tools["create_schematic"](
            schematic_path="../robot.kicad_sch",
            title="Robot",
            expected_absent=True,
            dry_run=True,
        )
