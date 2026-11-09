"""`list_projects` scoped to the linked workspace (SOLUSDEV-319).

Upstream's `list_projects` walks `~/Documents/KiCad` plus search paths, which
surfaces projects (KiCad's own templates, other folders) that every read tool
then refuses as escaping the workspace. This lists only `.kicad_pro` files
inside the workspace — the same confinement every other tool applies — and
flags the one KiCad currently has open (its `~<name>.lck` editor lock).
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from solus.workspace import WorkspaceNotConfiguredError, workspace_root

MAX_PROJECTS = 50
MAX_DEPTH = 6
_SKIPPED_DIRS = frozenset({"node_modules", "__pycache__", "solus-artifacts"})


def _skip(name: str) -> bool:
    return name.startswith(".") or name.endswith("-backups") or name in _SKIPPED_DIRS


def _entry(root: Path, path: Path) -> dict[str, Any]:
    return {
        "name": path.stem,
        "path": str(path),
        "relative_path": path.relative_to(root).as_posix(),
        "modified": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        "open_in_kicad": (path.parent / f"~{path.name}.lck").exists(),
    }


def list_projects() -> list[dict[str, Any]]:
    """KiCad projects in the linked workspace; `open_in_kicad` marks the one
    KiCad has open. Prefer that one when the user says "the project I have open"."""
    try:
        root = workspace_root()
    except WorkspaceNotConfiguredError:
        return []
    found: list[Path] = []
    for directory, subdirs, files in os.walk(root):  # followlinks=False: no symlink escapes
        depth = len(Path(directory).relative_to(root).parts)
        subdirs[:] = sorted(d for d in subdirs if not _skip(d)) if depth < MAX_DEPTH else []
        found.extend(Path(directory, f) for f in sorted(files) if f.endswith(".kicad_pro"))
    projects = [_entry(root, p) for p in found if p.resolve().is_relative_to(root)]
    projects.sort(key=lambda p: (not p["open_in_kicad"], p["relative_path"]))
    return projects[:MAX_PROJECTS]


def register_project_discovery(mcp: Any) -> None:
    mcp.tool()(list_projects)
