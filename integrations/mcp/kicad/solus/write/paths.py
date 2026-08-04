"""Path confinement for the ONE file `set_symbol_property` may mutate (T2b).

Unlike `solus/workspace.py::artifact_destination` (which confines a bare
filename the OVERLAY chooses under `<workspace>/solus-artifacts/`), this
confines an ARBITRARY caller-supplied path to an EXISTING `.kicad_sch` file
anywhere inside the workspace. Symlinks are resolved before the confinement
check (defense in depth against a symlinked escape), and every failure here
refuses with the same stable reason: `path_escapes_workspace` — a caller
cannot distinguish "traversal" from "wrong suffix" from "missing file" by
reason string alone, which is deliberate (CLAUDE.md §7: never leak
filesystem-shape detail through an error channel).
"""

from pathlib import Path

from solus.workspace import WorkspaceNotConfiguredError, workspace_root
from solus.write.errors import REASON_FILE_TOO_LARGE, REASON_PATH_ESCAPES_WORKSPACE, RefusalError

# 8 MiB — the plan-locked cap on schematic files this tool will edit.
MAX_SCHEMATIC_BYTES = 8 * 1024 * 1024
SCHEMATIC_SUFFIX = ".kicad_sch"


def resolve_confined_schematic_path(raw_path: str) -> Path:
    """The resolved, confined, existing `.kicad_sch` path for *raw_path*.

    A relative *raw_path* is taken relative to the workspace root; an
    absolute one is resolved as-is and then must still land inside the
    workspace. Raises `RefusalError` (never raises any other exception type)
    on every rejection.
    """
    if not raw_path:
        raise RefusalError(REASON_PATH_ESCAPES_WORKSPACE)
    try:
        root = workspace_root()
    except WorkspaceNotConfiguredError as exc:
        # H3: no workspace to confine into is the same honest bucket as
        # "escaped the workspace" — there is nothing to prove this path is
        # inside, so refuse rather than let the exception escape.
        raise RefusalError(REASON_PATH_ESCAPES_WORKSPACE) from exc
    candidate = Path(raw_path)
    base = candidate if candidate.is_absolute() else root / candidate
    resolved = base.resolve()
    if resolved.suffix != SCHEMATIC_SUFFIX:
        raise RefusalError(REASON_PATH_ESCAPES_WORKSPACE)
    if not resolved.is_relative_to(root):
        raise RefusalError(REASON_PATH_ESCAPES_WORKSPACE)
    if not resolved.is_file():
        raise RefusalError(REASON_PATH_ESCAPES_WORKSPACE)
    if resolved.stat().st_size > MAX_SCHEMATIC_BYTES:
        raise RefusalError(REASON_FILE_TOO_LARGE)
    return resolved
