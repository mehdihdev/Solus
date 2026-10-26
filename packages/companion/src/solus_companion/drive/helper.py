"""Run the pinned `solus-input` helper (docs/architecture/sol-drive.md §2–3).

The helper is the security boundary; this module only makes sure we run the
RIGHT binary the RIGHT way: an absolute, regular, executable, non-symlink path;
an argument list (never a shell); a minimal environment; a timeout that kills;
a stdout cap; exactly one JSON object back.
"""

import asyncio
import contextlib
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: A capture is a base64 PNG of at most 1568 px on its long edge — well under this.
STDOUT_CAP_BYTES = 12 * 1024 * 1024
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
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        return None
    return path


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
    lines = [line for line in raw.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if len(lines) != 1:
        raise DriveHelperError("helper_output", "expected exactly one JSON line")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
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
        proc = await asyncio.create_subprocess_exec(
            str(self.path),
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=dict(_CHILD_ENV),
        )
        assert proc.stdout is not None  # stdout=PIPE above
        try:
            raw = await asyncio.wait_for(_read_capped(proc.stdout, self.stdout_cap), timeout)
            code = await asyncio.wait_for(proc.wait(), timeout)
        except TimeoutError as exc:
            await _kill(proc)
            raise DriveHelperError("helper_timeout", f"no answer within {timeout:g}s") from exc
        except DriveHelperError:
            await _kill(proc)
            raise
        if code != 0:
            raise DriveHelperError("helper_crashed", f"exited with status {code}")
        return _parse(raw)


async def _kill(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()
