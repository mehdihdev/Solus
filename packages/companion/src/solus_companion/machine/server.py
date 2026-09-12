"""`MachineServer`: the native (non-MCP) built-in the Supervisor exposes as
server "machine". Same inventory shape and `CallToolResult` as a vendored fork,
so the cloud gate (integrations/mcp/machine/allowlist.yaml) and
`dispatch.map_result` treat it identically. No workspace ⇒ advertises nothing
and every call fails closed.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, ValidationError

from solus_companion.machine import actions, code_reader
from solus_companion.machine.actions import MachineActionError

logger = logging.getLogger("solus.companion.machine")

NO_WORKSPACE = "no project workspace linked"
_SUMMARY_CAP = 2000


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadFileArgs(_Args):
    path: str


class WriteFileArgs(_Args):
    path: str
    content: str
    create_dirs: bool = False


def _object_schema(**props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": True}


_STR: dict[str, Any] = {"type": "string"}
Handler = Callable[["MachineServer", Any], Awaitable[dict[str, Any]]]


class _ToolSpec:
    def __init__(self, model: type[_Args], description: str, output: dict[str, Any]) -> None:
        self.model = model
        self.description = description
        self.output = output


_TOOLS: dict[str, _ToolSpec] = {
    "read_code_file": _ToolSpec(
        ReadFileArgs,
        "Read saved UTF-8 source text (<=128 KiB; workspace only, "
        "no sensitive paths or symlinks).",
        _object_schema(path=_STR, content=_STR, encoding=_STR, size_bytes={"type": "integer"}),
    ),
    "read_file": _ToolSpec(
        ReadFileArgs,
        "Read a file inside the workspace (<= 1 MiB; text, or base64 for binary).",
        _object_schema(path=_STR, content=_STR, encoding=_STR, size_bytes={"type": "integer"}),
    ),
    "write_file": _ToolSpec(
        WriteFileArgs,
        "Atomically write a text file inside the workspace (<= 200 KB).",
        _object_schema(path=_STR, bytes_written={"type": "integer"}),
    ),
}
TOOL_NAMES = frozenset(_TOOLS)


def _error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)


def _ok_result(value: dict[str, Any]) -> CallToolResult:
    summary = json.dumps(value, default=str)[:_SUMMARY_CAP]
    return CallToolResult(
        content=[TextContent(type="text", text=summary)], structuredContent=value, isError=False
    )


class MachineServer:
    name = "machine"
    tool_names = TOOL_NAMES

    def __init__(self, workspace: Path | None) -> None:
        self.workspace = workspace
        self._since = datetime.now(UTC).isoformat()

    def inventory(self) -> dict[str, Any] | None:
        if self.workspace is None:
            return None
        tools = [
            {
                "name": name,
                "description": tool.description,
                "input_schema": tool.model.model_json_schema(),
                "output_schema": tool.output,
            }
            for name, tool in _TOOLS.items()
        ]
        return {"server": self.name, "tools": tools}

    def status_entry(self) -> dict[str, Any]:
        linked = self.workspace is not None
        return {
            "name": self.name,
            "state": "ready" if linked else "not_launched",
            "detail": None if linked else NO_WORKSPACE,
            "updated_at": self._since,
        }

    async def call_tool(self, tool: str, args: dict[str, Any]) -> CallToolResult:
        spec = _TOOLS.get(tool)
        if spec is None:
            return _error_result(f"unknown tool machine.{tool}")
        if self.workspace is None:
            return _error_result(NO_WORKSPACE)
        try:
            parsed = spec.model.model_validate(args)
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return _error_result(f"invalid arguments: {detail}"[:_SUMMARY_CAP])
        try:
            return _ok_result(await _HANDLERS[tool](self, parsed))
        except MachineActionError as exc:
            return _error_result(str(exc))
        except Exception as exc:
            logger.exception("machine.%s failed", tool)
            return _error_result(f"{tool} failed: {type(exc).__name__}")

    # --- handlers ------------------------------------------------------------------

    def _root(self) -> Path:
        assert self.workspace is not None  # call_tool fails closed before any handler
        return self.workspace

    async def _read_code_file(self, a: ReadFileArgs) -> dict[str, Any]:
        return dict(code_reader.read_code_file(self._root(), a.path))

    async def _read_file(self, a: ReadFileArgs) -> dict[str, Any]:
        return dict(actions.read_file(self._root(), a.path))

    async def _write_file(self, a: WriteFileArgs) -> dict[str, Any]:
        return dict(actions.write_file(self._root(), a.path, a.content, create_dirs=a.create_dirs))


_HANDLERS: dict[str, Handler] = {
    "read_code_file": MachineServer._read_code_file,
    "read_file": MachineServer._read_file,
    "write_file": MachineServer._write_file,
}
