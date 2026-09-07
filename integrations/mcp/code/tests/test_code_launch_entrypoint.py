"""SOLUSDEV-250 — the `code` server's Solus-authored launch entrypoint,
mirroring the local fork's pins: fixed argv, `env -i` scrub to the declared
allowlist (local's set + VIRTUAL_ENV), PATH pinned to a constant, zero
network/installer commands at LAUNCH, the fork-private interpreter only,
`cd` to the companion-passed workspace, companion discovery."""

import os
import re
import shutil
from pathlib import Path

from solus_companion.config import discover_servers

from code_paths import ENV_ALLOW, FORK_DIR, LAUNCH, MCP_ROOT, overlay_module  # isort: skip

DECLARED_ENV_ALLOWLIST: frozenset[str] = overlay_module("env_allowlist").CHILD_ENV_ALLOWLIST

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


def test_launch_uses_only_the_fixed_private_interpreter() -> None:
    commands = _launch_commands()
    assert '.venv/bin/python3"' in commands
    for match in re.finditer(r"\S*python3?\b", commands):
        assert match.group().endswith(".venv/bin/python3"), match.group()


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
