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
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

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
        100,
        table=lambda: tables.pop(0),
        kill=lambda pid, sig: killed.append((pid, sig)),
        token=lambda pid: f"t{pid}",
    )
    tracker.observe()
    tracker.kill(signal.SIGKILL)
    assert killed == [(101, signal.SIGKILL), (102, signal.SIGKILL)]


def test_tracker_skips_a_seen_pid_now_owned_by_a_stranger() -> None:
    tables = [{100: 1, 101: 100}, {101: 4242}]
    killed: list[int] = []
    tracker = process_os.TreeTracker(
        100,
        table=lambda: tables.pop(0),
        kill=lambda pid, sig: killed.append(pid),
        token=lambda pid: f"t{pid}",
    )
    tracker.observe()
    tracker.kill(signal.SIGTERM)
    assert killed == []


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_tracker_prunes_vanished_pids_on_every_observe() -> None:
    """§9.13: a pid that vanished is forgotten, so a later process reusing it is
    never mistaken for a descendant."""
    tables = [{100: 1, 101: 100, 102: 100}, {100: 1, 101: 100}]
    clock = Clock()
    tracker = process_os.TreeTracker(
        100, table=lambda: tables.pop(0), kill=lambda *_: None, token=str, clock=clock
    )
    tracker.observe()
    assert tracker.seen == {101, 102}
    clock.now += 5
    tracker.observe()
    assert tracker.seen == {101}


def test_tracker_signals_only_while_the_start_token_still_matches() -> None:
    """A pid recycled by an unrelated process (same pid, parent init) has a new start
    token and is left alone."""
    tables = [{100: 1, 101: 100, 102: 100}, {101: 1, 102: 1}]
    tokens = {101: "a", 102: "b"}
    killed: list[int] = []
    tracker = process_os.TreeTracker(
        100,
        table=lambda: tables.pop(0),
        kill=lambda pid, _sig: killed.append(pid),
        token=lambda pid: tokens.get(pid),
    )
    tracker.observe()
    tokens[102] = "recycled"
    tracker.kill(signal.SIGKILL)
    assert killed == [101]


def test_tracker_observe_is_rate_limited_and_kill_reads_a_fresh_table() -> None:
    reads: list[int] = []
    clock = Clock()

    def table() -> dict[int, int]:
        reads.append(1)
        return {100: 1, 101: 100}

    killed: list[int] = []
    tracker = process_os.TreeTracker(
        100,
        table=table,
        kill=lambda pid, _sig: killed.append(pid),
        token=str,
        clock=clock,
        interval=1.0,
    )
    tracker.observe()
    clock.now += 0.5
    tracker.observe()
    assert len(reads) == 1
    clock.now += 0.6
    tracker.observe()
    assert len(reads) == 2
    tracker.kill(signal.SIGTERM)
    assert len(reads) == 3 and killed == [101]


def test_forced_observe_bypasses_the_rate_limit() -> None:
    reads: list[int] = []
    clock = Clock()

    def table() -> dict[int, int]:
        reads.append(1)
        return {100: 1, 101: 100}

    tracker = process_os.TreeTracker(
        100, table=table, kill=lambda *_: None, token=str, clock=clock, interval=10.0
    )
    tracker.observe()
    tracker.observe(force=True)
    assert len(reads) == 2


def test_unknown_token_is_retried_and_a_live_descendant_is_still_signalled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A None token means "not yet known": retried on later observes; at kill time a
    pid still in the tree's parent chain is signalled even without a token, while a
    tokenless pid that left the chain is skipped (and logged)."""
    tables = [
        {100: 1, 101: 100, 102: 100},
        {100: 1, 101: 100, 102: 100},
        {100: 1, 101: 100, 102: 1},
    ]
    tokens: dict[int, str | None] = {101: None, 102: None}
    clock = Clock()
    killed: list[int] = []
    tracker = process_os.TreeTracker(
        100,
        table=lambda: tables.pop(0),
        kill=lambda pid, _sig: killed.append(pid),
        token=lambda pid: tokens.get(pid),
        clock=clock,
    )
    tracker.observe()
    assert tracker.tokens == {101: None, 102: None}
    tokens[101] = "late"
    clock.now += 5
    tracker.observe()
    assert tracker.tokens[101] == "late"
    tokens[102] = None
    with caplog.at_level("INFO", logger="solus.code.process_os"):
        tracker.kill(signal.SIGKILL)
    assert killed == [101]
    assert any("skipped" in record.getMessage() for record in caplog.records)


def test_observe_interval_is_one_second_on_macos() -> None:
    expected = 1.0 if sys.platform == "darwin" else 0.5
    assert process_os.OBSERVE_SECONDS == expected
    assert execute.TREE_SNAPSHOT_SECONDS == process_os.OBSERVE_SECONDS


def test_linux_start_token_includes_the_boot_id(tmp_path: Path) -> None:
    (tmp_path / "sys" / "kernel" / "random").mkdir(parents=True)
    (tmp_path / "sys" / "kernel" / "random" / "boot_id").write_text("boot-1\n")
    (tmp_path / "42").mkdir()
    fields = " ".join(str(n) for n in range(4, 30))  # value == field number
    (tmp_path / "42" / "stat").write_text(f"42 (a b) S {fields}\n")
    token = process_os.start_token(42, proc_root=tmp_path)
    assert token == "boot-1:22"
    (tmp_path / "sys" / "kernel" / "random" / "boot_id").write_text("boot-2\n")
    assert process_os.start_token(42, proc_root=tmp_path) != token
    (tmp_path / "sys" / "kernel" / "random" / "boot_id").unlink()
    assert process_os.start_token(42, proc_root=tmp_path) == "22", "raw starttime fallback"


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
    # Never SIG_IGN the test process: children would inherit an ignored SIGTERM.
    monkeypatch.setattr(server, "_ignore_shutdown_signals", lambda: None)
    monkeypatch.setattr(server, "_reap_orphans", lambda: None)

    class FakeServer:
        def run(self, transport: str) -> None:
            calls.append("run")

    monkeypatch.setattr(server, "build_server", lambda: FakeServer())
    server.main()
    assert calls == ["subreaper", "run"]
