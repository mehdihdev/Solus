"""Exercise the actual pinned FastMCP runtime through the sanctioned launcher."""

import asyncio
from pathlib import Path

import pytest

FORK = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (FORK / ".venv/bin/python3").exists(), reason="private runtime unavailable")
async def test_packaged_runtime_strict_tools(tmp_path: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with asyncio.timeout(30):
        async with stdio_client(
            StdioServerParameters(
                command=str(FORK / "bin/launch"), env={"SOLUS_MCP_WORKSPACE": str(tmp_path)}
            )
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert len(listed.tools) == 15
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
