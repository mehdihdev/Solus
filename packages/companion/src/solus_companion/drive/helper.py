"""Run the pinned `solus-input` helper (docs/architecture/sol-drive.md §2–3).

The helper enforces the drive policy; this module makes sure we run the RIGHT
binary the RIGHT way: an absolute, regular, executable path with no symlink
and no group/other-writable file or directory on the way to it, re-checked
before every run; an argument list (never a shell); a minimal environment; one
deadline for the whole run; SIGTERM first (the helper releases a held mouse
button on it), then SIGKILL; a stdout cap; exactly one JSON object back.
"""

import asyncio
import contextlib
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: A capture is a base64 PNG of at most 2048 px on its long edge (1568 by
#: default). Even an incompressible 2048² RGBA image (~22 MB as base64) fits;
#: the cap bounds a hostile or broken helper.
STDOUT_CAP_BYTES = 24 * 1024 * 1024
#: How long a terminated helper gets to release a held button and exit.
TERMINATE_GRACE_SECONDS = 1.0
_READ_CHUNK = 64 * 1024
#: The child sees nothing of the companion's environment (tokens, secrets).
_CHILD_ENV = {"PATH": "/usr/bin:/bin"}


class DriveHelperError(Exception):
    """A helper run that produced no trustworthy answer. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def resolve_helper(path_text: str | None) -> Path | None:
    """The helper path, or None when it is not an absolute executable regular file.

    Never PATH-resolved and never a symlink: the desktop app passes the packaged
    binary's absolute path, and anything else is treated as "no helper"."""
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        return None
    try:
        info = path.lstat()
        if path.resolve(strict=True) != path:  # a symlink anywhere on the path
            return None
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        return None
    if _file_replaceable(info) or any(_ancestor_replaceable(d.stat()) for d in path.parents):
        return None
    return path


def _file_replaceable(info: os.stat_result) -> bool:
    """The helper itself: never group- or other-writable."""
    return bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _ancestor_replaceable(info: os.stat_result) -> bool:
    """A directory above the helper lets someone else swap our entry.

    Sticky: no (others can't replace an entry they don't own). Other-writable:
    yes. Group-writable: only safe when root owns it — /Applications is
    drwxrwxr-x root:admin, and an admin can already replace anything there."""
    if bool(info.st_mode & stat.S_ISVTX):
        return False
    if info.st_mode & stat.S_IWOTH:
        return True
    return bool(info.st_mode & stat.S_IWGRP) and info.st_uid != 0


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await stream.read(_READ_CHUNK):
        size += len(chunk)
        if size > cap:
            raise DriveHelperError("helper_output", f"more than {cap} bytes of output")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(raw: bytes) -> dict[str, Any]:
    # Split on b"\n" only: str.splitlines() would also split on U+2028 / U+0085
    # inside a JSON string (a window title), which JSONSerialization leaves raw.
    lines = [line for line in raw.split(b"\n") if line.strip()]
    if len(lines) != 1:
        raise DriveHelperError("helper_output", "expected exactly one JSON line")
    try:
        value = json.loads(lines[0].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DriveHelperError("helper_output", "not JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
        raise DriveHelperError("helper_output", "missing the ok flag")
    return value


class DriveHelper:
    def __init__(
        self,
        path: Path,
        *,
        timeouts: dict[str, float] | None = None,
        stdout_cap: int = STDOUT_CAP_BYTES,
    ) -> None:
        self.path = path
        self.timeouts = timeouts or {}
        self.stdout_cap = stdout_cap

    def timeout_for(self, command: str, default: float) -> float:
        return self.timeouts.get(command, default)

    async def run(self, args: Sequence[str], *, timeout: float) -> dict[str, Any]:
        """One helper call: `args` WITHOUT the program. Raises DriveHelperError."""
        if resolve_helper(str(self.path)) != self.path:
            raise DriveHelperError("helper_missing", "the input helper changed or is gone")
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self.path),
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=dict(_CHILD_ENV),
            )
        except (OSError, ValueError) as exc:
            raise DriveHelperError("helper_spawn", type(exc).__name__) from exc
        assert proc.stdout is not None  # stdout=PIPE above
        finished = False
        try:
            async with asyncio.timeout(timeout):  # ONE deadline: reading and exiting
                raw = await _read_capped(proc.stdout, self.stdout_cap)
                code = await proc.wait()
            finished = True
        except TimeoutError as exc:
            raise DriveHelperError("helper_timeout", f"no answer within {timeout:g}s") from exc
        finally:
            # Any early exit — timeout, cap, cancellation (Stop, a dropped
            # bridge) — ends the helper; it must never keep posting events.
            if not finished:
                await _stop(proc)
        if code != 0:
            raise DriveHelperError("helper_crashed", f"exited with status {code}")
        return _parse(raw)


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM, a short grace to release a held button, then SIGKILL. Shielded:
    it must finish even while the calling task is being cancelled."""

    async def stop() -> None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), TERMINATE_GRACE_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()

        # Drain to EOF so the pipe transport closes (bounded: the process is gone).
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.communicate(), TERMINATE_GRACE_SECONDS)

    await asyncio.shield(stop())
