"""The Python forks of an integrations root: directories with an
`allowlist.yaml` and a shipped `requirements.lock.txt` (§1). A lock that
resolves outside the root is ignored — its bytes decide what pip installs."""

import logging
from dataclasses import dataclass
from pathlib import Path

from solus_companion.platforms import unavailable_reason
from solus_companion.runtime.roots import is_fork_name

logger = logging.getLogger("solus.companion.runtime")

LOCK_NAME = "requirements.lock.txt"


@dataclass(frozen=True)
class ForkInfo:
    name: str
    directory: Path
    lock: Path
    #: The platform.json refusal, or None when the fork runs on this OS.
    unavailable: str | None


def fork_lock(root_resolved: Path, fork_dir: Path) -> Path | None:
    """The fork's lock, resolved, if it exists as a file inside the root."""
    lock = fork_dir / LOCK_NAME
    if not (lock.exists() or lock.is_symlink()):
        return None
    resolved = lock.resolve()
    if not resolved.is_relative_to(root_resolved) or not resolved.is_file():
        logger.error("ignoring %s lock: it resolves outside the integrations root", fork_dir.name)
        return None
    return resolved


def python_forks(integrations_root: Path, platform: str) -> list[ForkInfo]:
    if not integrations_root.is_dir():
        return []
    root = integrations_root.resolve()
    forks: list[ForkInfo] = []
    for allowlist in sorted(integrations_root.glob("*/allowlist.yaml")):
        directory = allowlist.parent
        if not is_fork_name(directory.name):
            continue
        lock = fork_lock(root, directory)
        if lock is None:
            continue
        forks.append(
            ForkInfo(
                name=directory.name,
                directory=directory,
                lock=lock,
                unavailable=unavailable_reason(root, directory, platform),
            )
        )
    return forks
