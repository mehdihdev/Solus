"""SOLUSDEV-317 — descendant-tree kills: processes that leave the command's process
group (setsid) are tracked from process-table snapshots and killed on stop,
timeout, shutdown and after a one-shot command's leader exits. Linux makes the
server a child subreaper so orphans stay in the tree."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from code_paths import overlay_module  # isort: skip

process_os = overlay_module("process_os")
execute = overlay_module("execute")
server = overlay_module("server")


def test_descendants_walk_parent_pids() -> None:
    table = {10: 1, 11: 10, 12: 11, 13: 1, 14: 12, 20: 99}
    assert sorted(process_os.descendants(10, table)) == [11, 12, 14]
    assert process_os.descendants(99, table) == [20]
    assert process_os.descendants(42, table) == []


def test_tracker_kills_escaped_descendants_but_not_recycled_pids() -> None:
    tables = [
        {100: 1, 101: 100, 102: 101},  # snapshot while the leader runs
        {101: 1, 102: 101, 103: 555},  # leader gone; 101 orphaned; 103 unrelated
    ]
    killed: list[tuple[int, int]] = []
    tracker = process_os.TreeTracker(
        100, table=lambda: tables.pop(0), kill=lambda pid, sig: killed.append((pid, sig))
    )
    tracker.observe()
    tracker.kill(signal.SIGKILL)
    assert killed == [(101, signal.SIGKILL), (102, signal.SIGKILL)]


def test_tracker_skips_a_seen_pid_now_owned_by_a_stranger() -> None:
    tables = [{100: 1, 101: 100}, {101: 4242}]
    killed: list[int] = []
    tracker = process_os.TreeTracker(
        100, table=lambda: tables.pop(0), kill=lambda pid, sig: killed.append(pid)
    )
    tracker.observe()
    tracker.kill(signal.SIGTERM)
    assert killed == []


def test_process_table_contains_this_process() -> None:
    table = process_os.process_table()
    assert table.get(os.getpid()) == os.getppid()


def test_subreaper_is_requested_on_linux_only() -> None:
    calls: list[tuple[int, int]] = []
    process_os.become_subreaper("linux", prctl=lambda option, value: calls.append((option, value)))
    assert calls == [(36, 1)]
    process_os.become_subreaper("darwin", prctl=lambda option, value: calls.append((option, value)))
    assert calls == [(36, 1)]


def _state(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat")
    if stat.parent.parent.is_dir() and Path("/proc/self").is_dir():
        try:
            return stat.read_text().rpartition(")")[2].split()[0]
        except (OSError, IndexError):
            return ""
    return subprocess.run(
        ["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()


def _gone(pid: int) -> bool:
    for _ in range(60):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        state = _state(pid)
        if state.startswith("Z") or not state:
            return True
        time.sleep(0.1)
    return False


def test_one_shot_command_cannot_leave_a_setsid_descendant(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys, time\n"
        f"c = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)'],"
        " start_new_session=True)\n"
        "print(c.pid, flush=True)\n"
        "time.sleep(1.5)\n"
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    outcome = execute.default_runner([sys.executable, "-c", code], tmp_path, env, 30)
    escaped = int(outcome.stdout.split()[0])
    try:
        assert _gone(escaped), "a setsid descendant outlived the command"
    finally:
        try:
            os.kill(escaped, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_main_requests_the_subreaper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(server, "become_subreaper", lambda: calls.append("subreaper"))
    monkeypatch.setattr(server, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(server, "_reap_orphans", lambda: None)

    class FakeServer:
        def run(self, transport: str) -> None:
            calls.append("run")

    monkeypatch.setattr(server, "build_server", lambda: FakeServer())
    server.main()
    assert calls == ["subreaper", "run"]
