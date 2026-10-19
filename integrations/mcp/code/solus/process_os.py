"""OS seams of the process registry: spawning, group signals and start tokens
(docs/api/code-command-execution.md §2.3). Injected by tests; never PR_SET_PDEATHSIG."""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import IO, Protocol

PS = "/bin/ps"


class Child(Protocol):
    pid: int
    stdout: IO[bytes] | None
    stderr: IO[bytes] | None

    def poll(self) -> int | None: ...


Spawn = Callable[[list[str], Path, dict[str, str]], Child]


def default_spawn(argv: list[str], cwd: Path, env: dict[str, str]) -> Child:
    return subprocess.Popen(  # noqa: S603 - planned, sandboxed argv; no shell
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )


def default_killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # gone, or (macOS) only zombies left in the group


def start_token(pid: int) -> str | None:
    """When `pid` started, as the OS reports it (None when it is not running)."""
    proc = Path(f"/proc/{pid}/stat")
    if proc.exists():
        try:
            fields = proc.read_text().rpartition(")")[2].split()
            return fields[19]
        except (OSError, IndexError):
            return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, argv only
            [PS, "-o", "lstart=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    token = result.stdout.strip()
    return token if result.returncode == 0 and token else None
