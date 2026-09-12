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
  Windows) pins the same interpreter/entry/EDA_AGENT_* posture; cmd cannot
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
from pathlib import Path

import pytest
from solus_companion.config import discover_servers

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import LAUNCH, LAUNCH_CMD, MCP_ROOT, overlay_module  # isort: skip

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


def test_launch_uses_only_the_fixed_private_interpreter() -> None:
    commands = _launch_commands()
    assert '.venv/bin/python3"' in commands, (
        "the interpreter must be the fork's private .venv/bin/python3"
    )
    for match in re.finditer(r"\S*python3?\b", commands):
        assert match.group().endswith(".venv/bin/python3"), (
            f"PATH-resolved interpreter in bin/launch: {match.group()!r}"
        )
    assert not re.search(r"(?:^|\s)node\b", commands), "no node in a python fork's launcher"


def test_launch_cds_to_the_companion_passed_workspace_env_var() -> None:
    text = _launch_text()
    assert "SOLUS_MCP_WORKSPACE" in text, (
        "the workspace must arrive via the documented SOLUS_MCP_WORKSPACE env var"
    )
    assert re.search(r'^\s*cd\s+--\s*"\$WORKSPACE"', text, re.MULTILINE), (
        "bin/launch must cd to the validated workspace before exec"
    )


# --- bin/launch.cmd: the Windows twin ----------------------------------------


def test_launch_cmd_exists_and_pins_the_private_interpreter() -> None:
    assert LAUNCH_CMD.is_file(), "integrations/mcp/altium/bin/launch.cmd is missing"
    commands = _cmd_commands()
    assert r".venv\Scripts\python.exe" in commands, (
        "launch.cmd must pin the fork-private Windows interpreter"
    )
    assert r"solus\server.py" in commands, "launch.cmd must run the Solus overlay entrypoint"


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


def test_discover_servers_finds_altium_in_the_real_tree() -> None:
    fork = MCP_ROOT / "altium"
    if not (fork / "allowlist.yaml").is_file():
        pytest.skip(
            "allowlist.yaml is a later ALT task's deliverable; real-tree discovery arms then"
        )
    servers = discover_servers(MCP_ROOT)
    by_name = {server.name: server for server in servers}
    assert "altium" in by_name
    assert by_name["altium"].command == LAUNCH.resolve()


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
    """Exec a COPY of bin/launch whose fixed private interpreter is replaced
    by a stub that dumps its environment; every key the child sees must be in
    CHILD_ENV_ALLOWLIST (modulo shell-injected names)."""
    fork = tmp_path / "altium"
    (fork / "bin").mkdir(parents=True)
    (fork / "solus").mkdir()
    (fork / ".venv" / "bin").mkdir(parents=True)
    shutil.copy2(LAUNCH, fork / "bin" / "launch")
    (fork / "solus" / "server.py").write_text("", encoding="utf-8")
    dump = fork / "child-env.txt"
    stub = fork / ".venv" / "bin" / "python3"
    # env -i pins PATH=/usr/bin:/bin, so /usr/bin/env resolves; the stub runs
    # in the workspace cwd and writes the child environment there.
    stub.write_text(f'#!/bin/sh\n/usr/bin/env > "{dump}"\n', encoding="utf-8")
    stub.chmod(0o755)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # A parent environment stuffed with names the launcher must NOT forward —
    # secrets, upstream knobs, Windows profile roots.
    parent = {
        **os.environ,
        "SOLUS_MCP_WORKSPACE": str(workspace),
        "MOUSER_API_KEY": "must-not-forward",
        "USERPROFILE": "C:/Users/leak",
        "EDA_AGENT_CACHE_DIR": "/tmp/leak",
        "AWS_SECRET_ACCESS_KEY": "leak",
    }
    import subprocess  # noqa: PLC0415 — test-local, argv list only, no shell

    subprocess.run([str(fork / "bin" / "launch")], env=parent, check=True, timeout=30)

    observed = {
        line.split("=", 1)[0]
        for line in dump.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }
    leaked = observed - DECLARED_ENV_ALLOWLIST - _SHELL_INJECTED
    assert leaked == set(), f"the launcher forwarded non-allowlisted names: {sorted(leaked)}"
    for secret in ("MOUSER_API_KEY", "USERPROFILE", "EDA_AGENT_CACHE_DIR", "AWS_SECRET_ACCESS_KEY"):
        assert secret not in observed, f"{secret} leaked into the child environment"
