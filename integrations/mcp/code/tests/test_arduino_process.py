"""Owned process deadlines, output limits and process-group cleanup."""

import sys
import time
from pathlib import Path

import pytest

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

process = overlay_module("arduino_process")


def test_process_captures_tail_and_exit_without_inherited_environment(tmp_path: Path) -> None:
    result = process.run_bounded(
        [sys.executable, "-c", "import os; print(os.environ.get('PRIVATE_FIXTURE', 'absent'))"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        deadline=time.monotonic() + 5,
    )
    assert result["exit_code"] == 0 and result["stdout_tail"] == "absent\n"
    assert not result["timed_out"]


def test_output_cap_terminates_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process, "HARD_OUTPUT_BYTES", 1024)
    result = process.run_bounded(
        [sys.executable, "-c", "import os,time; os.write(1,b'x'*65536); time.sleep(30)"],
        cwd=tmp_path,
        env={},
        deadline=time.monotonic() + 5,
    )
    assert not result["ok"] and result["reason"] == "resource_limit"
    assert result["stdout_truncated"]


def test_timeout_kills_group_and_returns_unknown_exit(tmp_path: Path) -> None:
    start = time.monotonic()
    result = process.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env={},
        deadline=start + 0.15,
    )
    assert time.monotonic() - start < 3
    assert result["timed_out"] and result["exit_code"] is None


def test_closed_environment_is_fixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARDUINO_BOARD_MANAGER_ADDITIONAL_URLS", "https://example.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "https://example.invalid")
    env = process.closed_environment(tmp_path)
    assert set(env) == {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}
    assert env["HOME"] == str(tmp_path / "home")


def test_cancel_after_child_closes_both_pipes_is_prompt(tmp_path: Path) -> None:
    import threading

    event = threading.Event()
    token = process.CANCEL_EVENT.set(event)
    timer = threading.Timer(0.2, event.set)
    timer.start()
    start = time.monotonic()
    try:
        result = process.run_bounded(
            [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(30)"],
            cwd=tmp_path,
            env={},
            deadline=start + 2,
        )
    finally:
        process.CANCEL_EVENT.reset(token)
        timer.cancel()
    assert time.monotonic() - start < 1
    assert result["reason"] == "cancelled" and result["started"]


def test_sealed_cli_cannot_change_when_source_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import os

    runtime = overlay_module("arduino_toolchain")
    binary = tmp_path / "cli"
    original = b"pinned executable fixture for immutable descriptor"
    binary.write_bytes(original)
    binary.chmod(0o755)
    monkeypatch.setattr(runtime, "CLI_SHA256", hashlib.sha256(original).hexdigest())
    descriptor = process.sealed_cli(binary)
    binary.write_bytes(b"substituted executable")
    assert os.pread(descriptor, len(original), 0) == original
    with pytest.raises(OSError):
        os.pwrite(descriptor, b"x", 0)
    with pytest.raises(runtime.ArduinoError, match="cli_unavailable"):
        process.sealed_cli(binary)


def test_prelaunch_cancel_is_not_a_timeout_or_started_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    event = threading.Event()
    event.set()
    token = process.CANCEL_EVENT.set(event)
    monkeypatch.setattr(
        process.subprocess, "Popen", lambda *a, **kw: pytest.fail("process started")
    )
    try:
        result = process.run_bounded(["never"], cwd=tmp_path, env={}, deadline=time.monotonic() + 2)
    finally:
        process.CANCEL_EVENT.reset(token)
    assert result["reason"] == "cancelled" and not result["timed_out"] and not result["started"]


def test_server_import_and_neutral_probe_without_fcntl() -> None:
    import subprocess
    from pathlib import Path

    script = """
import asyncio
import builtins
import platform
from code_paths import overlay_module
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError("fcntl unavailable on this host")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
platform.system = lambda: "Windows"
platform.machine = lambda: "AMD64"
server = overlay_module("server")
assert "arduino_probe" in {tool.name for tool in asyncio.run(server.build_server().list_tools())}
probe = asyncio.run(server.tool_arduino_probe())
assert probe["platform"]["supported"] is False
assert probe["cli"]["reason"] == "Arduino toolchain not available on Windows/AMD64"
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).parent)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_real_bubblewrap_accepts_sealed_file_and_directory_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import os
    import platform
    from pathlib import Path

    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        pytest.skip("reviewed sandbox is Linux ARM64")
    if process.BWRAP.stat().st_uid != 0:
        pytest.skip("requires the actual host-owned Bubblewrap executable")
    runtime = overlay_module("arduino_toolchain")
    install = overlay_module("arduino_install")
    binary = Path("/usr/bin/true")
    monkeypatch.setattr(runtime, "CLI_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest())
    directory = install.open_directory(tmp_path)
    try:
        argv = process.sandbox_argv(binary, tmp_path, (str(binary),), writable_fd=directory)
        assert "--ro-bind-data" in argv and "--bind-fd" in argv
        for _ in range(2):
            result = process.run_bounded(
                argv,
                cwd=tmp_path,
                env=process.closed_environment(tmp_path),
                deadline=time.monotonic() + 5,
            )
            assert result["ok"], result["stderr_tail"]
    finally:
        os.close(directory)
    assert result["ok"], result["stderr_tail"]


def test_real_directory_mount_uses_held_inode_after_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import os
    import platform
    from pathlib import Path

    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        pytest.skip("reviewed sandbox is Linux ARM64")
    if process.BWRAP.stat().st_uid != 0:
        pytest.skip("requires actual host-owned Bubblewrap")
    runtime = overlay_module("arduino_toolchain")
    install = overlay_module("arduino_install")
    binary = Path("/usr/bin/cat")
    monkeypatch.setattr(runtime, "CLI_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest())
    original = tmp_path / "original"
    original.mkdir()
    (original / "owned.txt").write_text("owned")
    descriptor = install.open_directory(original)
    original.rename(tmp_path / "moved")
    original.mkdir()
    (original / "owned.txt").write_text("replacement")
    try:
        argv = process.sandbox_argv(
            binary, original, (str(binary), str(original / "owned.txt")), writable_fd=descriptor
        )
        result = process.run_bounded(
            argv,
            cwd=tmp_path,
            env=process.closed_environment(original),
            deadline=time.monotonic() + 5,
        )
    finally:
        os.close(descriptor)
    assert result["ok"], result["stderr_tail"]
    assert result["stdout_tail"] == "owned"
    assert (original / "owned.txt").read_text() == "replacement"


@pytest.mark.parametrize("success", [True, False, None])
def test_complete_bounded_json_is_validated_before_returning_only_tail(
    tmp_path: Path, success: bool | None
) -> None:
    import json

    body = json.dumps({"success": success, "compiler_out": "x" * 20_000})
    if success is None:
        body = "not JSON: " + "x" * 20_000
    result = process.run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", body],
        cwd=tmp_path,
        env={},
        deadline=time.monotonic() + 5,
        expect_json_success=True,
    )
    assert result["exit_code"] == 0 and result["started"]
    assert result["ok"] is (success is True)
    assert result["stdout_truncated"] and len(result["stdout_tail"]) <= 16_384
    assert not any(key in result for key in ("raw_stdout", "stdout_json", "parsed_report"))
    if success is not True:
        assert result["reason"] == "compilation_unverified"
