"""Stage roots (`SOLUS_SIM_ROOTS`), the bounded stage-file scan, and fd-relative confinement.

The gazebo fork's ``worlds.py`` shape (SOLUSDEV-322), named apart because each fork ships on
its own: every path that reaches this fork from a tool argument is root-relative and is opened
through :func:`open_stage_file` (reads) or :func:`write_stage_file` (the one write sink,
``save_stage``). The root is opened as a directory descriptor, each component ``O_NOFOLLOW``
relative to its parent, and the leaf must be a regular file; symlinks, ``..``, absolute paths
and option-shaped names never leave a root.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

STAGE_SUFFIXES: Final = frozenset({".usd", ".usda", ".usdc", ".usdz"})
#: `save_stage` destinations: a package (.usdz) is never written.
SAVE_SUFFIXES: Final = frozenset({".usd", ".usda", ".usdc"})
MAX_STAGE_FILES: Final = 500
MAX_SCAN_DEPTH: Final = 6
_SAFE_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
#: A confinement root: a directory path, or a directory descriptor the caller already opened
#: ``O_NOFOLLOW`` step by step (the model store); the descriptor is dup'd, never closed here.
RootRef = Path | int


@dataclass(frozen=True)
class StageFile:
    path: str  # root-relative POSIX path
    root: Path


def stage_roots() -> tuple[Path, ...]:
    """``SOLUS_SIM_ROOTS`` entries that are absolute, existing directories (deduplicated)."""
    roots: list[Path] = []
    for entry in os.environ.get("SOLUS_SIM_ROOTS", "").split(os.pathsep):
        path = Path(entry)
        if entry and path.is_absolute() and path.is_dir() and path not in roots:
            roots.append(path)
    return tuple(roots)


def list_stage_files(roots: Sequence[Path]) -> list[StageFile]:
    """USD files under each root: no symlinks, no hidden dirs, bounded depth and count."""
    found: list[StageFile] = []
    for root in roots:
        for rel in _walk_stage_tree(root):
            if len(found) >= MAX_STAGE_FILES:
                return found
            found.append(StageFile(path=rel, root=root))
    return found


def _walk_stage_tree(root: Path) -> list[str]:
    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and len(rel_dir.parts) < MAX_SCAN_DEPTH
        )
        for name in filenames:
            full = Path(dirpath) / name
            if full.suffix in STAGE_SUFFIXES and full.is_file() and not full.is_symlink():
                rels.append((rel_dir / name).as_posix() if rel_dir.parts else name)
    return sorted(rels)


def stage_parts(rel: str) -> tuple[str, ...]:
    """The components of a root-relative path, or ``ValueError`` (``..``, ``/x``, ``-x``, …)."""
    parts = tuple(rel.split("/"))
    if any(_SAFE_PART.fullmatch(p) is None or p in (".", "..") for p in parts):
        raise ValueError("path must be root-relative with plain name components")
    return parts


def _stage_parent_fd(root: RootRef, parts: tuple[str, ...]) -> int:
    """The directory descriptor holding ``parts[-1]``, every step ``O_NOFOLLOW``."""
    try:
        fd = os.dup(root) if isinstance(root, int) else os.open(root, _DIR_FLAGS)
    except OSError as error:
        raise ValueError("stage root unavailable") from error
    for part in parts[:-1]:
        try:
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
        except OSError as error:
            raise ValueError("path unavailable or unsafe") from error
        finally:
            os.close(fd)
        fd = nxt
    return fd


def open_stage_file(root: RootRef, rel: str) -> int:
    """Open ``root/rel`` read-only through ``O_NOFOLLOW`` descriptors; the leaf must be a
    regular file. Returns the descriptor (caller closes). ``ValueError`` on any escape."""
    parts = stage_parts(rel)
    fd = _stage_parent_fd(root, parts)
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


def stage_file_size(root: RootRef, rel: str) -> int | None:
    """The regular file's size under the root, or ``None`` when nothing readable is there."""
    try:
        fd = open_stage_file(root, rel)
    except ValueError:
        return None
    try:
        return os.fstat(fd).st_size
    finally:
        os.close(fd)


def write_stage_file(root: RootRef, rel: str, data: bytes) -> None:
    """Write ``root/rel`` through ``O_NOFOLLOW`` descriptors: a sibling temp file is created
    ``O_EXCL`` and renamed over the leaf, which must be absent or a regular file."""
    parts = stage_parts(rel)
    fd = _stage_parent_fd(root, parts)
    tmp = f".{parts[-1]}.solus-tmp"
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


def resolve_stage(stage_ref: str) -> tuple[Path, str]:
    """The first sim root holding ``stage_ref`` as a regular USD file, and the relative path."""
    roots = stage_roots()
    if not roots:
        raise ValueError("SOLUS_SIM_ROOTS names no directory to look for stages in")
    parts = stage_parts(stage_ref)
    if Path(parts[-1]).suffix not in STAGE_SUFFIXES:
        raise ValueError("a stage is a .usd, .usda, .usdc or .usdz file")
    for root in roots:
        try:
            os.close(open_stage_file(root, stage_ref))
        except ValueError:
            continue
        return root, stage_ref
    raise ValueError("no such stage file under the sim roots")
