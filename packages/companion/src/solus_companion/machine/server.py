"""`MachineServer`: the native (non-MCP) built-in the Supervisor exposes as
server "machine". Same inventory shape and `CallToolResult` as a vendored fork,
so the cloud gate (integrations/mcp/machine/allowlist.yaml) and
`dispatch.map_result` treat it identically. No workspace ⇒ only the
workspace-free `tool_versions` is advertised and every other call fails closed.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, ValidationError

from solus_companion.config import DEFAULT_VERSION_BINARIES
from solus_companion.machine import actions, code_reader
from solus_companion.machine.actions import MachineActionError

logger = logging.getLogger("solus.companion.machine")

NO_WORKSPACE = "no project workspace linked"
_SUMMARY_CAP = 2000
#: SOLUSDEV-320 `tool_versions`: per-binary bound and the one line kept of its output.
VERSION_PROBE_TIMEOUT: float = 2.0
VERSION_LINE_CAP = 200
#: Tools that need no workspace (nothing on disk is read or written).
_WORKSPACE_FREE = frozenset({"tool_versions"})

WhichFn = Callable[[str], str | None]
CaptureFn = Callable[[list[str], float], str | None]
#: An absolute path (POSIX or drive-letter) anywhere in a version line.
_ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/)[^\s)]+")


def absolute_path_which(name: str) -> str | None:
    """`shutil.which` over the ABSOLUTE entries of PATH only — never `.`, `""` or a relative
    dir, and never the cwd Windows would prepend (§7: binaries pinned to expected paths)."""
    dirs = [p for p in os.environ.get("PATH", "").split(os.pathsep) if os.path.isabs(p)]
    found = shutil.which(name, path=os.pathsep.join(dirs))
    if found is None or os.path.dirname(os.path.abspath(found)) not in {
        os.path.abspath(d) for d in dirs
    }:
        return None
    return found


def redact_version_line(line: str) -> str:
    """`pip 24.0 from /home/<user>/... (python 3.12)` → `pip 24.0`: a machine's attrs are
    read by every project member and SOL, so no local path (or username) rides along."""
    head = line.split(" from ", 1)[0]
    return _ABS_PATH_RE.sub("<path>", head).strip()


def capture_version(argv: list[str], timeout_seconds: float) -> str | None:
    """stdout (else stderr) of a successful argv run, bounded; None on any failure.
    Never raises, never a shell: `argv[0]` is an absolute path `which` resolved."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv over a resolved absolute binary
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr)[: VERSION_LINE_CAP * 4].decode("utf-8", errors="replace")


def _version_line(raw: str | None) -> str | None:
    """The first non-empty line, printable characters only, capped — or None."""
    for line in (raw or "").splitlines():
        kept = "".join(ch for ch in line if ch.isprintable()).strip()[:VERSION_LINE_CAP]
        if kept:
            return kept
    return None


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadFileArgs(_Args):
    path: str


class ToolVersionsArgs(_Args):
    """No arguments: the binaries are a fixed list, never caller-chosen."""


class WriteFileArgs(_Args):
    path: str
    content: str
    model_config = ConfigDict(extra="forbid", strict=True)
    create_dirs: bool = False
    dry_run: bool = False
    expected_fingerprint: str | None = None


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
        "Read saved UTF-8 source text (<=128 KiB; workspace only, no sensitive paths or symlinks).",
        _object_schema(path=_STR, content=_STR, encoding=_STR, size_bytes={"type": "integer"}),
    ),
    "read_file": _ToolSpec(
        ReadFileArgs,
        "Read a file inside the workspace (<= 1 MiB; text, or base64 for binary).",
        _object_schema(path=_STR, content=_STR, encoding=_STR, size_bytes={"type": "integer"}),
    ),
    "write_file": _ToolSpec(
        WriteFileArgs,
        (
            "Preview and atomically write bounded workspace text; "
            "complete preview fingerprint required."
        ),
        _object_schema(path=_STR, bytes_written={"type": "integer"}),
    ),
    "tool_versions": _ToolSpec(
        ToolVersionsArgs,
        "Report `--version` of a fixed list of developer tools on this machine (argv only).",
        _object_schema(tool_versions={"type": "object", "additionalProperties": _STR}),
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

    def __init__(
        self,
        workspace: Path | None,
        *,
        version_binaries: tuple[str, ...] = DEFAULT_VERSION_BINARIES,
        which: WhichFn = absolute_path_which,
        capture: CaptureFn = capture_version,
    ) -> None:
        self.workspace = workspace
        self._since = datetime.now(UTC).isoformat()
        self._version_binaries = version_binaries
        self._which = which
        self._capture = capture

    def inventory(self) -> dict[str, Any] | None:
        tools = [
            {
                "name": name,
                "description": tool.description,
                "input_schema": tool.model.model_json_schema(),
                "output_schema": tool.output,
            }
            for name, tool in _TOOLS.items()
            if self.workspace is not None or name in _WORKSPACE_FREE
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
        if self.workspace is None and tool not in _WORKSPACE_FREE:
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
        if a.dry_run:
            return dict(
                actions.plan_write_file(self._root(), a.path, a.content, create_dirs=a.create_dirs)
            )
        return dict(
            actions.write_file(
                self._root(),
                a.path,
                a.content,
                create_dirs=a.create_dirs,
                expected_fingerprint=a.expected_fingerprint,
            )
        )

    async def _tool_versions(self, _a: ToolVersionsArgs) -> dict[str, Any]:
        found: dict[str, str] = {}
        for name in self._version_binaries:
            exe = self._which(name)
            if exe is None:
                continue  # absent is omitted, never invented
            try:
                raw = await asyncio.to_thread(
                    self._capture, [exe, "--version"], VERSION_PROBE_TIMEOUT
                )
            except Exception:  # noqa: BLE001 - one broken binary never hides the others
                logger.warning("tool_versions: %s --version failed", name)
                continue
            line = redact_version_line(_version_line(raw) or "")
            if line:
                found[name] = line
        return {"tool_versions": found}


_HANDLERS: dict[str, Handler] = {
    "read_code_file": MachineServer._read_code_file,
    "read_file": MachineServer._read_file,
    "write_file": MachineServer._write_file,
    "tool_versions": MachineServer._tool_versions,
}
