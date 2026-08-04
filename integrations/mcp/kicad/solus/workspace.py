"""Workspace resolution and artifact confinement for the Solus kicad overlay.

The companion passes the project workspace via `SOLUS_MCP_WORKSPACE` (the one
documented cwd knob, set by `bin/launch`). Every file this overlay writes —
export artifacts — must resolve INSIDE that workspace; traversal attempts are
refused, never silently corrected (CLAUDE.md §7 path-traversal guards).

H3: `workspace_root()` FAILS CLOSED when `SOLUS_MCP_WORKSPACE` is unset —
it never falls back to the process cwd (which could be anything the child
happened to start in, e.g. the fork directory itself). Every confined
operation built on top (artifact writes, the H2 read-path confinement in
`solus/trimming.py`, the write tool's `solus/write/paths.py`) refuses cleanly
when this raises, rather than resolving against an unconfined default.
Tested by tests/test_overlay_env_allowlist.py.
"""

import os
from pathlib import Path

# Subdirectory of the workspace that holds tool-produced artifacts.
ARTIFACT_DIR_NAME = "solus-artifacts"


class WorkspaceNotConfiguredError(RuntimeError):
    """Raised by `workspace_root()` when `SOLUS_MCP_WORKSPACE` is unset or
    empty (H3). Every caller must treat this as a refusal to confine, never
    substitute a default of its own."""


def workspace_root() -> Path:
    """The resolved workspace root from `SOLUS_MCP_WORKSPACE`.

    Raises `WorkspaceNotConfiguredError` when the variable is absent or
    empty — fail closed rather than defaulting to the cwd (H3)."""
    raw = os.environ.get("SOLUS_MCP_WORKSPACE", "")
    if not raw:
        raise WorkspaceNotConfiguredError(
            "SOLUS_MCP_WORKSPACE is not set; refusing rather than confining to the process cwd"
        )
    return Path(raw).resolve()


def artifact_destination(filename: str) -> Path:
    """The confined path for one artifact file. Rejects anything that is not
    a bare, benign filename, then re-checks the RESOLVED path is inside the
    workspace (defense in depth against symlinked artifact directories)."""
    is_bare_name = bool(filename) and Path(filename).name == filename
    if not is_bare_name or "\\" in filename or filename.startswith("."):
        raise ValueError(f"unsafe artifact filename: {filename!r}")
    root = workspace_root()
    directory = root / ARTIFACT_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    destination = (directory / filename).resolve()
    if not destination.is_relative_to(root):
        raise ValueError(f"artifact destination escaped the workspace: {filename!r}")
    return destination


def to_workspace_relative(path: Path) -> str:
    """The workspace-relative POSIX form results carry as `artifact_path`."""
    return path.resolve().relative_to(workspace_root()).as_posix()
