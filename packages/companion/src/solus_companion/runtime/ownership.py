"""Owner-only directories — mcp-fork-runtime.md §5.

POSIX: `lstat` not a symlink, a directory, `st_uid == geteuid()`, no group or
other bits. Windows: owner is the current user, DACL protected (inheritance
off) with exactly two allow ACEs, both full control: the current user and
SYSTEM. The Windows decision is a pure function over an `AclSnapshot` so it is
tested everywhere; only the advapi32 reader/writer (winacl.py) is Windows-bound."""

import ctypes
import logging
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from solus_companion.runtime.errors import RuntimeSetupError

logger = logging.getLogger("solus.companion.runtime")

SYSTEM_SID = "S-1-5-18"
#: What the ctypes backend can raise: `_check` → OSError, a bad argument →
#: ctypes.ArgumentError, a malformed SID/string → ValueError.
_ACL_ERRORS: tuple[type[Exception], ...] = (OSError, ctypes.ArgumentError, ValueError)
FILE_ALL_ACCESS = 0x1F01FF


class OwnerOnly(Protocol):
    def check(self, path: Path) -> bool: ...

    def ensure(self, path: Path) -> None:
        """Create `path` (parents normally) and make it owner-only, or raise
        `RuntimeSetupError("not_owner_only")` when that is not possible."""


class PosixOwnerOnly:
    def __init__(self, euid: Callable[[], int] | None = None) -> None:
        self._euid = euid

    def _uid(self) -> int:
        return self._euid() if self._euid is not None else os.geteuid()

    def check(self, path: Path) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return False
        return (
            stat.S_ISDIR(info.st_mode) and info.st_uid == self._uid() and info.st_mode & 0o077 == 0
        )

    def ensure(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self._uid():
            raise RuntimeSetupError("not_owner_only")
        if info.st_mode & 0o077:
            os.chmod(path, 0o700)


@dataclass(frozen=True)
class Ace:
    kind: Literal["allow", "deny", "other"]
    sid: str
    mask: int


@dataclass(frozen=True)
class AclSnapshot:
    owner_sid: str
    protected: bool
    aces: tuple[Ace, ...]


def snapshot_is_owner_only(snapshot: AclSnapshot, user_sid: str) -> bool:
    if snapshot.owner_sid != user_sid or not snapshot.protected or len(snapshot.aces) != 2:
        return False
    full = all(
        ace.kind == "allow" and ace.mask & FILE_ALL_ACCESS == FILE_ALL_ACCESS
        for ace in snapshot.aces
    )
    return full and {ace.sid for ace in snapshot.aces} == {user_sid, SYSTEM_SID}


class AclBackend(Protocol):
    def current_user_sid(self) -> str: ...

    def read(self, path: Path) -> AclSnapshot | None: ...

    def apply(self, path: Path, user_sid: str) -> None: ...


class WindowsOwnerOnly:
    def __init__(self, backend: AclBackend) -> None:
        self._backend = backend

    def check(self, path: Path) -> bool:
        """Fails closed per folder: an ACL read error is "not owner-only" for
        that one fork, never an exception that aborts discovery for all."""
        try:
            if path.is_symlink() or not path.is_dir():
                return False
            snapshot = self._backend.read(path)
            return snapshot is not None and snapshot_is_owner_only(
                snapshot, self._backend.current_user_sid()
            )
        except _ACL_ERRORS as exc:
            logger.warning("owner-only check could not read an ACL: %s", type(exc).__name__)
            return False

    def ensure(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                raise RuntimeSetupError("not_owner_only")
            self._backend.apply(path, self._backend.current_user_sid())
        except _ACL_ERRORS as exc:
            logger.warning("owner-only ensure failed: %s", type(exc).__name__)
            raise RuntimeSetupError("not_owner_only") from exc
        if not self.check(path):
            raise RuntimeSetupError("not_owner_only")


def owner_only_for(platform: str) -> OwnerOnly:
    if platform == "win32":  # pragma: no cover — exercised on Windows only
        from solus_companion.runtime.winacl import Advapi32Backend

        return WindowsOwnerOnly(Advapi32Backend())
    return PosixOwnerOnly()
