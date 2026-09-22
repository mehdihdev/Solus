"""Confined file access only. I3 code server owns every environment action."""

import base64
from pathlib import Path

READ_CAP_BYTES = 1024 * 1024
WRITE_CAP_BYTES = 200 * 1024


class MachineActionError(ValueError):
    """A portable refusal at the machine file boundary."""


def confine(workspace: Path, candidate: str) -> Path:
    """Resolve `candidate` (relative to the workspace or absolute) and refuse
    anything whose REAL path leaves the workspace — `..` and symlinks alike."""
    root = workspace.resolve()
    target = (root / candidate).resolve()
    if target != root and not target.is_relative_to(root):
        raise MachineActionError(f"path {candidate!r} resolves outside the workspace; refused")
    return target


def read_file(workspace: Path, path: str) -> dict[str, object]:
    target = confine(workspace, path)
    if not target.is_file():
        raise MachineActionError(f"{path!r} is not a file inside the workspace")
    size = target.stat().st_size
    if size > READ_CAP_BYTES:
        raise MachineActionError(f"{path!r} is {size} bytes; read_file is capped at 1 MiB")
    raw = target.read_bytes()
    relative = str(target.relative_to(workspace.resolve()))
    if b"\x00" in raw:
        content, encoding = base64.b64encode(raw).decode("ascii"), "base64"
    else:
        content, encoding = raw.decode("utf-8", errors="replace"), "utf-8"
    return {"path": relative, "content": content, "encoding": encoding, "size_bytes": size}


def plan_write_file(
    workspace: Path, path: str, content: str, *, create_dirs: bool
) -> dict[str, object]:
    from solus_companion.machine.file_write import preview

    return preview(workspace, path, content, create_dirs=create_dirs)


def write_file(
    workspace: Path,
    path: str,
    content: str,
    *,
    create_dirs: bool,
    expected_fingerprint: str | None = None,
) -> dict[str, object]:
    from solus_companion.machine.file_write import write

    return write(
        workspace, path, content, create_dirs=create_dirs, expected_fingerprint=expected_fingerprint
    )
