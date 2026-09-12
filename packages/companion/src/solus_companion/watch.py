"""Local design-change sensor (SOLUSDEV-167).

The companion could already speak first — `_status_loop` is an unsolicited,
event-driven, coalesced push that has been in production since BRG-03. What was
missing was anything to say: nothing on the customer's machine observed the
design files, so a KiCad edit stayed invisible until the next cloud sweep asked
for a full re-export.

This is the cheapest sensor that answers "did anything move?": a `stat()` sweep
over the workspace, hashed into one fingerprint. No new dependency — the
companion declares only `websockets`, `mcp` and `pydantic`, and adding a file
watcher would mean a dependency, an ADR-031 re-vendor, and a platform matrix for
a question `os.stat` already answers.

**Ceiling, stated rather than hidden**: resolution is the poll period, and it
sees only SAVED files.

ponytail: `watchfiles` (inotify/FSEvents/ReadDirectoryChangesW) is the upgrade if
sub-second local latency is ever wanted. It is a real dependency in a process
that ships as a signed binary, which is why it is not here yet.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger("solus_companion.watch")

#: The forks write their exports here. Watching it would make the sensor trigger
#: on its own output — an export loop that never settles.
ARTIFACT_DIR_NAME = "solus-artifacts"

#: Suffixes that constitute "the design changed". Deliberately narrow: a build
#: artifact, a backup, or an editor swap file moving is not a design change, and
#: treating it as one spends a probe for nothing.
DESIGN_SUFFIXES = frozenset(
    {
        ".kicad_sch",
        ".kicad_pcb",
        ".kicad_pro",
        ".net",
        ".schdoc",
        ".pcbdoc",
        ".prjpcb",
    }
)

#: Bound the sweep. A workspace someone points at their home directory must not
#: turn the sensor into a disk crawler.
MAX_FILES = 2000


SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".ino",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".step",
        ".stp",
        ".sldprt",
        ".sldasm",
        ".iges",
        ".igs",
        ".f3d",
    }
)
DEPENDENCY_NAMES = frozenset(
    {
        "pyproject.toml",
        "environment.yml",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "cargo.toml",
        "cargo.lock",
        "uv.lock",
    }
)
SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", ARTIFACT_DIR_NAME}
)
MAX_ENTRIES = 10_000


def _bounded_files(root: Path) -> Iterable[Path]:
    """Bound inspected entries, including irrelevant files and directories."""
    pending = [root]
    remaining = MAX_ENTRIES
    while pending and remaining > 0:
        current = pending.pop()
        children: list[Path] = []
        with os.scandir(current) as entries:
            for entry in entries:
                remaining -= 1
                if entry.is_symlink():
                    pass
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIP_DIRS:
                        children.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
                if remaining <= 0:
                    break
        pending.extend(sorted(children, reverse=True))


def _pointer(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        return None
    with path.open("rb") as handle:
        data = handle.read(4097)
    return data.decode("utf-8") if len(data) <= 4096 else None


def _git_locations(root: Path) -> tuple[Path, Path] | None:
    """Resolve only bounded worktree pointers within the workspace or home."""
    dotgit = root / ".git"
    if dotgit.is_symlink():
        return None
    gitdir = dotgit
    if dotgit.is_file():
        pointer = _pointer(dotgit)
        if not pointer or not pointer.startswith("gitdir:"):
            return None
        gitdir = (root / pointer.split(":", 1)[1].strip()).resolve()
    home = Path.home().resolve()
    if not (gitdir.is_relative_to(root) or gitdir.is_relative_to(home)):
        return None
    if not gitdir.is_dir():
        return None
    common = gitdir
    pointer = _pointer(gitdir / "commondir")
    if pointer:
        common = (gitdir / pointer.strip()).resolve()
    if not (common.is_relative_to(root) or common.is_relative_to(home)):
        return None
    return gitdir, common


def _git_files(root: Path) -> Iterable[Path]:
    """Observe metadata only; never objects, logs, hooks or remote credentials."""
    dotgit = root / ".git"
    if dotgit.is_file() and not dotgit.is_symlink():
        yield dotgit
    locations = _git_locations(root)
    if locations is None:
        return
    gitdir, common = locations
    for path in (gitdir / "HEAD", gitdir / "commondir", common / "config", common / "packed-refs"):
        if not any(part.is_symlink() for part in (path, *path.parents)) and path.is_file():
            yield path
    refs = common / "refs"
    if refs.is_dir() and not refs.is_symlink():
        yield from _bounded_files(refs)


def design_files(root: Path) -> Iterable[Path]:
    seen = 0
    for path in _bounded_files(root):
        name = path.name.lower()
        if not (
            path.suffix.lower() in DESIGN_SUFFIXES | SOURCE_SUFFIXES
            or name in DEPENDENCY_NAMES
            or (name.startswith("requirements") and name.endswith(".txt"))
        ):
            continue
        yield path
        seen += 1
        if seen >= MAX_FILES:
            logger.warning("workspace fingerprint truncated at %d files", MAX_FILES)
            return


def fingerprint(root: Path | None) -> str:
    """One digest over (relative path, size, mtime_ns) of every design file.

    Saved source/design files and Git metadata are stat-only; the two worktree
    pointer files alone are read (at most 4 KiB each) to locate metadata. No file
    contents enter the payload-free change frame.

    Returns "" for CANNOT OBSERVE (no workspace, not a directory, unreadable),
    deliberately distinct from the digest of an empty workspace. Same principle
    as the cloud's no-signal codes: not being able to look is not the same as
    seeing nothing, and a caller must never read it as a change.
    """
    if root is None or not root.is_dir():
        return ""
    digest = hashlib.blake2b(digest_size=16)
    try:
        root = root.resolve()
        for index, path in enumerate(sorted((*design_files(root), *_git_files(root)))):
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else f"git:{index}"
            digest.update(f"{rel}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    except (OSError, ValueError, RuntimeError):
        logger.warning("could not read workspace %s for fingerprinting", root)
        return ""
    return digest.hexdigest()


def workspace_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def workspace_from_env() -> Path | None:
    return workspace_path(os.environ.get("SOLUS_COMPANION_WORKSPACE"))
