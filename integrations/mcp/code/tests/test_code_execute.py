"""SOLUSDEV-250 — `execute_plan`: runs EXACTLY the planned argv (argv[0]
resolved inside the workspace or against the pinned roots), scrubbed child
env (only PATH/HOME/LANG/TMPDIR/VIRTUAL_ENV — never a secret), 16 KiB tails,
timeout → process-group kill, never raises; plus the real runner."""

import dataclasses
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from conftest import FAKE_KIND  # isort: skip
from venv_fixture import fake_venv  # isort: skip

execute = overlay_module("execute")
plan = overlay_module("plan")
sandbox = overlay_module("sandbox")
profiles = overlay_module("profiles")


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
    ((argv, cwd, _runner_env, timeout),) = recorder.calls
    # The sandbox prefix is platform-specific (Linux adds `--env-fd N`); the tail is exact.
    expected = sandbox.wrap(FAKE_KIND, [str(ws / ".venv" / "bin" / "python"), "a.py"], workspace=ws)
    assert argv[0] == expected[0] and argv[-2:] == expected[-2:]
    assert cwd == ws and timeout == 7
    prepared = execute.prepare(ws, planned)
    assert not isinstance(prepared, str)
    env = prepared.child_env
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
        "sandbox": FAKE_KIND,
        "git_metadata_changed": False,
    }
    assert isinstance(result["duration_ms"], int) and result["duration_ms"] >= 0


def test_bare_tool_names_resolve_against_the_pinned_roots_only(ws: Path) -> None:
    recorder = Recorder()
    planned = plan.plan_action(ws, "install", {"packages": ["numpy"]}, which=lambda n: "/opt/x/uv")
    execute.execute_plan(ws, planned, runner=recorder, which=lambda n: "/opt/roots/uv")
    assert recorder.calls[0][0][-7:-5] == ["/opt/roots/uv", "pip"]
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
        "sandbox",
        "git_metadata_changed",
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
        # A zombie still answers kill(0); read its scheduler state instead.
        if _process_state(grandchild) in ("", "Z"):
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild survived the process-group kill")


