"""The `solus-input` agent client (docs/architecture/sol-drive.md §2.1, §3; slice 3b).

The helper runs as a launchd agent serving a Unix socket; it enforces the drive
policy and checks that the peer is the signed companion. This module talks to
it: the socket path and session token arrive from the desktop over stdin
(`DriveSessions.offer`, strictly validated), and each call is one connection —
one `run` request line, ONE line back under one deadline and a 24 MiB cap,
then close. Any early exit (timeout, cap, cancellation) closes the connection,
which stops the helper. Exactly one JSON object comes back or it is an error.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solus_companion.drive.outline import Emit

logger = logging.getLogger("solus.companion.drive")

#: A capture is a base64 PNG of at most 2048 px on its long edge (1568 by
#: default). Even an incompressible 2048² RGBA image (~22 MB as base64) fits;
#: the cap bounds a hostile or broken agent.
STDOUT_CAP_BYTES = 24 * 1024 * 1024
_READ_CHUNK = 64 * 1024
#: 32 random bytes, base64url without padding.
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_SESSION_KEYS = frozenset({"type", "socket", "token"})
_MAX_SOCKET_PATH = 1024
#: How often a bad token may ask the desktop for a fresh session.
SESSION_NEEDED_INTERVAL = 5.0
SESSION_NEEDED_LINE = '{"type":"drive_session_needed"}'


class DriveHelperError(Exception):
    """A helper call that produced no trustworthy answer. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DriveSession:
    socket: Path
    token: str = field(repr=False)  # never in a log or a repr


def socket_is_safe(path: Path) -> bool:
    """Absolute, no symlink anywhere, the directory this user's and exactly 0700,
    the socket a socket owned by this user."""
    if not path.is_absolute() or os.path.realpath(path) != str(path):
        return False
    uid = os.getuid()
    try:
        folder = os.lstat(path.parent)
        sock = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISDIR(folder.st_mode) or folder.st_uid != uid:
        return False
    if stat.S_IMODE(folder.st_mode) != 0o700:
        return False
    return stat.S_ISSOCK(sock.st_mode) and sock.st_uid == uid


def _session_from(message: Mapping[str, Any]) -> tuple[DriveSession | None, str]:
    """The session a control line carries, or None and why (never the token)."""
    if set(message) != _SESSION_KEYS:
        return None, "unexpected or missing fields"
    socket_text, token = message.get("socket"), message.get("token")
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        return None, "malformed token"
    if (
        not isinstance(socket_text, str)
        or not socket_text
        or len(socket_text) > _MAX_SOCKET_PATH
        or "\x00" in socket_text
    ):
        return None, "malformed socket path"
    path = Path(socket_text)
    if not socket_is_safe(path):
        return None, "socket path is not private to this user"
    return DriveSession(path, token), ""


class DriveSessions:
    """The current agent session, fed by `{"type":"drive_session",…}` stdin lines.
    A bad line is dropped with a warning and keeps the previous session."""

    def __init__(self) -> None:
        self._current: DriveSession | None = None

    def current(self) -> DriveSession | None:
        return self._current

    def offer(self, message: Mapping[str, Any]) -> bool:
        session, why = _session_from(message)
        if session is None:
            logger.warning("ignored drive_session line: %s", why)
            return False
        self._current = session
        logger.info("drive session updated via stdin")
        return True


async def _read_line(reader: asyncio.StreamReader, cap: int) -> bytes:
    """Bytes up to the first newline (or EOF); anything after it is an error."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await reader.read(_READ_CHUNK):
        chunks.append(chunk)
        size += len(chunk)
        if size > cap:
            raise DriveHelperError("helper_output", f"more than {cap} bytes of output")
        if b"\n" in chunk:
            break
    line, _, rest = b"".join(chunks).partition(b"\n")
    if rest.strip():
        raise DriveHelperError("helper_output", "expected exactly one JSON line")
    return line


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
        sessions: DriveSessions,
        *,
        timeouts: dict[str, float] | None = None,
        stdout_cap: int = STDOUT_CAP_BYTES,
        emit: Emit | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sessions = sessions
        self.timeouts = timeouts or {}
        self.stdout_cap = stdout_cap
        self._emit = emit
        self._clock = clock
        self._last_needed: float | None = None

    def timeout_for(self, command: str, default: float) -> float:
        return self.timeouts.get(command, default)

    async def run(self, args: Sequence[str], *, timeout: float) -> dict[str, Any]:
        """One `run` request for `args`. Raises DriveHelperError."""
        session = self.sessions.current()
        if session is None:
            raise DriveHelperError("agent_unavailable", "no session with the input helper yet")
        if not socket_is_safe(session.socket):
            raise DriveHelperError("agent_unavailable", "the input helper's socket is not safe")
        request = {"v": 1, "op": "run", "token": session.token, "argv": list(args)}
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(timeout):  # ONE deadline: connect, write, read
                try:
                    reader, writer = await asyncio.open_unix_connection(str(session.socket))
                except OSError as exc:
                    raise DriveHelperError(
                        "agent_unavailable", f"cannot reach the input helper ({type(exc).__name__})"
                    ) from exc
                writer.write(json.dumps(request).encode() + b"\n")
                await writer.drain()
                raw = await _read_line(reader, self.stdout_cap)
        except TimeoutError as exc:
            raise DriveHelperError("helper_timeout", f"no answer within {timeout:g}s") from exc
        except (ConnectionError, BrokenPipeError) as exc:
            raise DriveHelperError("agent_unavailable", "the input helper hung up") from exc
        finally:
            # Any early exit — timeout, cap, cancellation (Stop, a dropped
            # bridge) — closes the connection: that stops the helper.
            if writer is not None:
                writer.close()
                with contextlib.suppress(Exception):
                    await asyncio.shield(writer.wait_closed())
        reply = _parse(raw)
        if reply.get("ok") is False and reply.get("code") == "bad_token":
            self._ask_for_session()
        return reply

    def _ask_for_session(self) -> None:
        now = self._clock()
        if self._last_needed is not None and now - self._last_needed < SESSION_NEEDED_INTERVAL:
            return
        self._last_needed = now
        if self._emit is not None:
            self._emit(SESSION_NEEDED_LINE)
