"""`scan_folder` / `folder_digest` (docs/api/local-folder.md §4).

Walks the workspace without following symlinks (a symlinked file or
directory is skipped, never read — it may point outside the folder), skips
the documented directories, keeps only tool-relevant suffixes, sorts the
relative POSIX paths, caps the list at MAX_FILES (the walk stops at the
cap, so a truncated result is the first MAX_FILES files in sorted-walk order,
themselves sorted), hashes each file with a
streamed blake2b-128 (null over MAX_HASH_BYTES), and folds
`joined-path:hash-or-size\n` lines into a blake2b-128 digest. Both tools
share `_collect()` so the cloud compares like with like. `scan_folder` also
parses the walked dependency files into `dependencies` (deps.py —
docs/api/code-environment.md §3).

Wire shape: a file is `{parts, size, hash, tool}` — `parts` is the relative
path SPLIT into segments and `hash` is 32 hex chars, because the cloud's
ingress redaction masks any 40+ char high-entropy string (a 64-hex sha256, a
40-hex git sha, a long joined path) and would otherwise blank the scan.
"""

import hashlib
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any, TypedDict

from .deps import collect_dependencies
from .detect import tools_installed
from .gitremote import git_info
from .toolmap import HASH_CHUNK_BYTES, MAX_FILES, MAX_HASH_BYTES, SKIP_DIRS, tool_for

logger = logging.getLogger("solus.local.scan")

SCHEMA_VERSION = 1


class FileEntry(TypedDict):
    parts: list[str]
    size: int
    hash: str | None
    tool: str


def _open_for_hash(path: Path) -> IO[bytes]:
    return path.open("rb")


def file_hash(path: Path, *, size: int | None = None) -> str | None:
    """Streamed blake2b-128 (32 hex), or None when the file is over the cap
    or unreadable."""
    try:
        length = path.stat().st_size if size is None else size
        if length > MAX_HASH_BYTES:
            return None
        digest = hashlib.blake2b(digest_size=16)
        # Explicit byte budget: a file that grows mid-read is still capped.
        budget = MAX_HASH_BYTES
        with _open_for_hash(path) as handle:
            while chunk := handle.read(min(HASH_CHUNK_BYTES, budget + 1)):
                budget -= len(chunk)
                if budget < 0:
                    return None
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _walk(root: Path) -> Iterator[tuple[str, Path]]:
    """`(relative POSIX path, absolute path)` for every regular, non-symlink
    file with a tool-relevant suffix, skipping SKIP_DIRS and symlinked dirs."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(
            name for name in dirnames if name not in SKIP_DIRS and not (current / name).is_symlink()
        )
        # Sorted per directory so the capped walk is deterministic.
        for name in sorted(filenames):
            if tool_for(name) is None:
                continue
            absolute = current / name
            if absolute.is_symlink() or not absolute.is_file():
                continue
            yield absolute.relative_to(root).as_posix(), absolute


def _entry(rel: str, absolute: Path) -> FileEntry | None:
    try:
        size = absolute.stat().st_size
    except OSError:
        return None
    return {
        "parts": rel.split("/"),
        "size": size,
        "hash": file_hash(absolute, size=size),
        "tool": tool_for(rel) or "",
    }


def compute_digest(files: list[FileEntry]) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for entry in files:
        joined = "/".join(entry["parts"])
        digest.update(f"{joined}:{entry['hash'] or entry['size']}\n".encode())
    return digest.hexdigest()


def _candidates(root: Path) -> tuple[list[tuple[str, Path]], bool]:
    """Up to MAX_FILES candidates in walk order, and whether more existed.
    The walk is abandoned at MAX_FILES + 1 so memory is bounded by the cap,
    not by the tree."""
    collected: list[tuple[str, Path]] = []
    for item in _walk(root):
        if len(collected) == MAX_FILES:
            return collected, True
        collected.append(item)
    return collected, False


def _collect(root: Path) -> tuple[list[FileEntry], bool]:
    """The sorted, capped file list and whether it was truncated."""
    try:
        candidates, truncated = _candidates(root)
    except OSError:
        return [], False
    candidates.sort(key=lambda item: item[0])
    files = [entry for rel, absolute in candidates if (entry := _entry(rel, absolute))]
    return files, truncated


def scan_folder(root: Path, *, tools: dict[str, bool] | None = None) -> dict[str, Any]:
    """The full §4 `scan_folder` shape for `root`."""
    files, truncated = _collect(root)
    dependencies, truncated_dependencies = collect_dependencies(
        root, [entry["parts"] for entry in files]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "root_name": root.name,
        "git": git_info(root),
        "files": files,
        "digest": compute_digest(files),
        "truncated": truncated,
        "tools_installed": dict(tools) if tools is not None else dict(tools_installed()),
        "dependencies": dependencies,
        "truncated_dependencies": truncated_dependencies,
    }


def folder_digest(root: Path) -> dict[str, Any]:
    """`{digest, truncated}` — the same digest `scan_folder` reports."""
    files, truncated = _collect(root)
    return {"digest": compute_digest(files), "truncated": truncated}
