#!/usr/bin/env python3
"""Entry point for the Solus-authored `local` MCP server (SOLUSDEV-249).

`bin/launch` execs THIS file. It builds a FastMCP (the MCP SDK's built-in
`mcp.server.fastmcp`, from the fork-private venv) and registers exactly the
roster. Logging goes to stderr only — stdout is the MCP protocol channel.
Every tool returns a plain dict (structuredContent) and NEVER raises: any
internal failure collapses to the documented empty/refusal shape.

Importing this module has no side effects beyond the sys.path bootstrap;
the server starts only under `main()`.
"""

import hashlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_FORK_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_sys_path() -> None:
    """Make `solus` importable when exec'd as a plain script by the launcher."""
    sys.dont_write_bytecode = True
    entry = str(_FORK_DIR)
    if entry not in sys.path:
        sys.path.insert(0, entry)


_bootstrap_sys_path()

# Package-flexible imports: tests import this module as `local_solus.server`
# (relative imports); bin/launch execs it as a plain script, where only the
# absolute `solus.*` names put on sys.path above can resolve.
try:
    from .detect import tools_installed
    from .launch import open_in_tool
    from .roster import TOOL_ROSTER
    from .scan import SCHEMA_VERSION, folder_digest, scan_folder
    from .workspace import workspace_root
except ImportError:  # pragma: no cover - script mode under bin/launch
    from solus.detect import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        tools_installed,
    )
    from solus.launch import open_in_tool  # type: ignore[import-not-found, no-redef, unused-ignore]
    from solus.roster import TOOL_ROSTER  # type: ignore[import-not-found, no-redef, unused-ignore]
    from solus.scan import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        SCHEMA_VERSION,
        folder_digest,
        scan_folder,
    )
    from solus.workspace import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        workspace_root,
    )

logger = logging.getLogger("solus.local.server")

SERVER_NAME = "Solus Local"
#: The `tool` a refusal echoes back is caller input: bound it.
MAX_TOOL_NAME_ECHO = 64

_NO_TOOLS: dict[str, bool] = {"kicad": False, "altium": False, "vscode": False}


def _empty_digest() -> str:
    return hashlib.blake2b(digest_size=16).hexdigest()


def _empty_scan() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "root_name": "",
        "git": None,
        "files": [],
        "digest": _empty_digest(),
        "truncated": False,
        "tools_installed": dict(_NO_TOOLS),
        "dependencies": [],
        "truncated_dependencies": False,
    }


def _guarded(
    name: str, fallback: Callable[[], dict[str, Any]], body: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """Run `body`; on ANY exception log to stderr and answer `fallback()`."""
    try:
        return body()
    except Exception as exc:  # noqa: BLE001 - the never-raises rule
        logger.warning("%s failed: %s: %s", name, type(exc).__name__, exc)
        return fallback()


def tool_scan_folder() -> dict[str, Any]:
    """Scan the linked folder: git identity, tool-relevant files (path parts,
    size, blake2b-128 hash, tool), digest, and the Python dependency
    declarations (requirements*.txt, pyproject.toml, environment.yml)."""

    def body() -> dict[str, Any]:
        root = workspace_root()
        try:
            tools = {name: bool(flag) for name, flag in tools_installed().items()}
        except Exception:  # noqa: BLE001 - probing must not sink the scan
            tools = dict(_NO_TOOLS)
        return scan_folder(root, tools=tools)

    return _guarded("scan_folder", _empty_scan, body)


def tool_folder_digest() -> dict[str, Any]:
    """The content digest over the linked folder's tool-relevant files."""
    return _guarded(
        "folder_digest",
        lambda: {"digest": _empty_digest(), "truncated": False},
        lambda: folder_digest(workspace_root()),
    )


def _all_strings(*values: object) -> bool:
    """FastMCP validates argument types, but the never-raises rule is kept
    independent of that: a non-string is refused, not raised on."""
    return all(isinstance(value, str) for value in values)


def tool_open_in_tool(path: str, tool: str) -> dict[str, Any]:
    """Launch `tool` on `path` (relative to the linked folder)."""
    echoed = tool[:MAX_TOOL_NAME_ECHO] if isinstance(tool, str) else ""

    def fallback() -> dict[str, Any]:
        return {"launched": False, "tool": echoed, "reason": "launch failed"}

    def body() -> dict[str, Any]:
        if not _all_strings(path, tool):
            return {"launched": False, "tool": echoed, "reason": "path and tool must be strings"}
        result = open_in_tool(workspace_root(), path, tool)
        return {**result, "tool": echoed}

    return _guarded("open_in_tool", fallback, body)


def build_server() -> Any:
    """A FastMCP carrying exactly the roster."""
    # Imported lazily: the MCP SDK lives in the fork-private venv.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)
    server.tool(name="scan_folder", description=tool_scan_folder.__doc__)(tool_scan_folder)
    server.tool(name="folder_digest", description=tool_folder_digest.__doc__)(tool_folder_digest)
    server.tool(name="open_in_tool", description=tool_open_in_tool.__doc__)(tool_open_in_tool)
    registered = {tool.name for tool in server._tool_manager.list_tools()}
    if registered != TOOL_ROSTER:
        raise RuntimeError(f"registered {sorted(registered)} != roster {sorted(TOOL_ROSTER)}")
    return server


def _configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        force=True,
        format="%(asctime)s - %(levelname)s - [PID:%(process)d] - %(message)s",
    )


def main() -> None:
    _configure_logging()
    logger.info("Starting Solus local MCP server")
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
