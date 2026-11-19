"""Subprocess hygiene — argv only, scrubbed env, timeouts, capped output (§3)."""

from __future__ import annotations

import sys
from pathlib import Path

from solus_companion.runtime.proc import (
    OUTPUT_CAP_BYTES,
    POSIX_PATH,
    redact,
    run_capped,
    scrubbed_env,
)

DIRTY = {
    "PATH": "/evil/bin:/usr/bin",
    "HOME": "/Users/u",
    "TMPDIR": "/tmp/x",
    "PIP_INDEX_URL": "https://evil.example/simple",
    "PIP_EXTRA_INDEX_URL": "https://evil.example/simple",
    "PYTHONPATH": "/evil",
    "PYTHONHOME": "/evil",
    "PYTHONSTARTUP": "/evil/start.py",
    "VIRTUAL_ENV": "/some/venv",
    "CONDA_PREFIX": "/conda",
    "CONDA_DEFAULT_ENV": "base",
    "__PYVENV_LAUNCHER__": "/x",
    "AWS_SECRET_ACCESS_KEY": "nope",
    "HTTPS_PROXY": "http://proxy:3128",
    "SystemRoot": r"C:\Windows",
    "TEMP": r"C:\Temp",
    "LOCALAPPDATA": r"C:\Users\u\AppData\Local",
}

FORBIDDEN_PREFIXES = ("PIP_", "PYTHON", "VIRTUAL_ENV", "CONDA_", "__PYVENV")


def test_posix_child_env_is_built_from_scratch() -> None:
    env = scrubbed_env(DIRTY, "darwin")
    assert env["PATH"] == POSIX_PATH
    assert env["HOME"] == "/Users/u" and env["TMPDIR"] == "/tmp/x"
    assert not any(k.startswith(FORBIDDEN_PREFIXES) for k in env)
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "HTTPS_PROXY" not in env  # §3: built from scratch; the doc forwards no proxy


def test_windows_child_env_keeps_only_what_python_needs_to_start() -> None:
    env = scrubbed_env(DIRTY, "win32")
    assert env["PATH"] == r"C:\Windows\System32;C:\Windows"
    assert env["SYSTEMROOT"] == r"C:\Windows" and env["TEMP"] == r"C:\Temp"
    assert not any(k.upper().startswith(FORBIDDEN_PREFIXES) for k in env)
    assert "HOME" not in env and "AWS_SECRET_ACCESS_KEY" not in env


def test_run_capped_runs_argv_and_captures(tmp_path: Path) -> None:
    result = run_capped(
        [sys.executable, "-I", "-c", "import sys;print('out');print('err',file=sys.stderr)"],
        timeout=30,
        env=scrubbed_env({}, sys.platform),
    )
    assert result.ok and result.stdout.strip() == "out" and result.stderr.strip() == "err"


def test_run_capped_keeps_only_the_tail() -> None:
    script = f"import sys;sys.stdout.write('a'*{OUTPUT_CAP_BYTES * 2}+'END')"
    result = run_capped([sys.executable, "-I", "-c", script], timeout=30, env={})
    assert len(result.stdout.encode()) <= OUTPUT_CAP_BYTES
    assert result.stdout.endswith("END")


def test_run_capped_times_out_and_kills() -> None:
    result = run_capped(
        [sys.executable, "-I", "-c", "import time;time.sleep(30)"], timeout=0.5, env={}
    )
    assert result.timed_out and not result.ok


def test_run_capped_reports_a_missing_binary(tmp_path: Path) -> None:
    result = run_capped([str(tmp_path / "nope")], timeout=5, env={})
    assert result.launch_error and not result.ok


def test_redact_hides_home() -> None:
    assert redact("failed in /Users/alice/x", "/Users/alice") == "failed in ~/x"
    assert redact("nothing", "") == "nothing"
