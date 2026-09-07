"""SOLUSDEV-250 — `execute_plan`: runs EXACTLY the planned argv (argv[0]
resolved inside the workspace or against the pinned roots), scrubbed child
env (only PATH/HOME/LANG/TMPDIR/VIRTUAL_ENV — never a secret), 16 KiB tails,
timeout → process-group kill, never raises; plus the real runner."""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from venv_fixture import fake_venv  # isort: skip

execute = overlay_module("execute")
plan = overlay_module("plan")


class Recorder:
    def __init__(self, outcome: Any = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str], int]] = []
        self.outcome = outcome or execute.Outcome(0, b"out", b"err", False)
        self.error = error

    def __call__(self, argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> Any:
        self.calls.append((list(argv), cwd, dict(env), timeout))
        if self.error:
            raise self.error
        return self.outcome


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    fake_venv(tmp_path)
    (tmp_path / "a.py").write_text("print(1)\n")
    return tmp_path


@pytest.fixture
def scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", "/home/u")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("TMPDIR", "/tmp/t")
    monkeypatch.setenv("PATH", "/evil/bin")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    monkeypatch.setenv("GITHUB_TOKEN", "nope")
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else")
    monkeypatch.setenv("USER", "u")


def _run_plan(ws: Path) -> Any:
    return plan.plan_action(
        ws, "run", {"script": "a.py", "timeout_seconds": 7}, which=lambda _n: None
    )


def test_scrubbed_env_is_exactly_the_documented_names(ws: Path, scrub: None) -> None:
    env = execute.scrubbed_env(ws, ".venv")
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "VIRTUAL_ENV"}
    assert env["PATH"] == f"{ws / '.venv' / 'bin'}:/usr/bin:/bin"
    assert env["VIRTUAL_ENV"] == str(ws / ".venv")
    assert env["HOME"] == "/home/u"
    bare = execute.scrubbed_env(ws, None)
    assert set(bare) == {"PATH", "HOME", "LANG", "TMPDIR"} and bare["PATH"] == "/usr/bin:/bin"


def test_scrubbed_env_omits_unset_names(
    ws: Path, scrub: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TMPDIR")
    assert "TMPDIR" not in execute.scrubbed_env(ws, None)


def test_executes_exactly_the_plan_with_a_resolved_interpreter(ws: Path, scrub: None) -> None:
    recorder = Recorder()
    planned = _run_plan(ws)
    result = execute.execute_plan(ws, planned, runner=recorder)
    ((argv, cwd, env, timeout),) = recorder.calls
    assert argv == [str(ws / ".venv" / "bin" / "python"), "a.py"]
    assert cwd == ws and timeout == 7
    assert env["VIRTUAL_ENV"] == str(ws / ".venv") and "GITHUB_TOKEN" not in env
    assert result == {
        "ok": True,
        "argv": [".venv/bin/python", "a.py"],
        "cwd": ".",
        "exit_code": 0,
        "stdout_tail": "out",
        "stderr_tail": "err",
        "duration_ms": result["duration_ms"],
        "timed_out": False,
        "reason": None,
    }
    assert isinstance(result["duration_ms"], int) and result["duration_ms"] >= 0


def test_bare_tool_names_resolve_against_the_pinned_roots_only(ws: Path) -> None:
    recorder = Recorder()
    planned = plan.plan_action(ws, "install", {"packages": ["numpy"]}, which=lambda n: "/opt/x/uv")
    execute.execute_plan(ws, planned, runner=recorder, which=lambda n: "/opt/roots/uv")
    assert recorder.calls[0][0][0] == "/opt/roots/uv"
    missing = execute.execute_plan(ws, planned, runner=Recorder(), which=lambda n: None)
    assert missing["ok"] is False and missing["reason"] == "executable not found: uv"


def test_relative_interpreter_must_live_inside_the_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "bin"
    outside.mkdir(parents=True)
    (outside / "python").write_text("")
    (outside / "python").chmod(0o755)
    ws = tmp_path / "ws"
    ws.mkdir()
    os.symlink(tmp_path / "outside", ws / ".venv")
    assert execute.resolve_executable(ws, ".venv/bin/python") is None
    assert execute.resolve_executable(ws, "../outside/bin/python") is None
    assert execute.resolve_executable(ws, "missing/python") is None


def test_pinned_which_never_consults_the_inherited_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "uv").write_text("")
    (evil / "uv").chmod(0o755)
    monkeypatch.setenv("PATH", str(evil))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert execute.pinned_which("uv") is None or not execute.pinned_which("uv").startswith(
        str(evil)
    )
    assert str(evil) not in execute.search_path()
    assert execute.search_path().startswith("/usr/bin")


