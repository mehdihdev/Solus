"""Windows launcher resolution (ALT-9): specs keep pointing at `bin/launch`;
on win32 the sibling `bin/launch.cmd` is the real launcher (the altium fork
ships both). The executability guard must be meaningful per-platform —
`os.access(..., X_OK)` is always True on Windows for existing files."""

import sys
from pathlib import Path

import pytest
from solus_companion.config import discover_servers


def _write_server(
    root: Path, name: str, *, cmd_launcher: bool, posix_launcher: bool = True
) -> Path:
    server_dir = root / name
    (server_dir / "bin").mkdir(parents=True)
    (server_dir / "allowlist.yaml").write_text(f"server: {name}\n")
    if posix_launcher:
        launch = server_dir / "bin" / "launch"
        launch.write_text("#!/bin/sh\nexit 0\n")
        launch.chmod(0o755)
    if cmd_launcher:
        (server_dir / "bin" / "launch.cmd").write_text("@echo off\r\nexit /b 0\r\n")
    return server_dir


def _as_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")


def test_win32_resolves_the_sibling_launch_cmd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_server(tmp_path, "altium", cmd_launcher=True)
    _as_windows(monkeypatch)
    servers = discover_servers(tmp_path)
    assert [server.name for server in servers] == ["altium"]
    assert servers[0].command == (tmp_path / "altium" / "bin" / "launch.cmd").resolve()


def test_win32_without_launch_cmd_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A POSIX-only fork is refused on Windows with a clear reason — never
    launched via the shell-script `launch` (which Windows cannot execute)."""
    _write_server(tmp_path, "altium", cmd_launcher=False)
    _as_windows(monkeypatch)
    with caplog.at_level("ERROR"):
        assert discover_servers(tmp_path) == ()
    assert any(
        "REFUSED" in record.getMessage() and "launch.cmd" in record.getMessage()
        for record in caplog.records
    )


def test_win32_launch_cmd_must_stay_inside_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ADR-031 confinement guard applies to the RESOLVED Windows launcher
    exactly as it does to the POSIX one."""
    outside = tmp_path / "outside.cmd"
    outside.write_text("@echo off\r\n")
    root = tmp_path / "root"
    server_dir = _write_server(root, "evil", cmd_launcher=False)
    (server_dir / "bin" / "launch.cmd").symlink_to(outside)
    _as_windows(monkeypatch)
    assert discover_servers(root) == ()


def test_win32_launcher_resolving_to_a_non_executable_extension_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.access(X_OK) is meaningless on Windows: the guard there is the
    resolved launcher's extension (.cmd/.bat/.exe/.com)."""
    server_dir = _write_server(tmp_path, "meek", cmd_launcher=False)
    payload = server_dir / "bin" / "payload.txt"
    payload.write_text("not a launcher")
    (server_dir / "bin" / "launch.cmd").symlink_to(payload)
    _as_windows(monkeypatch)
    assert discover_servers(tmp_path) == ()


def test_posix_behavior_unchanged_when_launch_cmd_is_present(tmp_path: Path) -> None:
    """On POSIX the sibling launch.cmd is inert: bin/launch is resolved and
    the execute-bit guard still governs."""
    _write_server(tmp_path, "altium", cmd_launcher=True)
    servers = discover_servers(tmp_path)
    assert [server.name for server in servers] == ["altium"]
    assert servers[0].command == (tmp_path / "altium" / "bin" / "launch").resolve()


def test_posix_non_executable_launch_still_refused(tmp_path: Path) -> None:
    server_dir = _write_server(tmp_path, "meek", cmd_launcher=True)
    (server_dir / "bin" / "launch").chmod(0o644)
    assert discover_servers(tmp_path) == ()
