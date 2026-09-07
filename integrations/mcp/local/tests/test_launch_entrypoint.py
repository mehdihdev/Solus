"""SOLUSDEV-249 — the `local` server's Solus-authored launch entrypoint.

Locks the ADR-031 / `integrations/mcp/README.md` launcher law for the
Solus-authored (no-upstream) `local` server, mirroring the kicad fork's pins:

- `bin/launch` exists, is executable, and resolves INSIDE `integrations/mcp/`;
- fixed argv (no `$@`/`$*`), `env -i` scrub to the declared allowlist, PATH
  pinned to a constant, zero network/installer commands, the fork-private
  interpreter only, `cd` to the companion-passed workspace;
- the declared allowlist is SMALLER than kicad's: no `KICAD_*` knobs, and no
  secret-shaped name ever;
- `solus/env.allow` (the companion's mechanical passthrough list) never
  widens what the launcher itself would pass;
- `solus_companion.config.discover_servers` discovers the server.
"""

import os
import re
import shutil
from pathlib import Path

from solus_companion.config import discover_servers

# The bootstrap module must run before the overlay import — keep it first.
from .local_paths import ENV_ALLOW, FORK_DIR, LAUNCH, MCP_ROOT, overlay_module  # isort: skip

_env_allowlist = overlay_module("env_allowlist")
DECLARED_ENV_ALLOWLIST: frozenset[str] = _env_allowlist.CHILD_ENV_ALLOWLIST

EXPECTED_ENV_ALLOWLIST = frozenset(
    {"HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "PATH", "SOLUS_MCP_WORKSPACE"}
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
    """Script text with comment lines stripped (shebang included)."""
    lines = [line for line in _launch_text().splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines)


def _launch_env_names() -> set[str]:
    commands = _launch_commands()
    marker = "/usr/bin/env -i"
    assert marker in commands, "bin/launch must scrub the environment with env -i"
    env_block = commands.split(marker, 1)[1]
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", env_block, re.MULTILINE))


# --- existence, executability, containment ------------------------------------


def test_launch_exists_and_is_executable() -> None:
    assert LAUNCH.is_file(), "integrations/mcp/local/bin/launch is missing"
    assert os.access(LAUNCH, os.X_OK), "bin/launch is not executable"


def test_launch_is_a_regular_file_resolving_inside_mcp_root() -> None:
    assert not LAUNCH.is_symlink()
    assert LAUNCH.resolve().is_relative_to(MCP_ROOT.resolve())


# --- fixed argv, scrubbed env, no network ---------------------------------------


def test_launch_has_fixed_argv_with_no_argument_passthrough() -> None:
    text = _launch_text()
    assert "$@" not in text
    assert "$*" not in text
    assert '"$PYTHON" "$FORK_DIR/solus/server.py"' in text, (
        "bin/launch must exec the fixed private interpreter against solus/server.py"
    )


def test_launch_scrubs_environment_to_the_declared_allowlist() -> None:
    assert _launch_env_names() == DECLARED_ENV_ALLOWLIST


def test_declared_allowlist_is_exactly_the_local_set() -> None:
    """Smaller than kicad's: the generic POSIX basics, the pinned PATH, and
    the one workspace knob. No tool-specific knobs at all."""
    assert DECLARED_ENV_ALLOWLIST == EXPECTED_ENV_ALLOWLIST
    assert not any(name.startswith("KICAD_") for name in DECLARED_ENV_ALLOWLIST)


def test_declaration_admits_no_secret_shaped_names() -> None:
    for name in DECLARED_ENV_ALLOWLIST:
        assert not any(fragment in name for fragment in SECRETISH_FRAGMENTS), name


def test_launch_pins_path_to_a_constant_instead_of_inheriting_it() -> None:
    text = _launch_text()
    assert 'PATH="/usr/bin:/bin"' in text
    assert 'PATH="$PATH' not in text and 'PATH="${PATH' not in text


def test_launch_contains_no_network_or_installer_commands() -> None:
    text = _launch_text()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"bin/launch contains forbidden token {token!r}"


def test_launch_uses_only_the_fixed_private_interpreter() -> None:
    commands = _launch_commands()
    assert '.venv/bin/python3"' in commands
    for match in re.finditer(r"\S*python3?\b", commands):
        assert match.group().endswith(".venv/bin/python3"), match.group()
    assert not re.search(r"(?:^|\s)node\b", commands)


def test_launch_cds_to_the_companion_passed_workspace_env_var() -> None:
    text = _launch_text()
    assert "SOLUS_MCP_WORKSPACE" in text
    assert re.search(r'^\s*cd\s+--\s*"\$WORKSPACE"', text, re.MULTILINE)


def test_launch_passes_the_workspace_through_empty_when_unset() -> None:
    """The child must see an EMPTY SOLUS_MCP_WORKSPACE (so workspace_root()
    fails closed), never the fork-dir cwd fallback."""
    assert 'SOLUS_MCP_WORKSPACE="${SOLUS_MCP_WORKSPACE:-}"' in _launch_text()


# --- solus/env.allow: the companion's passthrough never widens the launcher ---


def test_env_allow_is_a_subset_of_the_declared_allowlist() -> None:
    names = {
        line.strip()
        for line in ENV_ALLOW.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert names, "solus/env.allow declares nothing"
    assert names <= DECLARED_ENV_ALLOWLIST
    # PATH is a launcher CONSTANT and the workspace is companion-SET: neither
    # is something the fork should ask to inherit from the host.
    assert "PATH" not in names
    assert "SOLUS_MCP_WORKSPACE" not in names


# --- companion discovery ---------------------------------------------------------


def test_discover_servers_finds_the_local_launch_in_a_synthetic_root(tmp_path: Path) -> None:
    fork = tmp_path / "local"
    (fork / "bin").mkdir(parents=True)
    (fork / "allowlist.yaml").write_text("server: local\n", encoding="utf-8")
    copied = fork / "bin" / "launch"
    shutil.copy2(LAUNCH, copied)

    servers = discover_servers(tmp_path, workspace=str(tmp_path))

    assert [server.name for server in servers] == ["local"]
    assert servers[0].command == copied.resolve()
    assert servers[0].args == ()
    assert servers[0].env["SOLUS_MCP_WORKSPACE"] == str(tmp_path)


def test_discover_servers_finds_local_in_the_real_tree() -> None:
    servers = discover_servers(MCP_ROOT)
    by_name = {server.name: server for server in servers}
    assert "local" in by_name
    assert by_name["local"].command == LAUNCH.resolve()
    assert by_name["local"].cwd == FORK_DIR.resolve()
    assert set(by_name["local"].env_passthrough) <= DECLARED_ENV_ALLOWLIST
