"""OS seams of the process registry: spawning, group signals and start tokens
(docs/api/code-command-execution.md §2.3). Injected by tests; never PR_SET_PDEATHSIG."""

import ctypes
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Protocol

from .sandbox import PASS_FDS

PS = "/bin/ps"
PROC = Path("/proc")
BOOT_ID = Path("sys/kernel/random/boot_id")
#: Process-table snapshot interval: `ps -A` is costly on macOS, `/proc` is cheap.
OBSERVE_SECONDS = 1.0 if sys.platform == "darwin" else 0.5


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


def start_token(pid: int, *, proc_root: Path = PROC) -> str | None:
    """When `pid` started, as the OS reports it (None when it is not running or
    unknowable). On Linux the start time (clock ticks since boot) is qualified by the
    boot id, so a token recorded before a reboot never matches afterwards."""
    proc = proc_root / str(int(pid)) / "stat"
    if proc.exists():
        try:
            fields = proc.read_text().rpartition(")")[2].split()
            boot = (proc_root / BOOT_ID).read_text().strip()
            return f"{boot}:{fields[19]}" if boot else None
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
    ones that left its process group (setsid) can still be killed. Each pid's start
    token is recorded when first seen; vanished pids are pruned on every snapshot,
    and a pid is only signalled while its parent is still the tree, init or this
    server AND its start token still matches (recycled pids are left alone)."""

    def __init__(
        self,
        leader: int,
        *,
        table: Callable[[], Mapping[int, int]] = process_table,
        kill: Callable[[int, int], None] = _signal,
        token: Callable[[int], str | None] = start_token,
        clock: Callable[[], float] = time.monotonic,
        interval: float = OBSERVE_SECONDS,
    ) -> None:
        self.leader = leader
        self._table = table
        self._kill = kill
        self._token = token
        self._clock = clock
        self._interval = interval
        self._next = float("-inf")
        self.tokens: dict[int, str | None] = {}

    @property
    def seen(self) -> set[int]:
        return set(self.tokens)

    def _update(self, table: Mapping[int, int]) -> None:
        self.tokens = {pid: token for pid, token in self.tokens.items() if pid in table}
        for pid in descendants(self.leader, table):
            if pid not in self.tokens:
                self.tokens[pid] = self._token(pid)

    def observe(self) -> None:
        """Snapshot the table (at most once per `interval`)."""
        now = self._clock()
        if now < self._next:
            return
        self._next = now + self._interval
        self._update(self._table())

    def kill(self, sig: int) -> None:
        """Signal every tracked descendant still ours, judged on a fresh table."""
        if not self.tokens:
            return
        table = self._table()
        self._update(table)
        owners = {self.leader, 1, os.getpid(), *self.tokens}
        for pid, token in sorted(self.tokens.items()):
            if token is None or table.get(pid) not in owners:
                continue
            if self._token(pid) == token:
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
