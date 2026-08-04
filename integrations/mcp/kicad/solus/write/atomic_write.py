"""Atomic file replacement for `set_symbol_property` (T2b).

A temp file is created in the SAME directory as the destination (so the
final rename is on one filesystem — atomic), fsync'd before the rename, then
moved into place with `os.replace`. Never touches the destination path
itself except at that final, atomic step: any failure before it leaves the
destination byte-for-byte as it was, and the temp file is cleaned up rather
than left behind.
"""

import os
import tempfile
from pathlib import Path


def atomic_write(destination: Path, data: bytes) -> None:
    """Write *data* to *destination* atomically. Raises the underlying OS
    exception on failure; the destination is left untouched either way, and
    the temp file never survives a failed attempt."""
    directory = destination.parent
    descriptor, temp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{destination.name}.", suffix=".solus-write.tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
