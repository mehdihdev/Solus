"""Blocking-safe reads of files a workspace (or a sandboxed command) may control.

A named pipe planted where a file is expected would block a plain `open()` forever
and hang the server. Every such read opens with `O_NONBLOCK` (and `O_NOFOLLOW`
unless the caller follows symlinks on purpose), then requires a regular file.
"""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_BASE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC


@contextmanager
def open_regular(path: Path | str, *, follow: bool = False) -> Iterator[int | None]:
    """A read descriptor for a regular file at `path`, else None (FIFO, device,
    directory, symlink without `follow`, missing). Closed on exit."""
    flags = _BASE_FLAGS | (0 if follow else os.O_NOFOLLOW)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        yield None
        return
    try:
        yield descriptor if stat.S_ISREG(os.fstat(descriptor).st_mode) else None
    finally:
        os.close(descriptor)


def read_regular(path: Path | str, limit: int, *, follow: bool = False) -> bytes | None:
    """At most `limit` bytes of a regular file, else None. Never blocks, never raises."""
    try:
        with open_regular(path, follow=follow) as descriptor:
            if descriptor is None:
                return None
            chunks: list[bytes] = []
            remaining = limit
            while remaining > 0:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
    except OSError:
        return None
