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


def design_files(root: Path) -> Iterable[Path]:
    seen = 0
    for path in sorted(root.rglob("*")):
        if seen >= MAX_FILES:
            logger.warning("workspace fingerprint truncated at %d files", MAX_FILES)
            return
        if ARTIFACT_DIR_NAME in path.parts:
            continue
        if path.suffix.lower() not in DESIGN_SUFFIXES:
            continue
        if not path.is_file():
            continue
        seen += 1
        yield path


def fingerprint(root: Path | None) -> str:
    """One digest over (relative path, size, mtime_ns) of every design file.

    `stat()` only — never opens a file, so it costs the same on a 2 MB schematic
    as on an empty one, and cannot become a channel for file CONTENT to reach a
    frame.

    Returns "" for CANNOT OBSERVE (no workspace, not a directory, unreadable),
    deliberately distinct from the digest of an empty workspace. Same principle
    as the cloud's no-signal codes: not being able to look is not the same as
    seeing nothing, and a caller must never read it as a change.
    """
    if root is None or not root.is_dir():
        return ""
    digest = hashlib.blake2b(digest_size=16)
    try:
        for path in design_files(root):
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            digest.update(f"{rel}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    except OSError:
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
