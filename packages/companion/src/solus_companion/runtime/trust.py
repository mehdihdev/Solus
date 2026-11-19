"""The discovery-time trust rule — mcp-fork-runtime.md §5.

A fork with a `requirements.lock.txt` launches only from a private env that
passes every check, evaluated in the doc's order; the first failure becomes
the `not_launched` detail. Nothing here writes."""

import os
from dataclasses import dataclass
from pathlib import Path

from solus_companion.runtime.errors import DetailCode
from solus_companion.runtime.ownership import OwnerOnly
from solus_companion.runtime.roots import env_interpreter
from solus_companion.runtime.stamp import STAMP_NAME, Stamp, lock_sha256, read_stamp


@dataclass(frozen=True)
class TrustResult:
    detail: DetailCode | None
    interpreter: Path | None = None
    stamp: Stamp | None = None

    @property
    def ready(self) -> bool:
        return self.detail is None


def _executable(path: Path, platform: str) -> bool:
    if platform == "win32":
        return path.suffix.lower() == ".exe"
    return os.access(path, os.X_OK)


def _stamp_matches(stamp: Stamp, fork: str, lock: Path) -> bool:
    if stamp.fork != fork:
        return False
    try:
        return stamp.lock_sha256 == lock_sha256(lock)
    except OSError:
        return False


def evaluate_trust(
    fork: str, lock: Path, envs_root: Path, *, platform: str, policy: OwnerOnly
) -> TrustResult:
    env_dir = envs_root / fork
    interpreter = env_interpreter(env_dir, platform)
    stamp_path = env_dir / STAMP_NAME
    present = interpreter.exists() or interpreter.is_symlink()
    if not (env_dir.is_dir() and present and stamp_path.is_file()):
        return TrustResult("needs_setup:no_env")
    if not (policy.check(envs_root) and policy.check(env_dir)):
        return TrustResult("needs_setup:not_owner_only")
    stamp = read_stamp(stamp_path)
    if stamp is None or not _stamp_matches(stamp, fork, lock):
        return TrustResult("needs_setup:stamp_mismatch")
    resolved = interpreter.resolve()
    inside = resolved.is_relative_to(env_dir.resolve())
    if not (inside and resolved.is_file() and _executable(resolved, platform)):
        return TrustResult("needs_setup:no_env")
    if not Path(stamp.base.path).exists():
        return TrustResult("needs_setup:base_missing")
    return TrustResult(None, resolved, stamp)
