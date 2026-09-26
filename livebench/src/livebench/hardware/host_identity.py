"""Read this host's existing companion identity; never initialize private state."""

import os
import re
import stat
from pathlib import Path


def read_host_identity(*, home: Path | None = None) -> str | None:
    path = (home or Path.home()) / ".solus" / "companion_id"
    descriptor: int | None = None
    try:
        if path.resolve(strict=True) != path:
            return None
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64:
            return None
        raw = os.read(descriptor, 65)
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            return None
        identity = raw.decode("ascii").strip()
        return identity if re.fullmatch(r"[0-9a-f]{32}", identity) else None
    except (OSError, UnicodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
