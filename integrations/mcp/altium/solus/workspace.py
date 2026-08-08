"""Workspace resolution for the Solus altium overlay.

The companion passes the project workspace via `SOLUS_MCP_WORKSPACE` (the one
documented cwd knob, set by `bin/launch` / `bin/launch.cmd`). Everything this
overlay derives on disk — the file-drop IPC directory and the DelphiScript
pointer file (`solus/pointer.py`) — must resolve INSIDE that workspace;
escape attempts are refused, never silently corrected (CLAUDE.md §7
path-traversal guards).

`workspace_root()` FAILS CLOSED when `SOLUS_MCP_WORKSPACE` is unset or
empty — it never falls back to the process cwd (which could be anything the
child happened to start in, e.g. the fork directory itself). Every confined
operation built on top (the pointer/IPC paths in `solus/pointer.py`, the
path-argument confinement in `solus/confinement.py`) refuses cleanly when
this raises, rather than resolving against an unconfined default. Tested by
tests/test_overlay_env_allowlist.py.
"""

import os
from pathlib import Path


class WorkspaceNotConfiguredError(RuntimeError):
    """Raised by `workspace_root()` when `SOLUS_MCP_WORKSPACE` is unset or
    empty. Every caller must treat this as a refusal to confine, never
    substitute a default of its own."""


def workspace_root() -> Path:
    """The resolved workspace root from `SOLUS_MCP_WORKSPACE`.

    Raises `WorkspaceNotConfiguredError` when the variable is absent or
    empty — fail closed rather than defaulting to the cwd."""
    raw = os.environ.get("SOLUS_MCP_WORKSPACE", "")
    if not raw:
        raise WorkspaceNotConfiguredError(
            "SOLUS_MCP_WORKSPACE is not set; refusing rather than confining to the process cwd"
        )
    return Path(raw).resolve()
