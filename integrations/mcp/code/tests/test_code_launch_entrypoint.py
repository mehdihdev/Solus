"""SOLUSDEV-250 — the `code` server's Solus-authored launch entrypoint,
mirroring the local fork's pins: fixed argv, `env -i` scrub to the declared
allowlist (local's set + VIRTUAL_ENV), PATH pinned to a constant, zero
network/installer commands at LAUNCH, the interpreter ONLY from
`SOLUS_MCP_PYTHON` (exit 78 otherwise — ADR-031 amendment 2026-11-19), `cd` to
the companion-passed workspace, companion discovery, and the `bin/launch.cmd`
Windows twin."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from solus_companion.config import discover_servers

from code_paths import ENV_ALLOW, FORK_DIR, LAUNCH, MCP_ROOT, overlay_module  # isort: skip

DECLARED_ENV_ALLOWLIST: frozenset[str] = overlay_module("env_allowlist").CHILD_ENV_ALLOWLIST
LAUNCH_CMD = FORK_DIR / "bin" / "launch.cmd"

EXPECTED_ENV_ALLOWLIST = frozenset(
    {"HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "PATH", "SOLUS_MCP_WORKSPACE"}
)
FORBIDDEN_TOKENS = (
    "npx",
    "uvx",
    "pip install",
    "uv ",
    "curl",
    "wget",
    "git clone",
    "nc -",
    "ftp",
    "rsync",
    "ssh ",
)
SECRETISH_FRAGMENTS = ("SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "APIKEY", "API_KEY")


def _launch_text() -> str:
    return LAUNCH.read_text(encoding="utf-8")


def _launch_commands() -> str:
    lines = [line for line in _launch_text().splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines)


def _cmd_text() -> str:
    return LAUNCH_CMD.read_text(encoding="utf-8")


def _cmd_commands() -> str:
    """launch.cmd text with `rem` comment lines stripped."""
    lines = [
        line for line in _cmd_text().splitlines() if not line.lstrip().lower().startswith("rem")
    ]
    return "\n".join(lines)


#: Names a POSIX /bin/sh sets on the process it execs (not secret- or path-bearing).
SHELL_INJECTED = frozenset({"PWD", "SHLVL", "_", "OLDPWD"})


def _fake_interpreter(directory: Path) -> tuple[Path, Path, Path]:
    """An executable `python3` stand-in that records its argv and environment."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "python3"
    argv_log = directory / "argv.txt"
    env_log = directory / "env.txt"
    script.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$0" "$@" > "{argv_log}"\n/usr/bin/env > "{env_log}"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, argv_log, env_log


def _interpreter_value(tmp_path: Path, kind: str) -> str:
    """A SOLUS_MCP_PYTHON value the launcher must refuse."""
    if kind == "missing":
        return str(tmp_path / "absent" / "python3")
    if kind == "not-executable":
        plain = tmp_path / "plain-python3"
        plain.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        plain.chmod(0o644)
        return str(plain)
    if kind == "relative":
        return "python3"  # the decoy in cwd/PATH must never be chosen
    return kind


def _run_launch(env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LAUNCH)], env=env, cwd=cwd, capture_output=True, text=True, timeout=30, check=False
    )


def _dumped_env(env_log: Path) -> dict[str, str]:
    lines = env_log.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def _launch_env_names() -> set[str]:
    commands = _launch_commands()
    marker = "/usr/bin/env -i"
    assert marker in commands
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", commands.split(marker, 1)[1], re.MULTILINE))


def test_launch_exists_and_is_executable() -> None:
    assert LAUNCH.is_file() and os.access(LAUNCH, os.X_OK)
    assert not LAUNCH.is_symlink()
    assert LAUNCH.resolve().is_relative_to(MCP_ROOT.resolve())


def test_launch_has_fixed_argv_with_no_argument_passthrough() -> None:
    text = _launch_text()
    assert "$@" not in text and "$*" not in text
    assert '"$PYTHON" "$FORK_DIR/solus/server.py"' in text


def test_launch_scrubs_environment_to_the_declared_allowlist() -> None:
    assert _launch_env_names() == DECLARED_ENV_ALLOWLIST


def test_declared_allowlist_is_locals_plus_virtual_env() -> None:
    assert DECLARED_ENV_ALLOWLIST == EXPECTED_ENV_ALLOWLIST
    for name in DECLARED_ENV_ALLOWLIST:
        assert not any(fragment in name for fragment in SECRETISH_FRAGMENTS), name


def test_launch_pins_path_to_a_constant_instead_of_inheriting_it() -> None:
    text = _launch_text()
    assert 'PATH="/usr/bin:/bin"' in text
    assert 'PATH="$PATH' not in text and 'PATH="${PATH' not in text


def test_launch_contains_no_network_or_installer_commands() -> None:
    commands = _launch_commands()
    for token in FORBIDDEN_TOKENS:
        assert token not in commands, token


def test_launch_takes_the_interpreter_only_from_solus_mcp_python() -> None:
    """ADR-031 amendment 2026-11-19: the fork env lives in the app-data
    `mcp-envs/` dir and the companion hands the validated interpreter over as
    SOLUS_MCP_PYTHON — never a vendored-tree `.venv`, never a PATH name."""
    commands = _launch_commands()
    assert ".venv" not in _launch_text(), "bin/launch must not reference an in-tree .venv"
    assert 'PYTHON="${SOLUS_MCP_PYTHON:-}"' in commands
    assert re.search(r"^\s*exit 78$", commands, re.MULTILINE), "missing the exit-78 guard"
    assert not re.search(r"python", commands), "bare/PATH-resolved python in bin/launch"
    assert not re.search(r"(?:^|\s)node\b", commands), "no node in a python fork's launcher"


