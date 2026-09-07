"""Workspace resolution and path confinement for the `local` server.

The companion passes the linked folder via `SOLUS_MCP_WORKSPACE` (set by
`bin/launch`). `workspace_root()` FAILS CLOSED when the variable is unset or
empty — never the process cwd. `resolve_inside()` is the one path gate every
tool uses: a relative POSIX path must stay inside the root after symlink
resolution, or the answer is None (never an exception).
"""

import os
from pathlib import Path, PurePosixPath

#: Characters that make a "relative" path smell absolute/foreign (Windows
#: drive or UNC forms, backslash separators) — refused outright.
_FOREIGN_MARKERS = ("\\", ":")


class WorkspaceNotConfiguredError(RuntimeError):
    """`SOLUS_MCP_WORKSPACE` is unset or empty; refuse rather than confine to
    an arbitrary cwd."""


def workspace_root() -> Path:
    """The resolved linked folder from `SOLUS_MCP_WORKSPACE`, or raise."""
    raw = os.environ.get("SOLUS_MCP_WORKSPACE", "")
    if not raw:
        raise WorkspaceNotConfiguredError(
            "SOLUS_MCP_WORKSPACE is not set; refusing rather than confining to the process cwd"
        )
    return Path(raw).resolve()


def is_safe_relative(rel_path: str) -> bool:
    """A non-empty, relative, traversal-free POSIX path."""
    if not rel_path or any(marker in rel_path for marker in _FOREIGN_MARKERS):
        return False
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or rel_path.startswith("/"):
        return False
    parts = pure.parts
    return bool(parts) and all(part not in ("..", ".", "") for part in parts)


def resolve_inside(rel_path: str, root: Path | None = None) -> Path | None:
    """The resolved absolute path of `rel_path` under the workspace, or None
    when the path is unsafe, missing, or resolves (via symlink) outside it."""
    try:
        base = (root or workspace_root()).resolve()
        if not is_safe_relative(rel_path):
            return None
        resolved = (base / rel_path).resolve(strict=True)
    except (WorkspaceNotConfiguredError, OSError, ValueError):
        return None
    return resolved if resolved.is_relative_to(base) else None
