"""The one place the motion tools shell out: ffmpeg, resolved once to an absolute path."""

from __future__ import annotations

import shutil
import subprocess

_found = shutil.which("ffmpeg")
if _found is None:
    raise SystemExit("ffmpeg not found on PATH (brew install ffmpeg)")
FFMPEG: str = _found


def ffmpeg(*args: str) -> bytes:
    """Run ffmpeg with an argument list (never a shell) and return stdout."""
    done = subprocess.run(  # noqa: S603 — pinned binary, argv list built by our own scripts
        [FFMPEG, "-loglevel", "error", *args], check=True, capture_output=True
    )
    return done.stdout
