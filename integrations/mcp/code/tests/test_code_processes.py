"""SOLUSDEV-317 — the long-running process registry (docs/api/code-command-execution.md
§2.3): bounds, ring output with cursors, max runtime, SIGTERM→SIGKILL stop, stop-all,
retention, and orphan reaping by start token. Time and spawning are injected; one
real short-lived process proves the wiring. HOME is always a temp dir."""

import io
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

processes = overlay_module("processes")
profiles = overlay_module("profiles")


class FakeChild:
    def __init__(self, pid: int, stdout: bytes = b"", ignores_term: bool = False) -> None:
        self.pid = pid
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(b"")
        self.returncode: int | None = None
        self.ignores_term = ignores_term

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise TimeoutError
        return self.returncode


class World:
    """Injected clock, spawner, signals and start tokens."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.children: dict[int, FakeChild] = {}
        self.signals: list[tuple[int, int]] = []
        self.next_pid = 500
        self.outputs: list[bytes] = []
        self.spawned: list[tuple[list[str], Path, dict[str, str]]] = []
        self.fail_spawn = False
        self.ignore_term = False
        self.tokens: dict[int, str] = {}

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def spawn(self, argv: list[str], cwd: Path, env: dict[str, str]) -> FakeChild:
        if self.fail_spawn:
            raise FileNotFoundError(argv[0])
        self.next_pid += 1
        child = FakeChild(
            self.next_pid, self.outputs.pop(0) if self.outputs else b"", self.ignore_term
        )
        self.children[child.pid] = child
        self.tokens[child.pid] = f"token-{child.pid}"
        self.spawned.append((argv, cwd, env))
        return child

    def killpg(self, pgid: int, sig: int) -> None:
        self.signals.append((pgid, sig))
        child = self.children.get(pgid)
        if child is None or child.returncode is not None:
            return
        if sig == signal.SIGKILL or not child.ignores_term:
            child.returncode = -sig

    def start_token(self, pid: int) -> str | None:
        return self.tokens.get(pid)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def world() -> World:
    return World()


class FakeTracker:
    """Records descendant-tree observations and kills per leader."""

    events: list[tuple[str, int, int]] = []

    def __init__(self, leader: int) -> None:
        self.leader = leader

    def observe(self, force: bool = False) -> None:
        FakeTracker.events.append(("observe", self.leader, int(force)))

    def kill(self, sig: int) -> None:
        FakeTracker.events.append(("kill", self.leader, sig))


def _registry(ws: Path, world: World, git_digest: Any = None) -> Any:
    FakeTracker.events = []
    return processes.Registry(
        ws,
        spawn=world.spawn,
        clock=world.clock,
        sleep=world.sleep,
        killpg=world.killpg,
        start_token=world.start_token,
        tracker=FakeTracker,
        watch=False,
        git_digest=git_digest or (lambda _root: "unchanged"),
    )


def _start(registry: Any, name: str | None = "bringup", runtime: int = 3600) -> dict[str, Any]:
    result: dict[str, Any] = registry.start(
        ["/usr/bin/sandbox-exec", "...", "/opt/bin/node", "srv.js"],
        display_argv=["/opt/bin/node", "srv.js"],
        cwd=Path("/w"),
        cwd_label="app",
        env={"PATH": "/usr/bin"},
        name=name,
        max_runtime_seconds=runtime,
        sandbox="sandbox-exec",
    )
    return result


def _state_file(home: Path, ws: Path) -> Path:
    return home / ".solus" / "code-processes" / f"{profiles.workspace_key(ws)}.json"


def test_start_records_the_process_and_its_orphan_token(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    result = _start(registry)
    assert result["ok"] is True and result["pid"] == 501 and result["reason"] is None
    assert result["argv"] == ["/opt/bin/node", "srv.js"] and result["cwd"] == "app"
    assert result["sandbox"] == "sandbox-exec" and result["started_at"]
    assert world.spawned[0][0][0] == "/usr/bin/sandbox-exec"
    state = _state_file(home, ws)
    assert json.loads(state.read_text())["processes"] == [
        {"pid": 501, "pgid": 501, "token": "token-501"}
    ]
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.parent.stat().st_mode) == 0o700
    (entry,) = registry.status()["processes"]
    assert entry == {
        "process_id": result["process_id"],
        "name": "bringup",
        "argv": ["/opt/bin/node", "srv.js"],
        "cwd": "app",
        "state": "running",
        "pid": 501,
        "exit_code": None,
        "started_at": result["started_at"],
        "ended_at": None,
        "sandbox": "sandbox-exec",
        "git_metadata_changed": False,
        "interactive": False,
        "awaiting_input": False,
        "prompt_seq": 0,
        "prompt_tail": None,
    }
    assert "output" not in registry.status()


def test_at_most_four_running(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    for _ in range(4):
        assert _start(registry)["ok"] is True
    refused = _start(registry)
    assert refused["ok"] is False and "4" in refused["reason"] and refused["process_id"] is None
    world.children[501].returncode = 0
    registry.sweep()
    assert _start(registry)["ok"] is True


def test_output_is_complete_lines_with_cursor(ws: Path, home: Path, world: World) -> None:
    world.outputs.append(b"first\nsecond\npartial")
    registry = _registry(ws, world)
    process_id = _start(registry)["process_id"]
    world.children[501].returncode = 3
    registry.sweep()
    answer = registry.status(process_id=process_id, cursor=0)
    output = answer["output"]
    assert [chunk["text"] for chunk in output["chunks"]] == ["first\n", "second\n", "partial"]
    assert [chunk["seq"] for chunk in output["chunks"]] == [1, 2, 3]
    assert output["cursor"] == 3 and output["truncated"] is False
    assert output["process_id"] == process_id
    assert registry.status(process_id=process_id, cursor=3)["output"]["chunks"] == []
    later = registry.status(process_id=process_id, cursor=3)["output"]
    assert later["cursor"] == 3
    (entry,) = answer["processes"]
    assert entry["state"] == "exited" and entry["exit_code"] == 3 and entry["ended_at"]


def test_oversized_lines_are_suppressed(ws: Path, home: Path, world: World) -> None:
    world.outputs.append(b"x" * 3000 + b"\nok\n")
    registry = _registry(ws, world)
    process_id = _start(registry)["process_id"]
    world.children[501].returncode = 0
    registry.sweep()
    texts = [c["text"] for c in registry.status(process_id=process_id)["output"]["chunks"]]
    assert texts[0] == "[oversized output line suppressed]\n" and all(len(t) <= 2048 for t in texts)


def test_ring_drops_old_output_and_answers_are_bounded(ws: Path, home: Path, world: World) -> None:
    line = b"y" * 1000 + b"\n"
    world.outputs.append(line * 400)  # ~400 KiB > 256 KiB ring
    registry = _registry(ws, world)
    process_id = _start(registry)["process_id"]
    world.children[501].returncode = 0
    registry.sweep()
    output = registry.status(process_id=process_id, cursor=0)["output"]
    assert output["truncated"] is True
    assert output["chunks"][0]["seq"] > 1
    assert sum(len(c["text"].encode()) for c in output["chunks"]) <= 64 * 1024
    total = 0
    cursor = 0
    while True:
        page = registry.status(process_id=process_id, cursor=cursor)["output"]
        if not page["chunks"]:
            break
        total += sum(len(c["text"].encode()) for c in page["chunks"])
        cursor = page["cursor"]
    assert total <= 256 * 1024 and cursor == 400


def test_max_runtime_kills_the_group(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    process_id = _start(registry, runtime=60)["process_id"]
    world.now += 59
    registry.sweep()
    assert registry.status()["processes"][0]["state"] == "running"
    world.now += 2
    registry.sweep()
    (entry,) = registry.status()["processes"]
    assert entry["state"] == "timed_out" and (501, signal.SIGTERM) in world.signals
    assert process_id == entry["process_id"]
    assert json.loads(_state_file(home, ws).read_text())["processes"] == []


def test_stop_terms_then_kills_after_grace(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    polite = _start(registry)["process_id"]
    assert registry.stop(polite) == {
        "ok": True,
        "process_id": polite,
        "state": "stopped",
        "exit_code": -signal.SIGTERM,
        "reason": None,
        "git_metadata_changed": False,
    }
    assert world.signals == [(501, signal.SIGTERM)]
    world.ignore_term = True
    stubborn = _start(registry)["process_id"]
    started = world.now
    result = registry.stop(stubborn)
    assert result["state"] == "stopped" and result["exit_code"] == -signal.SIGKILL
    assert world.signals[-2:] == [(502, signal.SIGTERM), (502, signal.SIGKILL)]
    assert 5 <= world.now - started < 6
    again = registry.stop(stubborn)
    assert again["ok"] is True and again["state"] == "stopped"
    assert world.signals[-1] == (502, signal.SIGKILL), "a finished process is not signalled again"


def test_unknown_process(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    assert registry.stop("nope") == {
        "ok": False,
        "process_id": "nope",
        "state": None,
        "exit_code": None,
        "reason": "unknown process",
        "git_metadata_changed": False,
    }
    answer = registry.status(process_id="nope")
    assert answer["output"] is None and answer["processes"] == []


def test_spawn_failure_is_recorded_as_failed_to_start(ws: Path, home: Path, world: World) -> None:
    world.fail_spawn = True
    registry = _registry(ws, world)
    result = _start(registry)
    assert result["ok"] is False and "could not start" in result["reason"]
    (entry,) = registry.status()["processes"]
    assert entry["state"] == "failed_to_start" and entry["pid"] is None


def test_retention_and_entry_cap(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    first = _start(registry)["process_id"]
    world.children[501].returncode = 0
    registry.sweep()
    world.now += 29 * 60
    registry.sweep()
    assert [p["process_id"] for p in registry.status()["processes"]] == [first]
    world.now += 2 * 60
    registry.sweep()
    assert registry.status()["processes"] == []
    for _ in range(20):
        _start(registry)
        world.children[world.next_pid].returncode = 0
        registry.sweep()
    assert len(registry.status()["processes"]) == 16


def test_stop_all_stops_everything_and_clears_the_state_file(
    ws: Path, home: Path, world: World
) -> None:
    registry = _registry(ws, world)
    for _ in range(3):
        _start(registry)
    world.children[502].ignores_term = True
    registry.stop_all()
    states = {p["pid"]: p["state"] for p in registry.status()["processes"]}
    assert states == {501: "stopped", 502: "stopped", 503: "stopped"}
    assert (502, signal.SIGKILL) in world.signals
    assert not _state_file(home, ws).exists()


def test_reap_orphans_kills_only_matching_start_tokens(ws: Path, home: Path, world: World) -> None:
    state = _state_file(home, ws)
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "processes": [
                    {"pid": 700, "pgid": 700, "token": "same"},
                    {"pid": 701, "pgid": 701, "token": "old"},
                    {"pid": 1, "pgid": 1, "token": "init"},
                    {"pid": "x", "pgid": 2, "token": "bad"},
                ],
            }
        )
    )
    world.tokens.update({700: "same", 701: "reused-pid", 1: "init"})
    _registry(ws, world).reap_orphans()
    assert world.signals == [(700, signal.SIGKILL)]
    assert not state.exists()


@pytest.mark.parametrize("content", [b"{broken", b"[]", b'{"processes": "x"}', b"\xff" * 10])
def test_reap_orphans_tolerates_corrupt_state(
    ws: Path, home: Path, world: World, content: bytes
) -> None:
    state = _state_file(home, ws)
    state.parent.mkdir(parents=True)
    state.write_bytes(content)
    _registry(ws, world).reap_orphans()
    assert world.signals == [] and not state.exists()


def test_reap_without_a_state_file_writes_nothing(ws: Path, home: Path, world: World) -> None:
    _registry(ws, world).reap_orphans()
    assert not (home / ".solus").exists()


def test_start_token_of_this_process_is_stable() -> None:
    token = processes.start_token(os.getpid())
    assert token and token == processes.start_token(os.getpid())
    assert processes.start_token(2**22 + 12345) is None


def test_real_process_lifecycle(ws: Path, home: Path) -> None:
    registry = processes.Registry(ws)
    try:
        result = registry.start(
            [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(30)"],
            display_argv=["python", "-c", "..."],
            cwd=ws,
            cwd_label=".",
            env={"PATH": "/usr/bin:/bin"},
            name=None,
            max_runtime_seconds=60,
            sandbox=None,
        )
        assert result["ok"] is True
        for _ in range(100):
            chunks = registry.status(process_id=result["process_id"])["output"]["chunks"]
            if chunks:
                break
            time.sleep(0.05)
        assert chunks[0]["text"] == "up\n"
        started = time.monotonic()
        stopped = registry.stop(result["process_id"])
        assert stopped["state"] == "stopped" and time.monotonic() - started < 5
        with pytest.raises(ProcessLookupError):
            os.kill(result["pid"], 0)
    finally:
        registry.stop_all()


def test_stop_and_timeout_kill_the_descendant_tree(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    first = _start(registry)["process_id"]
    registry.sweep()
    assert ("observe", 501, 0) in FakeTracker.events
    registry.stop(first)
    assert ("observe", 501, 1) in FakeTracker.events, "stop takes a forced snapshot"
    assert ("kill", 501, signal.SIGTERM) in FakeTracker.events
    assert ("kill", 501, signal.SIGKILL) in FakeTracker.events
    _start(registry, runtime=60)
    world.now += 61
    registry.sweep()
    assert ("kill", 502, signal.SIGKILL) in FakeTracker.events
    _start(registry)
    registry.stop_all()
    assert ("kill", 503, signal.SIGKILL) in FakeTracker.events


class Digest:
    """An injected git-metadata digest (the Linux detection path, made deterministic)."""

    def __init__(self) -> None:
        self.value = "v0"
        self.roots: list[Path] = []

    def __call__(self, root: Path) -> str:
        self.roots.append(root)
        return self.value


def test_git_metadata_change_is_reported_at_exit(ws: Path, home: Path, world: World) -> None:
    digest = Digest()
    registry = _registry(ws, world, digest)
    process_id = _start(registry)["process_id"]
    assert digest.roots == [ws]
    digest.value = "v1"  # the process wrote .git/hooks (Linux: detection only)
    world.children[501].returncode = 0
    registry.sweep()
    (entry,) = registry.status()["processes"]
    assert entry["state"] == "exited" and entry["git_metadata_changed"] is True
    assert registry.stop(process_id)["git_metadata_changed"] is True


def test_git_metadata_change_is_reported_on_stop_timeout_and_stop_all(
    ws: Path, home: Path, world: World
) -> None:
    digest = Digest()
    registry = _registry(ws, world, digest)
    stopped = _start(registry)["process_id"]
    timed = _start(registry, runtime=60)["process_id"]
    clean = _start(registry)["process_id"]
    assert registry.stop(clean)["git_metadata_changed"] is False
    shutdown = _start(registry)["process_id"]
    digest.value = "v1"
    result = registry.stop(stopped)
    assert result["state"] == "stopped" and result["git_metadata_changed"] is True
    world.now += 61
    registry.sweep()
    registry.stop_all()
    states = {p["process_id"]: p for p in registry.status()["processes"]}
    assert states[timed]["state"] == "timed_out" and states[timed]["git_metadata_changed"]
    assert states[shutdown]["state"] == "stopped" and states[shutdown]["git_metadata_changed"]
    assert states[clean]["git_metadata_changed"] is False


def test_stop_of_a_naturally_exited_process_reports_its_real_state(
    ws: Path, home: Path, world: World
) -> None:
    registry = _registry(ws, world)
    process_id = _start(registry)["process_id"]
    world.children[501].returncode = 0
    result = registry.stop(process_id)
    assert result["state"] == "exited" and result["exit_code"] == 0
    assert world.signals == []


@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox-exec profile")
def test_real_sandboxed_process_cannot_write_git_hooks(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute = overlay_module("execute")
    plan_module = overlay_module("plan")
    ws = (tmp_path / "ws").resolve()
    (ws / ".git" / "hooks").mkdir(parents=True)
    (ws / ".git" / "config").write_text("[core]\n")
    plan = plan_module.plan_action(
        ws,
        "process_start",
        {"argv": ["touch", ".git/hooks/pre-commit"]},
        which=execute.pinned_which,
    )
    assert plan.ok, plan.reason
    prepared = execute.prepare(ws, plan)
    assert not isinstance(prepared, str), prepared
    registry = processes.Registry(ws)
    try:
        with prepared.handing_over():
            started = registry.start(
                prepared.argv,
                display_argv=plan.argv,
                cwd=prepared.cwd,
                cwd_label=".",
                env=prepared.env,
                name=None,
                max_runtime_seconds=60,
                sandbox=plan.sandbox,
            )
        assert started["ok"] is True
        for _ in range(200):
            (entry,) = registry.status()["processes"]
            if entry["state"] != "running":
                break
            time.sleep(0.05)
        assert entry["state"] == "exited" and entry["exit_code"] != 0
        assert not (ws / ".git" / "hooks" / "pre-commit").exists()
        assert entry["git_metadata_changed"] is False
    finally:
        registry.stop_all()


def test_stop_all_with_a_short_grace_escalates_quickly(ws: Path, home: Path, world: World) -> None:
    registry = _registry(ws, world)
    world.ignore_term = True
    _start(registry)
    started = world.now
    registry.stop_all(grace_seconds=1.0)
    assert world.signals == [(501, signal.SIGTERM), (501, signal.SIGKILL)]
    assert 1.0 <= world.now - started < 1.5
