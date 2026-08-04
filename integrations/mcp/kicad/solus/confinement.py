"""Path-argument confinement for every registered MCP tool call (H2).

Before any registered tool body runs, every STRING argument whose name is
path-shaped (`project_path`, `schematic_path` — substring `path`,
case-insensitive, enumerated from the actual roster schemas in
`solus/roster.py`: `get_project_structure`, `extract_project_netlist`,
`analyze_schematic_connections`, `analyze_bom`, `export_netlist`, and
`set_symbol_property`) must resolve — symlinks included — INSIDE
`solus.workspace.workspace_root()`. A prompt-injected model call that passes
an absolute path to another team's KiCad project, or a crafted relative path
that traverses out via `..` or a symlink, is refused here in ONE place,
before ANY tool (the 5 upstream reads, the Solus-authored `export_netlist`,
and the confirmation-gated `set_symbol_property`) ever touches the
filesystem. This is wired into every registration through
`solus/trimming.py::TrimmingRegistrar`.

`solus/write/paths.py` keeps its own, stricter, `.kicad_sch`-specific check
for `set_symbol_property` as defense in depth — this module is the outer,
universal layer every registered tool passes through regardless of which
package implements it.

H3: an unconfigured workspace (`WorkspaceNotConfiguredError`) folds into the
SAME stable `path_escapes_workspace` reason as an actual escape — there is no
workspace to confine into, so nothing can be proven inside it. This mirrors
the "closest honest bucket" call `solus/write/locator.py` makes for
unparseable input rather than minting a new reason for every distinct cause.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from solus.workspace import WorkspaceNotConfiguredError, workspace_root

REASON_PATH_ESCAPES_WORKSPACE = "path_escapes_workspace"

_PATH_NAME_MARKER = "path"


def _is_path_shaped(name: str) -> bool:
    """Whether *name* names a path-shaped tool argument."""
    return _PATH_NAME_MARKER in name.lower()


def _is_confined(raw: str, root: Path) -> bool:
    """Whether *raw* (relative-to-root or absolute) resolves inside *root*."""
    if not raw:
        return False
    candidate = Path(raw)
    base = candidate if candidate.is_absolute() else root / candidate
    resolved = base.resolve()
    return resolved.is_relative_to(root)


def _refusal() -> dict[str, Any]:
    return {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


def confinement_refusal(kwargs: Mapping[str, Any]) -> dict[str, Any] | None:
    """`None` when every path-shaped argument in *kwargs* is confined to the
    workspace; otherwise the structured tool-error envelope the caller must
    return INSTEAD of invoking the tool body. Never raises — a tool with no
    path-shaped arguments (e.g. `list_projects`) never consults the
    workspace at all."""
    path_args = {name: value for name, value in kwargs.items() if _is_path_shaped(name)}
    if not path_args:
        return None
    try:
        root = workspace_root()
    except WorkspaceNotConfiguredError:
        return _refusal()
    for value in path_args.values():
        if not isinstance(value, str) or not _is_confined(value, root):
            return _refusal()
    return None
