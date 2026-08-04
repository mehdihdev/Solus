"""Pure-Python git tree hashing for the vendored-tree integrity guards.

ADR-031 pins each vendored tree by its git tree hash: PROVENANCE.md records it,
and any byte change to `upstream/`/`vendor/` changes it and mechanically voids
the human sign-offs. The tests that enforce that guard used to shell out to
`git`, which made them **silently environment-dependent**: the CI image
(`ghcr.io/astral-sh/uv:python3.12-bookworm-slim`) ships no `git` binary, so the
one place the guard matters most crashed with `FileNotFoundError: 'git'`.

This module recomputes the same hash from the working tree with hashlib only —
no subprocess, no network, no git. `test_tree_hash.py` cross-checks it against
the real `git rev-parse` wherever git IS available, so the reimplementation can
never drift from the thing PROVENANCE's human-verifiable command reports.

Tool litter (`__pycache__`, `.ruff_cache`, …) is skipped by name: it is
gitignored, so it must not perturb the hash. That is also a bug fix — a stray
`.ruff_cache/` inside `upstream/` once broke the guard by being force-added to
the scratch index the old implementation used.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

#: Gitignored tool/OS artifacts that may appear inside a vendored tree. They are
#: untracked, so git's tree hash never includes them and neither do we.
IGNORED_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        ".DS_Store",
        ".git",
        "node_modules",
        ".coverage",
    }
)

#: Gitignored suffixes (compiled artifacts).
IGNORED_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")

_GIT_MODE_TREE = b"40000"  # git writes 40000, not 040000
_GIT_MODE_FILE = b"100644"
_GIT_MODE_EXEC = b"100755"
_GIT_MODE_LINK = b"120000"


def _is_ignored(path: Path) -> bool:
    return path.name in IGNORED_NAMES or path.name.endswith(IGNORED_SUFFIXES)


def _hash_object(kind: bytes, payload: bytes) -> bytes:
    """The raw 20-byte sha1 of a git object (`<kind> <len>\\0<payload>`)."""
    header = kind + b" " + str(len(payload)).encode() + b"\0"
    # sha1 here is git's object-id algorithm, not a security primitive.
    return hashlib.sha1(header + payload, usedforsecurity=False).digest()


def _blob_id(path: Path) -> bytes:
    if path.is_symlink():
        # git stores the link target as the blob content, unresolved.
        return _hash_object(b"blob", os.readlink(path).encode())
    return _hash_object(b"blob", path.read_bytes())


def _entry_mode(path: Path) -> bytes:
    """git's rule exactly: the OWNER execute bit decides 100755 vs 100644.

    Deliberately NOT `os.access(path, os.X_OK)` — running as root (every CI
    container) that call reports success for files with no execute bits at all,
    which silently hashed all 121 vendored files as 100755 and made this guard
    fail only inside CI. `lstat` reads the bit itself, so the answer is the same
    for root and non-root, on every filesystem."""
    if path.is_symlink():
        return _GIT_MODE_LINK
    return _GIT_MODE_EXEC if path.lstat().st_mode & stat.S_IXUSR else _GIT_MODE_FILE


def _sort_key(path: Path) -> bytes:
    """git orders tree entries by name bytes, comparing a directory as if its
    name ended in `/` — so `foo.txt` sorts before `foo/` even though `.` < `/`
    would say otherwise at the raw-byte level."""
    suffix = b"/" if path.is_dir() and not path.is_symlink() else b""
    return path.name.encode() + suffix


def _tree_id(root: Path) -> bytes | None:
    """The raw 20-byte tree id for `root`, or None if it holds nothing git
    would track (git cannot represent an empty directory)."""
    entries: list[bytes] = []
    for child in sorted((p for p in root.iterdir() if not _is_ignored(p)), key=_sort_key):
        if child.is_dir() and not child.is_symlink():
            subtree = _tree_id(child)
            if subtree is None:
                continue  # empty (or litter-only) directory: git omits it
            entries.append(_GIT_MODE_TREE + b" " + child.name.encode() + b"\0" + subtree)
            continue
        entries.append(_entry_mode(child) + b" " + child.name.encode() + b"\0" + _blob_id(child))
    if not entries:
        return None
    return _hash_object(b"tree", b"".join(entries))


def git_tree_hash(root: Path) -> str:
    """The 40-hex git tree hash of `root`'s CURRENT working-tree contents —
    identical to `git rev-parse HEAD:<root>` when the tree is committed clean.

    Raises FileNotFoundError if `root` does not exist, and ValueError if it
    holds nothing trackable (an empty vendored tree is always a bug)."""
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")
    tree = _tree_id(root)
    if tree is None:
        raise ValueError(f"{root} contains no trackable files")
    return tree.hex()
