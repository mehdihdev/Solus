"""World roots (`SOLUS_SIM_ROOTS`), the bounded world-file scan, and fd-relative confinement.

Every path that reaches this fork from a tool argument is root-relative and is opened through
:func:`confined_open` (reads) or :func:`confined_write` (the one write sink, ``save_world``):
the root is opened as a directory descriptor, each component is opened with ``O_NOFOLLOW``
relative to its parent, and the leaf must be a regular file. Symlinks, ``..``, absolute paths
and option-shaped names never leave the root (the pattern of
``integrations/mcp/isaac/solus/assets.py``).
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .family_detect import FamilyName, family_hint

WORLD_SUFFIXES: Final = frozenset({".sdf", ".world"})
MAX_WORLD_FILES: Final = 500
MAX_SCAN_DEPTH: Final = 6
_HINT_BYTES: Final = 64 * 1024
_SAFE_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: A confinement root: a directory path, or a directory descriptor the caller already opened
#: ``O_NOFOLLOW`` step by step (the model store); the descriptor is dup'd, never closed here.
Root = Path | int


@dataclass(frozen=True)
class WorldFile:
    path: str  # root-relative POSIX path
    root: Path
    family_hint: FamilyName | None


def sim_roots() -> tuple[Path, ...]:
    """``SOLUS_SIM_ROOTS`` entries that are absolute, existing directories (deduplicated)."""
    roots: list[Path] = []
    for entry in os.environ.get("SOLUS_SIM_ROOTS", "").split(os.pathsep):
        path = Path(entry)
        if entry and path.is_absolute() and path.is_dir() and path not in roots:
            roots.append(path)
    return tuple(roots)


def list_world_files(roots: Sequence[Path]) -> list[WorldFile]:
    """``*.sdf`` / ``*.world`` under each root: no symlinks, no hidden dirs, bounded depth and
    count, sorted by root-relative path."""
    found: list[WorldFile] = []
    for root in roots:
        for rel in _walk_world_tree(root):
            if len(found) >= MAX_WORLD_FILES:
                return found
            found.append(WorldFile(path=rel, root=root, family_hint=_hint_for(root, rel)))
    return found


def _walk_world_tree(root: Path) -> list[str]:
    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and len(rel_dir.parts) < MAX_SCAN_DEPTH
        )
        for name in filenames:
            full = Path(dirpath) / name
            if full.suffix in WORLD_SUFFIXES and full.is_file() and not full.is_symlink():
                rels.append((rel_dir / name).as_posix() if rel_dir.parts else name)
    return sorted(rels)


def _hint_for(root: Path, rel: str) -> FamilyName | None:
    try:
        return family_hint(read_confined(root, rel, _HINT_BYTES, truncate=True))
    except ValueError:
        return None


def rel_parts(rel: str) -> tuple[str, ...]:
    """The components of a root-relative path, or ``ValueError`` (``..``, ``/x``, ``-x``, …)."""
    parts = tuple(rel.split("/"))
    if any(_SAFE_PART.fullmatch(p) is None for p in parts):
        raise ValueError("path must be root-relative with plain name components")
    return parts


def _open_parent(root: Root, parts: tuple[str, ...]) -> int:
    """The directory descriptor holding ``parts[-1]``, every step ``O_NOFOLLOW``."""
    try:
        fd = (
            os.dup(root)
            if isinstance(root, int)
            else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        )
    except OSError as error:
        raise ValueError("world root unavailable") from error
    for part in parts[:-1]:
        try:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError as error:
            raise ValueError("path unavailable or unsafe") from error
        finally:
            os.close(fd)
        fd = nxt
    return fd


def confined_open(root: Root, rel: str) -> int:
    """Open ``root/rel`` read-only through ``O_NOFOLLOW`` descriptors; the leaf must be a
    regular file. Returns the descriptor (caller closes). ``ValueError`` on any escape."""
    parts = rel_parts(rel)
    fd = _open_parent(root, parts)
    try:
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as error:
        raise ValueError("path unavailable or unsafe") from error
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(leaf).st_mode):
        os.close(leaf)
        raise ValueError("not a regular file")
    return leaf


def read_confined(root: Root, rel: str, max_bytes: int, *, truncate: bool = False) -> bytes:
    """The file's bytes through :func:`confined_open`; a file over ``max_bytes`` is refused
    unless ``truncate`` asks for the prefix."""
    fd = confined_open(root, rel)
    try:
        data = os.read(fd, max_bytes + 1)
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        if not truncate:
            raise ValueError("file too large")
        data = data[:max_bytes]
    return data


def confined_write(root: Root, rel: str, data: bytes) -> None:
    """Write ``root/rel`` through ``O_NOFOLLOW`` descriptors: a sibling temp file is created
    ``O_EXCL`` and renamed over the leaf, which must be absent or a regular file (a symlink,
    directory or fifo there is refused). ``ValueError`` on any escape or failure."""
    parts = rel_parts(rel)
    fd = _open_parent(root, parts)
    tmp = f".{parts[-1]}.solus-tmp"  # ponytail: a crash leaves it; the next write refuses (O_EXCL)
    try:
        try:
            mode = os.lstat(parts[-1], dir_fd=fd).st_mode
        except FileNotFoundError:
            mode = stat.S_IFREG
        if not stat.S_ISREG(mode):
            raise ValueError("destination is not a regular file")
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(out, view) :]
            os.rename(tmp, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
        except OSError:
            os.unlink(tmp, dir_fd=fd)
            raise
        finally:
            os.close(out)
    except OSError as error:
        raise ValueError("path unavailable or unsafe") from error
    finally:
        os.close(fd)


def model_dir(workspace: Path, sha256: str) -> Path:
    """``<workspace>/.solus/sim/models/<sha256>`` — the only place a Solus-pushed model lives."""
    if _SHA256.fullmatch(sha256) is None:
        raise ValueError("invalid model digest")
    return workspace / ".solus" / "sim" / "models" / sha256
