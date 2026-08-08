"""Confined file-drop IPC paths for the Solus altium overlay (SOLUSDEV-102).

Upstream's DelphiScript bridge (`upstream/src/eda_agent/config.py`) drives
Altium through a file-drop IPC workspace plus a pointer file the Pascal side
reads at startup to find that workspace. Upstream's DEFAULT pointer path is
MACHINE-GLOBAL — a fixed path under the Windows program-data root, shared
with any running Altium session — unless `EDA_AGENT_POINTER_FILE` redirects
it (see `WORKSPACE_POINTER_FILE` in the upstream config module for the
literal default path).

This module is the single Solus-side computation of the CONFINED
replacements: both the IPC directory and the pointer file live INSIDE the
Solus workspace, byte-matching the `EDA_AGENT_WORKSPACE` /
`EDA_AGENT_POINTER_FILE` pins that `bin/launch` and `bin/launch.cmd` set.
Pure functions of an explicit workspace root: ALT-5's server bootstrap
resolves the root via `solus.workspace.workspace_root()` (fail-closed) and
validates the derived paths here. A path that RESOLVES (symlinks included)
outside the workspace is refused, never corrected; the machine-global
default is never returned on any code path.
"""

from pathlib import Path

#: Subdirectory of the Solus workspace that holds the file-drop IPC exchange.
#: Must match the launcher pins exactly (tests/test_pointer_confinement.py).
IPC_DIR_NAME = ".eda-agent-ipc"

#: Pointer-file name the Pascal side expects, relocated inside the IPC dir.
POINTER_FILE_NAME = "workspace-path.txt"


class PointerConfinementError(ValueError):
    """A derived IPC path resolved outside the workspace (symlink escape).
    Callers must refuse the launch/operation, never fall back to any other
    location."""


def _confined(candidate: Path, root: Path) -> Path:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise PointerConfinementError(
            f"{candidate} resolves to {resolved}, outside the workspace {root}"
        )
    return resolved


def ipc_workspace_dir(workspace_root: Path) -> Path:
    """The confined file-drop IPC directory under *workspace_root* — the
    value the `EDA_AGENT_WORKSPACE` pin must equal. Refuses symlink escapes."""
    root = workspace_root.resolve()
    return _confined(root / IPC_DIR_NAME, root)


def pointer_file_path(workspace_root: Path) -> Path:
    """The confined pointer-file path under *workspace_root* — the value the
    `EDA_AGENT_POINTER_FILE` pin must equal. Refuses symlink escapes of the
    IPC directory and of the pointer file itself."""
    root = workspace_root.resolve()
    ipc_dir = _confined(root / IPC_DIR_NAME, root)
    return _confined(ipc_dir / POINTER_FILE_NAME, root)
