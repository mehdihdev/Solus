"""Confined file access only. I3 code server owns every environment action."""

import base64
import os
import tempfile
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


def write_file(workspace: Path, path: str, content: str, *, create_dirs: bool) -> dict[str, object]:
    data = content.encode("utf-8")
    if len(data) > WRITE_CAP_BYTES:
        raise MachineActionError(f"content is {len(data)} bytes; write_file is capped at 200 KB")
    target = confine(workspace, path)
    if target.is_dir():
        raise MachineActionError(f"{path!r} is a directory")
    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.is_dir():
        raise MachineActionError(f"parent directory of {path!r} does not exist (pass create_dirs)")
    # Atomic: temp in the same directory, then replace — a reader never sees a
    # half-written file.
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".solus-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return {"path": str(target.relative_to(workspace.resolve())), "bytes_written": len(data)}