def _process_state(pid: int) -> str:
    """One-letter scheduler state ("" once the pid is gone). Reads /proc on
    Linux — the slim CI image ships no `ps` — and falls back to ps elsewhere."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ""
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        # `pid (comm) S ...` — comm may contain spaces, so split after the last ')'.
        return proc_stat.read_text().rpartition(")")[2].split()[0]
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return state.stdout.strip()[:1]


def test_default_runner_stdin_is_closed(tmp_path: Path) -> None:
    code = "import sys; print(repr(sys.stdin.read()))"
    outcome = execute.default_runner([sys.executable, "-c", code], tmp_path, _env(), 30)
    assert outcome.stdout.strip() == b"''"


# --- SOLUSDEV-317: sandbox, profiles, cwd, git metadata ------------------------------


def _exec_plan(ws: Path, **fields: Any) -> Any:
    tool = ws / "tools" / "t.sh"
    tool.parent.mkdir(exist_ok=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    base = plan.Plan(
        action="exec", ok=True, argv=[str(tool), "x"], sandbox=FAKE_KIND, timeout_seconds=5
    )
    return dataclasses.replace(base, **fields)


def test_a_plan_without_sandbox_never_runs(ws: Path) -> None:
    recorder = Recorder()
    result = execute.execute_plan(ws, _exec_plan(ws, sandbox=None), runner=recorder)
    assert recorder.calls == [] and result["reason"].startswith("sandbox unavailable")


def test_absolute_program_cwd_and_profile_environment(ws: Path, scrub: None) -> None:
    (ws / "sub").mkdir()
    profile = profiles.Profile(
        name="ros",
        setup_file="/opt/ros/x.bash",
        extends=None,
        captured_at="t",
        variables=(("PATH", "/opt/ros/bin:/usr/bin:/bin"), ("ROS_DISTRO", "jazzy"), ("HOME", "/x")),
        digest="d",
    )
    recorder = Recorder()
    planned = _exec_plan(ws, cwd="sub", profile=profile, environment=".venv")
    result = execute.execute_plan(ws, planned, runner=recorder)
    ((argv, cwd, _runner_env, timeout),) = recorder.calls
    assert argv[-2:] == [str(ws / "tools" / "t.sh"), "x"] and cwd == ws / "sub"
    prepared = execute.prepare(ws, planned)
    assert not isinstance(prepared, str)
    env = prepared.child_env  # what the command runs with (Linux passes it over --env-fd)
    assert env["ROS_DISTRO"] == "jazzy" and env["HOME"] == "/home/u"
    assert env["PATH"] == f"{ws / '.venv' / 'bin'}:/opt/ros/bin:/usr/bin:/bin"
    assert result["cwd"] == "sub" and result["sandbox"] == FAKE_KIND and timeout == 5


def test_git_metadata_change_is_reported(ws: Path) -> None:
    (ws / ".git" / "hooks").mkdir(parents=True)

    def tamper(*_args: object) -> Any:
        (ws / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n")
        return execute.Outcome(0, b"", b"", False)

    assert execute.execute_plan(ws, _exec_plan(ws), runner=tamper)["git_metadata_changed"] is True
    quiet = execute.execute_plan(ws, _exec_plan(ws), runner=Recorder())
    assert quiet["git_metadata_changed"] is False


def test_moved_cwd_and_missing_program_refuse(ws: Path) -> None:
    assert (
        "cwd" in execute.execute_plan(ws, _exec_plan(ws, cwd="gone"), runner=Recorder())["reason"]
    )
    missing = _exec_plan(ws, argv=[str(ws / "nope"), "x"])
    assert "executable not found" in execute.execute_plan(ws, missing, runner=Recorder())["reason"]


@pytest.mark.real_sandbox
def test_real_exec_runs_sandboxed(tmp_path: Path) -> None:
    ws = tmp_path.resolve()
    tool = ws / "w.sh"
    tool.write_text("#!/bin/sh\necho hi > inside.txt && echo done\necho x > .git/config || true\n")
    tool.chmod(0o755)
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("[core]\n")
    kind = sandbox.probe()[0]
    planned = plan.Plan(action="exec", ok=True, argv=[str(tool)], sandbox=kind, timeout_seconds=30)
    result = execute.execute_plan(ws, planned)
    assert result["ok"] is True and result["stdout_tail"] == "done\n", result
    assert (ws / "inside.txt").read_text() == "hi\n"
    assert result["git_metadata_changed"] is (kind != "sandbox-exec")


def _profile_with(variables: tuple[tuple[str, str], ...]) -> Any:
    return profiles.Profile(
        name="p", setup_file="/x.sh", extends=None, captured_at="t", variables=variables, digest="d"
    )


def test_loader_injection_variables_never_reach_a_child(ws: Path, scrub: None) -> None:
    hostile = _profile_with(
        (
            ("LD_PRELOAD", "/evil.so"),
            ("LD_AUDIT", "x"),
            ("DYLD_INSERT_LIBRARIES", "x"),
            ("GCONV_PATH", "/evil"),
            ("LD_LIBRARY_PATH", "/opt/ros/lib"),
        )
    )
    env = execute.child_env(ws, _exec_plan(ws, profile=hostile))
    assert not {"LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES", "GCONV_PATH"} & set(env)
    assert env["LD_LIBRARY_PATH"] == "/opt/ros/lib"


def test_linux_helper_gets_a_fixed_env_and_the_child_env_over_a_descriptor(
    ws: Path, scrub: None
) -> None:
    seen: dict[str, Any] = {}

    def runner(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> Any:
        fd = int(argv[argv.index("--env-fd") + 1])
        seen["payload"] = os.pread(fd, 1 << 20, 0)
        seen["fds"] = execute.sandbox.PASS_FDS.get()
        seen["fd"], seen["env"] = fd, env
        return execute.Outcome(0, b"", b"", False)

    profile = _profile_with((("ROS_DISTRO", "jazzy"), ("LD_LIBRARY_PATH", "/opt/ros/lib")))
    planned = _exec_plan(ws, sandbox="landlock-abi3", profile=profile)
    result = execute.execute_plan(ws, planned, runner=runner)
    assert result["ok"] is True, result
    assert seen["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert seen["fds"] == (seen["fd"],)
    entries = dict(e.split(b"=", 1) for e in seen["payload"].split(b"\0") if e)
    assert entries[b"ROS_DISTRO"] == b"jazzy" and entries[b"LD_LIBRARY_PATH"] == b"/opt/ros/lib"
    assert entries[b"HOME"] == b"/home/u" and b"AWS_SECRET_ACCESS_KEY" not in entries
    with pytest.raises(OSError):
        os.fstat(seen["fd"])  # closed once the command finished


def test_oversized_child_environment_is_refused(ws: Path, scrub: None) -> None:
    huge = _profile_with(tuple((f"V{i}", "x" * 8000) for i in range(200)))
    recorder = Recorder()
    planned = _exec_plan(ws, sandbox="landlock-abi3", profile=huge)
    result = execute.execute_plan(ws, planned, runner=recorder)
    assert recorder.calls == [] and "environment too large" in result["reason"]


def test_default_runner_kills_the_group_after_the_leader_exits(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys\n"
        f"child = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
    )
    outcome = execute.default_runner([sys.executable, "-c", code], tmp_path, _env(), 30)
    assert outcome.exit_code == 0
    leftover = int(outcome.stdout.split()[0])
    for _ in range(50):
        if _process_state(leftover) in ("", "Z"):
            break
        time.sleep(0.1)
    else:
        pytest.fail("a descendant outlived the command's process group")


def test_pinned_which_refuses_a_program_in_a_writable_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§9.5: a tool planted in a writable cache by an earlier command never resolves."""
    home = tmp_path / "home"
    planted = home / ".cache" / "bin" / "uv"
    planted.parent.mkdir(parents=True)
    planted.write_text("#!/bin/sh\n")
    planted.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(execute, "SEARCH_ROOTS", ("~/.cache/bin",))
    assert execute.pinned_which("uv") is None


@pytest.mark.real_writable_roots
def test_resolve_executable_refuses_a_venv_interpreter_linked_into_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"
    planted = tmp_path / "planted-python"
    planted.write_text("#!/bin/sh\n")
    planted.chmod(0o755)
    (ws / ".venv" / "bin").mkdir(parents=True)
    (ws / ".venv" / "bin" / "python").symlink_to(planted)
    assert execute.resolve_executable(ws, ".venv/bin/python") is None
    assert execute.resolve_executable(ws, str(planted)) is None
    inside = ws / "bin" / "tool.sh"
    inside.parent.mkdir()
    inside.write_text("#!/bin/sh\n")
    inside.chmod(0o755)
    assert execute.resolve_executable(ws, "bin/tool.sh") == str(inside)
