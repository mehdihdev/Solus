"""Exercise the actual pinned FastMCP runtime through the sanctioned launcher.

The fork env lives in the app-data `mcp-envs/kicad/` dir (ADR-031 amendment
2026-11-19), so the test takes its interpreter from SOLUS_TEST_KICAD_PYTHON and
hands it to bin/launch exactly as the companion does, via SOLUS_MCP_PYTHON."""

import asyncio
import os
from pathlib import Path

import pytest

FORK = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("SOLUS_TEST_KICAD_PYTHON", "")


@pytest.mark.skipif(not PYTHON, reason="private runtime unavailable (set SOLUS_TEST_KICAD_PYTHON)")
async def test_packaged_runtime_strict_tools(tmp_path: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with asyncio.timeout(30):
        async with stdio_client(
            StdioServerParameters(
                command=str(FORK / "bin/launch"),
                env={"SOLUS_MCP_PYTHON": PYTHON, "SOLUS_MCP_WORKSPACE": str(tmp_path)},
            )
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                # SOLUSDEV-321 P4-T3: export_spice_netlist moved this from 15 to 16; P5's
                # export_schematic_pdf and export_board_pdf move it to 18
                assert len(listed.tools) == 18
                args = {
                    "schematic_path": "fresh.kicad_sch",
                    "title": "Fresh",
                    "expected_absent": True,
                    "dry_run": True,
                }
                for extra in ({"unknown": True}, {"dry_run": "true"}):
                    result = await session.call_tool("create_schematic", {**args, **extra})
                    assert result.isError
                result = await session.call_tool("create_schematic", args)
                assert not result.isError
                assert not list(tmp_path.iterdir())
