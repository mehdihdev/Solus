"""SOLUSDEV-102 ALT-3 — the altium fork's Solus-authored launch entrypoints.

Locks the ADR-031 / `integrations/mcp/README.md` launcher law for the
vendored `salitronic/eda-agent` fork:

- `bin/launch` exists, is executable, and resolves INSIDE `integrations/mcp/`
  (no symlink escape) so the companion's `_launch_command` guard accepts it;
- the script has a FIXED argv (no `$@`/`$*` passthrough), a scrubbed
  environment (explicit `env -i` allowlist, PATH pinned to a constant), and
  zero network/installer commands or PATH-resolved interpreters;
- the fork-specific IPC pins: upstream drives Altium through a file-drop IPC
  workspace located via a MACHINE-GLOBAL pointer file unless
  `EDA_AGENT_POINTER_FILE` redirects it (upstream/src/eda_agent/config.py) —
  so the launcher SETS `EDA_AGENT_BACKEND`, `EDA_AGENT_WORKSPACE`, and
  `EDA_AGENT_POINTER_FILE`, each derived from `SOLUS_MCP_WORKSPACE`, never
  inherited from the parent environment;
- `bin/launch.cmd` (human-approved Windows twin — Altium runs only on
  Windows) pins the same entry/EDA_AGENT_* posture and takes the interpreter
  only from `SOLUS_MCP_PYTHON` (ADR-031 amendment 2026-11-19); cmd cannot
  scrub the environment, so the companion's child-env allowlist
  (`solus_companion.supervisor._child_env`) is the authoritative scrub there
  and the script sets only the pins (residual recorded in SECURITY_REVIEW.md
  by a later task);
- `solus_companion.config.discover_servers` accepts the launcher.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from solus_companion.config import discover_servers

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import FORK_DIR, LAUNCH, LAUNCH_CMD, MCP_ROOT, overlay_module  # isort: skip

_env_allowlist = overlay_module("env_allowlist")
DECLARED_ENV_ALLOWLIST: frozenset[str] = _env_allowlist.CHILD_ENV_ALLOWLIST

#: Launcher-SET pins — assigned values derived from SOLUS_MCP_WORKSPACE,
#: never inherited from the parent environment.
LAUNCHER_SET_PINS = frozenset(
    {"EDA_AGENT_BACKEND", "EDA_AGENT_WORKSPACE", "EDA_AGENT_POINTER_FILE"}
)

# Network / installer / PATH-resolved-launcher tokens banned from the script
# text outright (README rule 4: zero network I/O, no installs at launch).
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


def _launch_text() -> str:
    return LAUNCH.read_text(encoding="utf-8")


def _launch_commands() -> str:
    """Script text with comment lines stripped (shebang included)."""
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


# --- bin/launch: existence, executability, containment ----------------------


def test_launch_exists_and_is_executable() -> None:
    assert LAUNCH.is_file(), "integrations/mcp/altium/bin/launch is missing"
    assert os.access(LAUNCH, os.X_OK), "bin/launch is not executable"
    # git mode 100755 comes from the OWNER execute bit (the os.access root
    # quirk makes X_OK alone unreliable in CI containers).
    assert LAUNCH.lstat().st_mode & stat.S_IXUSR, "bin/launch lacks the owner-execute bit"


def test_launch_is_a_regular_file_resolving_inside_mcp_root() -> None:
    assert not LAUNCH.is_symlink(), "bin/launch must be a regular file, not a symlink"
    resolved = LAUNCH.resolve()
    assert resolved.is_relative_to(MCP_ROOT.resolve()), (
        "bin/launch resolves outside integrations/mcp/ — the companion guard would refuse it"
    )


# --- bin/launch: fixed argv, scrubbed env, no network ------------------------


def test_launch_has_fixed_argv_with_no_argument_passthrough() -> None:
    text = _launch_text()
    assert "$@" not in text, "bin/launch must not forward caller arguments"
    assert "$*" not in text, "bin/launch must not forward caller arguments"
    assert '"$PYTHON" "$FORK_DIR/solus/server.py"' in text, (
        "bin/launch must exec the fixed private interpreter against the "
        "Solus overlay entrypoint (ALT-5: solus/server.py replaces upstream's "
        "eda_agent entry) with a fixed argv"
    )


def test_launch_scrubs_environment_to_the_declared_allowlist() -> None:
    commands = _launch_commands()
    marker = "/usr/bin/env -i"
    assert marker in commands, "bin/launch must clear the environment with env -i"
    env_block = commands.split(marker, 1)[1]
    passed = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", env_block, re.MULTILINE))
    assert passed == DECLARED_ENV_ALLOWLIST, (
        f"env allowlist drift: script assigns {sorted(passed)}, "
        f"declared {sorted(DECLARED_ENV_ALLOWLIST)}"
    )


def test_launch_passes_non_pin_names_through_and_only_those() -> None:
    commands = _launch_commands()
    env_block = commands.split("/usr/bin/env -i", 1)[1]
    for name in sorted(DECLARED_ENV_ALLOWLIST - LAUNCHER_SET_PINS - {"PATH"}):
        assert f'{name}="${{{name}:-}}"' in env_block, (
            f"{name} must be passed through in the empty-defaulting form"
        )


def test_launch_sets_the_ipc_pins_and_never_inherits_them() -> None:
    text = _launch_text()
    assert 'IPC_DIR="$WORKSPACE/.eda-agent-ipc"' in text, (
        "the IPC directory must be derived from the Solus workspace"
    )
    assert 'EDA_AGENT_BACKEND="altium"' in text
    assert 'EDA_AGENT_WORKSPACE="$IPC_DIR"' in text
    assert 'EDA_AGENT_POINTER_FILE="$IPC_DIR/workspace-path.txt"' in text
    assert '"${EDA_AGENT' not in text, (
        "no EDA_AGENT_* variable may ever be inherited from the parent environment"
    )


def test_launch_pins_path_to_a_constant_instead_of_inheriting_it() -> None:
    text = _launch_text()
    assert 'PATH="/usr/bin:/bin"' in text, (
        "PATH must be a fixed constant for the child, never inherited"
    )
    assert 'PATH="$PATH' not in text and 'PATH="${PATH' not in text


def test_launch_contains_no_network_or_installer_commands() -> None:
    text = _launch_text()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"bin/launch contains forbidden token {token!r}"


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
    interpreter, argv_log, env_log = _fake_interpreter(tmp_path / "mcp-envs" / "altium" / "bin")
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
    assert set(child) - DECLARED_ENV_ALLOWLIST - _SHELL_INJECTED == set()
    assert child["PATH"] == "/usr/bin:/bin"
    assert child["SOLUS_MCP_WORKSPACE"] == str(workspace)
    assert not decoy_argv.exists()


def test_launch_cds_to_the_companion_passed_workspace_env_var() -> None:
    text = _launch_text()
    assert "SOLUS_MCP_WORKSPACE" in text, (
        "the workspace must arrive via the documented SOLUS_MCP_WORKSPACE env var"
    )
    assert re.search(r'^\s*cd\s+--\s*"\$WORKSPACE"', text, re.MULTILINE), (
        "bin/launch must cd to the validated workspace before exec"
    )


# --- bin/launch.cmd: the Windows twin ----------------------------------------


def test_launch_cmd_takes_the_interpreter_only_from_solus_mcp_python() -> None:
    """ADR-031 amendment 2026-11-19: no in-tree `.venv` on Windows either."""
    assert LAUNCH_CMD.is_file(), "integrations/mcp/altium/bin/launch.cmd is missing"
    commands = _cmd_commands()
    assert ".venv" not in _cmd_text()
    assert r'"%SOLUS_MCP_PYTHON%" "%FORK_DIR%\solus\server.py"' in commands
    assert 'if "%SOLUS_MCP_PYTHON%"==""' in commands
    assert 'if not exist "%SOLUS_MCP_PYTHON%"' in commands
    assert "exit /b 78" in commands
    assert not re.search(r"python", commands), "bare/PATH-resolved python in launch.cmd"
    assert not re.search(r"%[0-9*]", commands), "launch.cmd must not forward caller arguments"


def test_launch_cmd_is_flagged_for_human_security_re_review() -> None:
    assert "PENDING human security re-review" in _cmd_text()


def test_launch_cmd_fails_closed_when_the_workspace_is_unset() -> None:
    commands = _cmd_commands()
    assert 'if "%SOLUS_MCP_WORKSPACE%"==""' in commands, (
        "launch.cmd must refuse to start without SOLUS_MCP_WORKSPACE"
    )
    assert "exit /b 1" in commands


def test_launch_cmd_sets_the_ipc_pins_derived_from_the_workspace() -> None:
    commands = _cmd_commands()
    assert 'set "EDA_AGENT_BACKEND=altium"' in commands
    assert r'set "EDA_AGENT_WORKSPACE=%SOLUS_MCP_WORKSPACE%\.eda-agent-ipc"' in commands
    assert (
        r'set "EDA_AGENT_POINTER_FILE=%SOLUS_MCP_WORKSPACE%\.eda-agent-ipc\workspace-path.txt"'
        in commands
    )
    # The pins are SET, never expanded from an inherited EDA_AGENT_* value.
    assert "%EDA_AGENT" not in _cmd_text(), (
        "launch.cmd must never read an inherited EDA_AGENT_* variable"
    )


def test_launch_cmd_documents_the_companion_scrub_residual() -> None:
    text = _cmd_text()
    assert "_child_env" in text, (
        "launch.cmd must state that the companion's _child_env allowlist is "
        "the authoritative scrub on Windows"
    )
    assert "SECURITY_REVIEW.md" in text, (
        "launch.cmd must reference where the no-env-scrub residual is recorded"
    )


def test_launch_cmd_contains_no_network_or_installer_commands() -> None:
    text = _cmd_text()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"bin/launch.cmd contains forbidden token {token!r}"


# --- companion discovery ------------------------------------------------------


def test_discover_servers_finds_the_altium_launch(tmp_path: Path) -> None:
    """The real `bin/launch`, placed in a minimal integrations root, passes the
    companion's paranoid discovery guard (exists + executable + inside-root).
    A synthetic root is used because `allowlist.yaml` is a later ALT task's
    deliverable."""
    fork = tmp_path / "altium"
    (fork / "bin").mkdir(parents=True)
    (fork / "allowlist.yaml").write_text("server: altium\n", encoding="utf-8")
    copied = fork / "bin" / "launch"
    shutil.copy2(LAUNCH, copied)

    servers = discover_servers(tmp_path)

    assert [server.name for server in servers] == ["altium"]
    assert servers[0].command == copied.resolve()
    assert servers[0].args == ()


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_discover_servers_finds_altium_in_the_real_tree(
    platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fork = MCP_ROOT / "altium"
    if not (fork / "allowlist.yaml").is_file():
        pytest.skip(
            "allowlist.yaml is a later ALT task's deliverable; real-tree discovery arms then"
        )
    monkeypatch.setattr("solus_companion.config.sys", SimpleNamespace(platform=platform))
    servers = discover_servers(MCP_ROOT)
    by_name = {server.name: server for server in servers}
    assert "altium" in by_name
    if platform == "win32":
        assert by_name["altium"].command == LAUNCH_CMD.resolve()
        assert by_name["altium"].unavailable_reason is None
    else:
        host = "Linux" if platform == "linux" else "macOS"
        assert by_name["altium"].command is None
        assert by_name["altium"].unavailable_reason == f"Altium Designer is not available on {host}"


# --- M3 / T4-POSIX: the POSIX launcher actually scrubs the child env --------------
#
# The launcher-text tests above prove bin/launch is WRITTEN to scrub with
# `env -i` + the allowlist; this executes it end-to-end against a stub
# interpreter that dumps its own environment, proving the child process
# really sees only the declared allowlist (plus the handful of variables the
# POSIX shell injects into any process it starts — PWD/SHLVL/_).

#: Names a POSIX /bin/sh sets on the process it execs, outside the launcher's
#: control and harmless (not secret- or path-bearing).
_SHELL_INJECTED = frozenset({"PWD", "SHLVL", "_", "OLDPWD"})


@pytest.mark.skipif(os.name != "posix", reason="bin/launch is the POSIX launcher")
def test_launch_child_env_is_scrubbed_to_the_allowlist(tmp_path: Path) -> None:
    """Exec bin/launch with SOLUS_MCP_PYTHON pointing at a stub interpreter
    that dumps its environment; every key the child sees must be in
    CHILD_ENV_ALLOWLIST (modulo shell-injected names)."""
    stub, _, env_log = _fake_interpreter(tmp_path / "mcp-envs" / "altium" / "bin")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # A parent environment stuffed with names the launcher must NOT forward —
    # secrets, upstream knobs, Windows profile roots.
    parent = {
        **os.environ,
        "SOLUS_MCP_WORKSPACE": str(workspace),
        "SOLUS_MCP_PYTHON": str(stub),
        "MOUSER_API_KEY": "must-not-forward",
        "USERPROFILE": "C:/Users/leak",
        "EDA_AGENT_CACHE_DIR": "/tmp/leak",
        "AWS_SECRET_ACCESS_KEY": "leak",
    }
    subprocess.run([str(LAUNCH)], env=parent, check=True, timeout=30)

    observed = set(_dumped_env(env_log))
    leaked = observed - DECLARED_ENV_ALLOWLIST - _SHELL_INJECTED
    assert leaked == set(), f"the launcher forwarded non-allowlisted names: {sorted(leaked)}"
    for secret in ("MOUSER_API_KEY", "USERPROFILE", "EDA_AGENT_CACHE_DIR", "AWS_SECRET_ACCESS_KEY"):
        assert secret not in observed, f"{secret} leaked into the child environment"
