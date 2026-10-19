"""OS seams of the process registry: spawning, group signals and start tokens
(docs/api/code-command-execution.md §2.3). Injected by tests; never PR_SET_PDEATHSIG."""

import ctypes
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Protocol

from .sandbox import PASS_FDS

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
        pass_fds=PASS_FDS.get(),
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


PR_SET_CHILD_SUBREAPER = 36


def _proc_table() -> dict[int, int]:
    table: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as handle:
                fields = handle.read().rpartition(")")[2].split()
            table[int(entry)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    return table


def process_table() -> dict[int, int]:
    """pid → parent pid for every visible process ({} when unavailable)."""
    if os.path.isdir("/proc/self"):
        return _proc_table()
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, argv only
            [PS, "-A", "-o", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = int(parts[1])
    return table


def descendants(leader: int, table: Mapping[int, int]) -> list[int]:
    """Every pid whose parent chain reaches `leader` (breadth first)."""
    children: dict[int, list[int]] = {}
    for pid, parent in table.items():
        children.setdefault(parent, []).append(pid)
    found: list[int] = []
    queue = list(children.get(leader, []))
    while queue:
        pid = queue.pop(0)
        if pid in found or pid == leader:
            continue
        found.append(pid)
        queue.extend(children.get(pid, []))
    return found


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class TreeTracker:
    """Descendants of one leader, accumulated from process-table snapshots, so the
    ones that left its process group (setsid) can still be killed. A pid seen earlier
    is only signalled while its parent is still the tree, init or this server
    (recycled pids are left alone)."""

    def __init__(
        self,
        leader: int,
        *,
        table: Callable[[], Mapping[int, int]] = process_table,
        kill: Callable[[int, int], None] = _signal,
    ) -> None:
        self.leader = leader
        self._table = table
        self._kill = kill
        self.seen: set[int] = set()

    def observe(self) -> None:
        self.seen.update(descendants(self.leader, self._table()))

    def kill(self, sig: int) -> None:
        if not self.seen:
            return
        table = self._table()
        owners = {self.leader, 1, os.getpid(), *self.seen}
        for pid in sorted(self.seen):
            if pid in table and table[pid] in owners:
                self._kill(pid, sig)


def become_subreaper(
    platform: str = sys.platform, *, prctl: Callable[[int, int], object] | None = None
) -> None:
    """Linux: orphaned descendants reparent to this server and stay in its tree."""
    if not platform.startswith("linux"):
        return
    if prctl is None:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
    try:
        prctl(PR_SET_CHILD_SUBREAPER, 1)
    except (OSError, AttributeError):
        return
