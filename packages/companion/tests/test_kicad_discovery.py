"""KiCad install discovery: fixed absolute candidates, regular executables only."""

import os
from pathlib import Path

import pytest
from solus_companion.config import discover_servers
from solus_companion.kicad_discovery import KICAD_CLI_ENV, candidate_paths, find_kicad_cli


def _make_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_candidates_are_absolute_and_os_specific() -> None:
    for platform in ("darwin", "linux", "win32"):
        paths = candidate_paths(platform)
        assert paths
        assert all(Path(p).is_absolute() or p[1:3] == ":\\" for p in paths)
    assert candidate_paths("darwin")[0].endswith("KiCad.app/Contents/MacOS/kicad-cli")
    assert any(p.endswith("kicad-cli.exe") for p in candidate_paths("win32"))
    assert candidate_paths("freebsd") == ()


def test_finds_first_executable_candidate(tmp_path: Path) -> None:
    first = _make_exe(tmp_path / "a" / "kicad-cli")
    second = _make_exe(tmp_path / "b" / "kicad-cli")
    assert find_kicad_cli(candidates=(str(first), str(second))) == os.path.realpath(first)


def test_skips_missing_directory_nonexecutable_and_relative(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    plain = tmp_path / "plain"
    plain.write_text("x")
    plain.chmod(0o644)
    good = _make_exe(tmp_path / "good" / "kicad-cli")
    found = find_kicad_cli(
        candidates=(
            str(tmp_path / "nope"),
            str(tmp_path / "dir"),
            str(plain),
            "kicad-cli",
            str(good),
        )
    )
    assert found == os.path.realpath(good)


def test_none_when_nothing_installed(tmp_path: Path) -> None:
    assert find_kicad_cli(candidates=(str(tmp_path / "nope"),)) is None


def test_ambient_environment_cannot_influence_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile = _make_exe(tmp_path / "evil" / "kicad-cli")
    monkeypatch.setenv(KICAD_CLI_ENV, str(hostile))
    monkeypatch.setenv("PATH", str(hostile.parent))
    assert find_kicad_cli(candidates=(str(tmp_path / "nope"),)) is None


def _kicad_root(tmp_path: Path) -> Path:
    server = tmp_path / "kicad"
    (server / "bin").mkdir(parents=True)
    (server / "allowlist.yaml").write_text("server: kicad\n")
    launch = server / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)
    return tmp_path


def test_discover_servers_sets_kicad_cli_path_for_kicad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _make_exe(tmp_path / "bin" / "kicad-cli")
    monkeypatch.setattr("solus_companion.config.find_kicad_cli", lambda: str(exe))
    servers = discover_servers(_kicad_root(tmp_path / "root"))
    assert servers[0].env[KICAD_CLI_ENV] == str(exe)


def test_discover_servers_omits_kicad_cli_path_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("solus_companion.config.find_kicad_cli", lambda: None)
    monkeypatch.setenv(KICAD_CLI_ENV, "/hostile")
    servers = discover_servers(_kicad_root(tmp_path / "root"))
    assert KICAD_CLI_ENV not in servers[0].env


def test_other_servers_never_get_kicad_cli_path() -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp_root"
    assert KICAD_CLI_ENV not in discover_servers(fixture)[0].env


def test_hostile_ambient_kicad_cli_path_never_reaches_child_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_companion.supervisor import child_env

    monkeypatch.setattr("solus_companion.config.find_kicad_cli", lambda: None)
    server = discover_servers(_kicad_root(tmp_path / "root"))[0]
    ambient = {"PATH": "/usr/bin", "HOME": "/h", KICAD_CLI_ENV: "/hostile"}
    assert KICAD_CLI_ENV not in child_env(server.env, server.env_passthrough, source=ambient)
