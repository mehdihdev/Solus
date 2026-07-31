"""Standalone mock MCP server for the companion test suite (SOLUS-BRG-01).

A vendored copy of packages/api/tests/fixtures/mcp_mock_server.py — speaks
the REAL protocol (FastMCP over stdio), launched via ../bin/launch. Only
needs the `mcp` package.

Canned tools:
- `echo`      — returns its input (structured `{"result": ...}` via FastMCP wrapping)
- `add`       — structured dict output
- `boom`      — always fails → a `CallToolResult.isError` result
- `sleepy`    — sleeps ~5s
- `plain`     — no output schema (content-block mapping)
- `pic`       — returns binary image content (never-inline rule)
- `badschema` — advertises a malformed input schema (mutated below)

If `MCP_MOCK_PID_FILE` is set, the server writes its PID there at startup so
tests can kill/reap the child by PID.
"""

import asyncio
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

server = FastMCP("mock")


@server.tool()
def echo(text: str) -> str:
    """Echo the input back."""
    return text


@server.tool()
def add(a: int, b: int) -> dict[str, int]:
    """Add two integers (structured output)."""
    return {"total": a + b}


@server.tool()
def boom() -> str:
    """Always fails."""
    raise RuntimeError("boom went the server")


@server.tool()
async def sleepy() -> str:
    """Sleep ~5 seconds, then answer."""
    await asyncio.sleep(5)
    return "done"


@server.tool()
def plain(x: str) -> Any:
    """Return unstructured text (no output schema)."""
    return x


@server.tool()
def pic() -> Image:
    """Return binary image content (never to be inlined client-side)."""
    return Image(data=b"BINARYSENTINEL", format="png")


@server.tool()
def badschema(x: str) -> str:
    """Tool whose advertised input schema is malformed."""
    return x


# Corrupt `badschema`'s advertised input schema so consumers have a malformed
# schema to handle. FastMCP generates only valid schemas, hence the mutation.
server._tool_manager._tools["badschema"].parameters = {"type": "not-a-real-type"}

if __name__ == "__main__":
    pid_file = os.environ.get("MCP_MOCK_PID_FILE")
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()))
    server.run("stdio")
