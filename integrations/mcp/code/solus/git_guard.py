"""Git metadata protection shared by both sandboxes (docs/api/code-command-execution.md §3).

`protected_git_dirs` resolves `.git` (or the `gitdir:` file's target and its
`commondir`); macOS makes those whole directories read-only by profile, Linux (Landlock grants only)
relies on `git_metadata_digest` before/after every command. The digest covers
`.git` itself, `.gitmodules`, `config*`, `commondir`, `hooks/**`, `info/**`,
`worktrees/**` and, at any depth under `modules/`, `config*`, `hooks/**`, `info/**`,
`commondir` and `gitdir` — full contents and modes.
Past any cap it answers a unique sentinel: always "changed" (fail closed).
"""

import hashlib
import os
import stat
import uuid
from pathlib import Path

from .safe_read import open_regular, read_regular

MAX_GIT_ENTRIES = 4096
MAX_GIT_BYTES = 64 * 1024 * 1024
MAX_GIT_VISITED = 200_000
NESTED_METADATA_DIRS: frozenset[str] = frozenset({"hooks", "info"})
NESTED_METADATA_FILES: frozenset[str] = frozenset({"commondir", "gitdir"})


def _real(path: Path | str) -> str:
    return os.path.realpath(path)


def _gitfile_target(dot_git: Path) -> str | None:
    data = read_regular(dot_git, 4096)
    if data is None:
        return None
    text = data.decode("utf-8", errors="replace").strip()
    if not text.startswith("gitdir:"):
        return None
    target = text[len("gitdir:") :].strip()
    return _real(dot_git.parent / target) if target else None


def _commondir(git_dir: str) -> str:
    data = read_regular(os.path.join(git_dir, "commondir"), 4096, follow=True)
    if data is None:
        return git_dir
    target = data.decode("utf-8", errors="replace").strip()
    return _real(os.path.join(git_dir, target)) if target else git_dir


def protected_git_dirs(workspace: Path) -> tuple[str, str]:
    """`(git dir, common dir)` whose metadata is protected: `.git` itself, or the
    target of a `gitdir:` file and the `commondir` it names."""
    dot_git = Path(workspace) / ".git"
    default = str(dot_git)
    if dot_git.is_file() and not dot_git.is_symlink():
        target = _gitfile_target(dot_git)
        if target is None:
            return default, default
        return target, _commondir(target)
    if dot_git.is_dir():
        return default, _commondir(default)
    return default, default


class _OverflowError(Exception):
    """A digest cap was hit: the answer must compare as changed."""


class _Digest:
    def __init__(self) -> None:
        self.hash = hashlib.sha256()
        self.entries = 0
        self.bytes = 0
        self.visited = 0

    def visit(self) -> None:
        self.visited += 1
        if self.visited > MAX_GIT_VISITED:
            raise _OverflowError

    def entry(self, path: str) -> None:
        try:
            info = os.lstat(path)
        except OSError:
            self.hash.update(f"{path}:absent\0".encode(errors="replace"))
            return
        size = 0 if stat.S_ISDIR(info.st_mode) else info.st_size
        self.entries += 1
        self.bytes += size
        if self.entries > MAX_GIT_ENTRIES or self.bytes > MAX_GIT_BYTES:
            raise _OverflowError
        self.hash.update(f"{path}:{info.st_mode}:{size}\0".encode(errors="replace"))
        if stat.S_ISLNK(info.st_mode):
            self.hash.update(os.readlink(path).encode(errors="replace"))
        elif stat.S_ISREG(info.st_mode):
            self._stream(path)

    def _stream(self, path: str) -> None:
        """Contents of a regular file; anything else (a FIFO swapped in after the
        lstat) hashes as unreadable rather than blocking."""
        try:
            with open_regular(path) as descriptor:
                if descriptor is None:
                    self.hash.update(b"unreadable")
                    return
                for block in iter(lambda: os.read(descriptor, 1024 * 1024), b""):
                    self.hash.update(block)
        except OSError:
            self.hash.update(b"unreadable")

    def tree(self, root: str, nested: bool = False) -> None:
        """Every entry under `root`; with `nested`, only metadata entries are hashed
        (the whole tree is still walked — nothing is skipped by name)."""
        self.entry(root)
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            for name in sorted([*dirs, *files]):
                self.visit()
                path = os.path.join(directory, name)
                relative = os.path.relpath(path, root)
                if not nested or _nested_metadata(relative):
                    self.entry(path)


def _nested_metadata(relative: str) -> bool:
    """Metadata at any depth under `modules/` or `worktrees/`."""
    parts = relative.split(os.sep)
    return (
        bool(NESTED_METADATA_DIRS.intersection(parts))
        or parts[-1].startswith("config")
        or parts[-1] in NESTED_METADATA_FILES
    )


def _digest_git_dir(digest: _Digest, git_dir: str) -> None:
    digest.entry(git_dir)
    try:
        names = sorted(os.listdir(git_dir))
    except OSError:
        names = []
    for name in names:
        if name.startswith("config"):
            digest.entry(os.path.join(git_dir, name))
    digest.entry(os.path.join(git_dir, "commondir"))
    digest.tree(os.path.join(git_dir, "hooks"))
    digest.tree(os.path.join(git_dir, "info"))
    digest.tree(os.path.join(git_dir, "modules"), nested=True)
    digest.tree(os.path.join(git_dir, "worktrees"))


def git_metadata_digest(workspace: Path) -> str:
    """A digest of every protected git metadata path (full contents and modes).
    Past any cap it answers a unique sentinel, which always compares as changed."""
    digest = _Digest()
    try:
        digest.entry(os.path.join(workspace, ".git"))
        digest.entry(os.path.join(workspace, ".gitmodules"))
        for git_dir in dict.fromkeys(protected_git_dirs(workspace)):
            _digest_git_dir(digest, git_dir)
    except _OverflowError:
        return f"overflow:{uuid.uuid4().hex}"
    return digest.hash.hexdigest()
