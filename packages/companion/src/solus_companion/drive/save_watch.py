"""The drive step's saved-file watch (docs/architecture/sol-drive.md §2.2, §3).

KiCad (project-bound) keeps the design-file watch over the whole workspace. A
window-bound app whose document lies in the workspace gets every regular file
under that document's folder; otherwise nothing is watched. A fingerprint of
"" means "cannot observe" and counts as a change, so the step stops.
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from solus_companion.watch import (
    ARTIFACT_DIR_NAME,
    AUTOSAVE_PREFIX,
    HISTORY_DIR_NAME,
    MAX_ENTRIES,
    saved_design_fingerprint,
)

logger = logging.getLogger("solus.companion.drive")

#: Same exclusions as the design watch (§3): bulk folders, KiCad's timed writes, exports.
_SKIP_DIRS = frozenset({".git", "node_modules", HISTORY_DIR_NAME, ARTIFACT_DIR_NAME})
_DOCUMENT_DIR_CAP = 4096

DESIGN_SAVED = "a design file in this project changed; SOL stopped"
FILE_CHANGED = "a file in this project changed; SOL stopped"


def document_folder(workspace: Path, document_dir: Any) -> Path | None:
    """`<workspace>/<documentDir>` when it is a relative path that resolves to an
    existing folder inside the workspace; None (watch off) for anything else."""
    if not isinstance(document_dir, str) or len(document_dir) > _DOCUMENT_DIR_CAP:
        return None
    relative = PurePosixPath(document_dir)
    if "\x00" in document_dir or relative.is_absolute() or ".." in relative.parts:
        return None
    root = workspace.resolve()
    try:
        folder = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not folder.is_dir() or not folder.is_relative_to(root):
        return None
    return folder


def _regular_files(root: Path) -> list[Path] | None:
    """Every regular file under `root` (file symlinks by their target); None when
    there are more than MAX_ENTRIES entries to look at."""
    found: list[Path] = []
    pending = [root]
    remaining = MAX_ENTRIES
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                remaining -= 1
                if remaining < 0:
                    return None
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIRS:
                        pending.append(Path(entry.path))
                elif entry.is_file() and not entry.name.startswith(AUTOSAVE_PREFIX):
                    found.append(Path(entry.path))
    return found


def folder_fingerprint(root: Path) -> str:
    """One digest over size + mtime of every regular file under `root`; "" when it
    cannot be observed whole."""
    if not root.is_dir():
        return ""
    digest = hashlib.blake2b(digest_size=16)
    try:
        files = _regular_files(root)
        if files is None:
            logger.warning("document folder is too big for the saved-file check")
            return ""
        for path in sorted(files):
            try:
                stat = path.stat()
                mark = f"{stat.st_size}:{stat.st_mtime_ns}"
            except OSError:
                mark = "unreadable"
            digest.update(f"{path.relative_to(root).as_posix()}:{mark}\n".encode())
    except (OSError, ValueError, RuntimeError):
        logger.warning("could not read the document folder for the saved-file check")
        return ""
    return digest.hexdigest()


@dataclass(frozen=True)
class SaveWatch:
    """A baseline taken at the step's identify; `changed()` compares against it."""

    root: Path
    every_file: bool
    baseline: str

    @classmethod
    def take(cls, root: Path, *, every_file: bool) -> "SaveWatch":
        return cls(root, every_file, _read(root, every_file=every_file))

    @property
    def stop_message(self) -> str:
        return FILE_CHANGED if self.every_file else DESIGN_SAVED

    def changed(self) -> bool:
        now = _read(self.root, every_file=self.every_file)
        return not now or now != self.baseline


def _read(root: Path, *, every_file: bool) -> str:
    return folder_fingerprint(root) if every_file else saved_design_fingerprint(root)