def test_tails_are_cut_to_16_kib(ws: Path) -> None:
    outcome = execute.Outcome(0, b"a" * 100_000 + b"END", b"\xff" * 20_000, False)
    result = execute.execute_plan(ws, _run_plan(ws), runner=Recorder(outcome))
    assert len(result["stdout_tail"]) == 16 * 1024 and result["stdout_tail"].endswith("END")
    assert len(result["stderr_tail"]) == 16 * 1024  # undecodable bytes are replaced, never raised


def test_timeout_and_non_zero_exit_are_not_ok(ws: Path) -> None:
    timed = execute.execute_plan(
        ws, _run_plan(ws), runner=Recorder(execute.Outcome(None, b"", b"", True))
    )
    assert timed["ok"] is False and timed["exit_code"] is None and timed["timed_out"] is True
    assert timed["reason"] == "timed out after 7 s"
    failed = execute.execute_plan(
        ws, _run_plan(ws), runner=Recorder(execute.Outcome(3, b"", b"boom", False))
    )
    assert failed["ok"] is False and failed["exit_code"] == 3 and failed["stderr_tail"] == "boom"


def test_refused_plans_and_spawn_failures_answer_the_refusal_shape(ws: Path) -> None:
    refused = plan.plan_action(ws, "run", {"script": "../x"}, which=lambda _n: None)
    recorder = Recorder()
    result = execute.execute_plan(ws, refused, runner=recorder)
    assert recorder.calls == [] and result == execute.refusal(refused.reason)
    crashed = execute.execute_plan(ws, _run_plan(ws), runner=Recorder(error=OSError("nope")))
    assert crashed == execute.refusal("could not start: OSError")
    assert set(execute.refusal("x")) == {
        "ok",
        "argv",
        "cwd",
        "exit_code",
        "stdout_tail",
        "stderr_tail",
        "duration_ms",
        "timed_out",
        "reason",
    }


# --- the real runner -----------------------------------------------------------------


def _env() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}


def test_default_runner_captures_exit_code_and_both_streams(tmp_path: Path) -> None:
    code = "import sys; print('hi'); print('bad', file=sys.stderr); sys.exit(4)"
    outcome = execute.default_runner([sys.executable, "-c", code], tmp_path, _env(), 30)
    assert outcome.exit_code == 4 and outcome.stdout == b"hi\n" and b"bad" in outcome.stderr
    assert outcome.timed_out is False


def test_default_runner_kills_the_whole_process_group_on_timeout(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    started = time.monotonic()
    outcome = execute.default_runner([sys.executable, "-c", code], tmp_path, _env(), 2)
    assert outcome.timed_out is True and outcome.exit_code is None
    assert time.monotonic() - started < 15
    grandchild = int(outcome.stdout.split()[0])
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        # A zombie still answers kill(0); ps shows its state.
        state = subprocess.run(
            ["/bin/ps", "-o", "stat=", "-p", str(grandchild)], capture_output=True, text=True
        )
        if not state.stdout.strip() or state.stdout.strip().startswith("Z"):
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild survived the process-group kill")


def test_default_runner_stdin_is_closed(tmp_path: Path) -> None:
    code = "import sys; print(repr(sys.stdin.read()))"
    outcome = execute.default_runner([sys.executable, "-c", code], tmp_path, _env(), 30)
    assert outcome.stdout.strip() == b"''"