@pytest.mark.parametrize("value", [None, "", "missing", "not-executable", "relative"])
def test_launch_exits_78_without_a_valid_solus_mcp_python(
    tmp_path: Path, value: str | None
) -> None:
    decoy, decoy_argv, _ = _fake_interpreter(tmp_path / "on-path")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {"PATH": f"{decoy.parent}:/usr/bin:/bin", "SOLUS_MCP_WORKSPACE": str(workspace)}
    if value is not None:
        env["SOLUS_MCP_PYTHON"] = _interpreter_value(tmp_path, value)

    result = _run_launch(env, cwd=decoy.parent)

    assert result.returncode == 78, result.stderr
    assert "SOLUS_MCP_PYTHON" in result.stderr
    assert not decoy_argv.exists(), "the launcher resolved an interpreter from PATH/cwd"


def test_launch_execs_exactly_solus_mcp_python(tmp_path: Path) -> None:
    interpreter, argv_log, env_log = _fake_interpreter(tmp_path / "mcp-envs" / "code" / "bin")
    decoy, decoy_argv, _ = _fake_interpreter(tmp_path / "on-path")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {
        "PATH": f"{decoy.parent}:/usr/bin:/bin",
        "SOLUS_MCP_PYTHON": str(interpreter),
        "SOLUS_MCP_WORKSPACE": str(workspace),
        "PYTHONPATH": "/must/not/forward",
        "AWS_SECRET_ACCESS_KEY": "must-not-forward",
    }

    result = _run_launch(env, cwd=decoy.parent)

    assert result.returncode == 0, result.stderr
    argv = argv_log.read_text(encoding="utf-8").splitlines()
    assert argv == [str(interpreter), str(FORK_DIR.resolve() / "solus" / "server.py")]
    child = _dumped_env(env_log)
    assert set(child) - DECLARED_ENV_ALLOWLIST - SHELL_INJECTED == set()
    assert child["PATH"] == "/usr/bin:/bin"
    assert child["SOLUS_MCP_WORKSPACE"] == str(workspace)
    assert not decoy_argv.exists()


# --- bin/launch.cmd: the Windows twin (content checks; cmd cannot run here) ---


def test_launch_cmd_takes_the_interpreter_only_from_solus_mcp_python() -> None:
    commands = _cmd_commands()
    assert ".venv" not in _cmd_text()
    assert r'"%SOLUS_MCP_PYTHON%" "%FORK_DIR%\solus\server.py"' in commands
    assert 'if "%SOLUS_MCP_PYTHON%"==""' in commands
    assert 'if not exist "%SOLUS_MCP_PYTHON%"' in commands
    assert "exit /b 78" in commands
    assert not re.search(r"python", commands), "bare/PATH-resolved python in launch.cmd"


def test_launch_cmd_refuses_an_empty_workspace() -> None:
    commands = _cmd_commands()
    assert 'if "%SOLUS_MCP_WORKSPACE%"==""' in commands
    assert "exit /b 1" in commands


def test_launch_cmd_has_a_fixed_argv_and_pins_path() -> None:
    commands = _cmd_commands()
    assert not re.search(r"%[0-9*]", commands), "launch.cmd must not forward caller arguments"
    assert 'set "PATH=%SystemRoot%\\System32;%SystemRoot%"' in commands
    assert "%PATH%" not in _cmd_text(), "PATH must be a constant, never inherited"


def test_launch_cmd_contains_no_network_or_installer_commands() -> None:
    text = _cmd_text()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"bin/launch.cmd contains forbidden token {token!r}"


def test_launch_cmd_is_flagged_for_human_security_re_review() -> None:
    assert "PENDING human security re-review" in _cmd_text()


def test_discover_servers_uses_launch_cmd_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("solus_companion.config.sys", SimpleNamespace(platform="win32"))
    by_name = {server.name: server for server in discover_servers(MCP_ROOT)}
    assert by_name["code"].command == LAUNCH_CMD.resolve()


def test_launch_cds_to_the_workspace_and_passes_it_through_empty_when_unset() -> None:
    text = _launch_text()
    assert re.search(r'^\s*cd\s+--\s*"\$WORKSPACE"', text, re.MULTILINE)
    assert 'SOLUS_MCP_WORKSPACE="${SOLUS_MCP_WORKSPACE:-}"' in text


def test_env_allow_is_a_subset_of_the_declared_allowlist() -> None:
    names = {
        line.strip()
        for line in ENV_ALLOW.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert names and names <= DECLARED_ENV_ALLOWLIST
    assert "PATH" not in names and "SOLUS_MCP_WORKSPACE" not in names


def test_discover_servers_finds_the_code_launch_in_a_synthetic_root(tmp_path: Path) -> None:
    fork = tmp_path / "code"
    (fork / "bin").mkdir(parents=True)
    (fork / "allowlist.yaml").write_text("server: code\n", encoding="utf-8")
    copied = fork / "bin" / "launch"
    shutil.copy2(LAUNCH, copied)
    servers = discover_servers(tmp_path, workspace=str(tmp_path))
    assert [server.name for server in servers] == ["code"]
    assert servers[0].command == copied.resolve() and servers[0].args == ()
    assert servers[0].env["SOLUS_MCP_WORKSPACE"] == str(tmp_path)


def test_discover_servers_finds_code_in_the_real_tree() -> None:
    by_name = {server.name: server for server in discover_servers(MCP_ROOT)}
    assert "code" in by_name
    assert by_name["code"].command == LAUNCH.resolve()
    assert by_name["code"].cwd == FORK_DIR.resolve()
    assert set(by_name["code"].env_passthrough) <= DECLARED_ENV_ALLOWLIST
