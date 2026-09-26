"""The production Code launcher discovers strict Arduino tools without installing."""

import asyncio
from pathlib import Path

import pytest

from code_paths import FORK_DIR, LAUNCH  # isort: skip


@pytest.mark.skipif(
    not (FORK_DIR / ".venv/bin/python3").exists(), reason="private runtime unavailable"
)
async def test_packaged_arduino_transport(tmp_path: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with asyncio.timeout(30):
        async with stdio_client(
            StdioServerParameters(command=str(LAUNCH), env={"SOLUS_MCP_WORKSPACE": str(tmp_path)})
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert len(listed.tools) == 15
                for args in ({"unknown": True}, {"dry_run": "true"}):
                    result = await session.call_tool("arduino_prepare", args)
                    assert result.isError
                result = await session.call_tool("arduino_probe", {})
                assert not result.isError
                assert result.structuredContent is not None
                assert result.structuredContent["ok"] is True
                assert not list(tmp_path.iterdir())
