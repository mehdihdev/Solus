"""The production Code launcher discovers strict Arduino tools without installing.

The fork env lives in the app-data `mcp-envs/code/` dir (ADR-031 amendment
2026-11-19), so the test takes its interpreter from SOLUS_TEST_CODE_PYTHON and
hands it to bin/launch exactly as the companion does, via SOLUS_MCP_PYTHON."""

import asyncio
import os
from pathlib import Path

import pytest

from code_paths import LAUNCH, overlay_module  # isort: skip

#: The launcher lists the whole roster (SOLUSDEV-321 P6 fixed a stale count of 15 here).
ROSTER = overlay_module("roster").TOOL_ROSTER
PYTHON = os.environ.get("SOLUS_TEST_CODE_PYTHON", "")


@pytest.mark.skipif(not PYTHON, reason="private runtime unavailable (set SOLUS_TEST_CODE_PYTHON)")
async def test_packaged_arduino_transport(tmp_path: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with asyncio.timeout(30):
        async with stdio_client(
            StdioServerParameters(
                command=str(LAUNCH),
                env={"SOLUS_MCP_PYTHON": PYTHON, "SOLUS_MCP_WORKSPACE": str(tmp_path)},
            )
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == ROSTER
                for args in ({"unknown": True}, {"dry_run": "true"}):
                    result = await session.call_tool("arduino_prepare", args)
                    assert result.isError
                result = await session.call_tool("arduino_probe", {})
                assert not result.isError
                assert result.structuredContent is not None
                assert result.structuredContent["ok"] is True
                assert not list(tmp_path.iterdir())
