"""Private API runtime identity, held under an OS lock for the process lifetime."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import uuid
from pathlib import Path


class RuntimeOwnershipError(Exception):
    """Ownership is unavailable; native paths never become API errors."""


def _lock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _directory(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeOwnershipError("Local runtime ownership is unavailable")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise RuntimeOwnershipError("Local runtime ownership is unavailable")
    path.chmod(0o700)


class RuntimeOwner:
    """No filesystem work before acquire; no UUID is trusted without its lifetime lock."""

    def __init__(self, *, home: Path | None = None, location: Path | None = None) -> None:
        self.home = home
        self.location = location or Path(__file__).resolve().parents[5]
        self.path: Path | None = None
        self.identity: str | None = None
        self._fd: int | None = None

    def acquire(self) -> str:
        if self._fd is not None and self.identity is not None:
            return self.identity
        fd: int | None = None
        try:
            home = self.home if self.home is not None else Path.home()
            root = home / ".solus"
            _directory(root)
            runtimes = root / "api-runtimes"
            _directory(runtimes)
            scope = hashlib.sha256(str(self.location.resolve()).encode()).hexdigest()
            directory = runtimes / scope
            _directory(directory)
            self.path = directory / "owner"
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            created = False
            try:
                fd = os.open(self.path, flags | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
            except FileExistsError:
                if self.path.is_symlink():
                    raise RuntimeOwnershipError("Local runtime ownership is unavailable") from None
                fd = os.open(self.path, flags)
            info = os.fstat(fd)
            named = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
                named.st_dev,
                named.st_ino,
            ):
                raise RuntimeOwnershipError("Local runtime ownership is unavailable")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise RuntimeOwnershipError("Local runtime ownership is unavailable")
            _lock(fd)
            raw = os.read(fd, 129)
            if created and not raw:
                identity = str(uuid.uuid4())
                os.write(fd, (identity + "\n").encode("ascii"))
                os.fsync(fd)
            else:
                identity = raw.decode("ascii").strip()
                if len(raw) > 128 or str(uuid.UUID(identity)) != identity:
                    raise RuntimeOwnershipError("Local runtime ownership is unavailable")
            self._fd, self.identity = fd, identity
            return identity
        except (OSError, ValueError, UnicodeError, RuntimeOwnershipError):
            if fd is not None:
                os.close(fd)
            raise RuntimeOwnershipError("Local runtime ownership is unavailable") from None

    def close(self) -> None:
        fd, self._fd = self._fd, None
        self.identity = None
        if fd is not None:
            os.close(fd)
