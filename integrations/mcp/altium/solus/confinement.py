"""Path-argument confinement for every registered MCP tool call.

Before any registered tool body runs, every SUPPLIED argument whose name is
path-shaped (substring `path`, case-insensitive — `project_path`,
`schematic_path`, `output_path`, ...) must be a string that resolves —
symlinks included — INSIDE `solus.workspace.workspace_root()`. `None` and
`""` count as UNSUPPLIED: the MCP SDK's arg validation forwards every
arg-model field including unsupplied defaults, and upstream's own tool
bodies drop falsy path args before building IPC params — refusing those
defaults would make every tool carrying an optional path argument refuse
every call (the H1 finding). A prompt-injected model call that
passes an absolute path to another team's Altium project, or a crafted
relative path that traverses out via `..` or a symlink, is refused here in
ONE place, before any tool ever touches the filesystem. ALT-5's registration
shim wires this into every tool it registers, mirroring how the kicad fork's
trimming registrar consumes ITS confinement module — same function name,
same semantics, same stable refusal envelope.

An unconfigured workspace (`WorkspaceNotConfiguredError`) folds into the
SAME stable `path_escapes_workspace` reason as an actual escape — there is
no workspace to confine into, so nothing can be proven inside it. This
mirrors the "closest honest bucket" call the kicad fork made rather than
minting a new reason for every distinct cause.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .workspace import WorkspaceNotConfiguredError, workspace_root

REASON_PATH_ESCAPES_WORKSPACE = "path_escapes_workspace"

_PATH_NAME_MARKER = "path"


def _is_path_shaped(name: str) -> bool:
    """Whether *name* names a path-shaped tool argument."""
    return _PATH_NAME_MARKER in name.lower()


def _is_confined(raw: str, root: Path) -> bool:
    """Whether *raw* (relative-to-root or absolute) resolves inside *root*.

    Never raises (M1): `Path.resolve()` raises ValueError on embedded NUL
    bytes (and OSError on pathological filesystem states); both fold into a
    plain "not confined" so the caller returns the stable refusal envelope."""
    if not raw:
        return False
    candidate = Path(raw)
    base = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = base.resolve()
    except (OSError, ValueError):
        return False
    return resolved.is_relative_to(root)


def _refusal() -> dict[str, Any]:
    return {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


def _is_absent(value: Any) -> bool:
    """Whether *value* is an unsupplied-default marker rather than a path.

    The MCP SDK's arg validation passes EVERY arg-model field to the tool —
    unsupplied defaults included — so wrappers see `project_path=None` (the
    proj_* reads) and `sheet_path=""` on every call. Upstream tool bodies
    drop falsy path args before building IPC params (`if project_path:`), so
    None/"" here IS "argument absent": skip it, never refuse the default."""
    return value is None or (isinstance(value, str) and value == "")


def confinement_refusal(kwargs: Mapping[str, Any]) -> dict[str, Any] | None:
    """`None` when every SUPPLIED path-shaped argument in *kwargs* is confined
    to the workspace; otherwise the structured tool-error envelope the caller
    must return INSTEAD of invoking the tool body. `None`/`""` values are
    treated as absent (see `_is_absent`). Never raises — a tool with no
    supplied path-shaped arguments never consults the workspace at all."""
    path_args = {
        name: value
        for name, value in kwargs.items()
        if _is_path_shaped(name) and not _is_absent(value)
    }
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
