"""SOLUSDEV-102 ALT-3 — the env-allowlist declaration lives in solus/ and the
launchers agree with it; the whole upstream env surface is declared and stays
scrubbed; workspace resolution fails closed on an unset/empty
SOLUS_MCP_WORKSPACE."""

import re
from pathlib import Path

import pytest

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import LAUNCH, LAUNCH_CMD, UPSTREAM_SRC, overlay_module  # isort: skip

_env_allowlist = overlay_module("env_allowlist")
_workspace = overlay_module("workspace")

CHILD_ENV_ALLOWLIST: frozenset[str] = _env_allowlist.CHILD_ENV_ALLOWLIST
UPSTREAM_ENV_NEVER_FORWARDED: frozenset[str] = _env_allowlist.UPSTREAM_ENV_NEVER_FORWARDED
WorkspaceNotConfiguredError: type[Exception] = _workspace.WorkspaceNotConfiguredError
workspace_root = _workspace.workspace_root

SECRETISH_FRAGMENTS = ("SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "APIKEY", "API_KEY")

#: Env-name shapes upstream reads (grep over upstream/src): the eda-agent
#: namespaces, the part-sourcing endpoints/credentials, the KiCad library
#: discovery family, and the Windows profile roots. Every match must be
#: declared — either allowlisted (the pins) or in the scrub set.
_ENV_NAME_PATTERN = re.compile(
    r"_?EDA_AGENT_[A-Z0-9_]+"
    r"|PARTS_REGISTRY_[A-Z0-9_]+"
    r"|EASYEDA_[A-Z0-9_]+"
    r"|KICAD[0-9]*_(?:SYMBOL|FOOTPRINT|3DMODEL)_DIR"
    r"|USERPROFILE|LOCALAPPDATA"
    r"|DIGIKEY_[A-Z0-9_]+|MOUSER_[A-Z0-9_]+|NEXAR_[A-Z0-9_]+"
    r"|ELEMENT14_[A-Z0-9_]+|TME_[A-Z0-9_]+"
)

#: Pattern matches that are NOT environment variables (Python constants).
_KNOWN_NON_ENV_NAMES = frozenset({"EASYEDA_UNIT_MIL"})


def _launch_env_names() -> set[str]:
    lines = [
        line
        for line in LAUNCH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    commands = "\n".join(lines)
    marker = "/usr/bin/env -i"
    assert marker in commands, "bin/launch must scrub the environment with env -i"
    env_block = commands.split(marker, 1)[1]
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", env_block, re.MULTILINE))


def _launch_command_text() -> str:
    """bin/launch with comment lines stripped."""
    return "\n".join(
        line
        for line in LAUNCH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def _cmd_command_text() -> str:
    """bin/launch.cmd with `rem` comment lines stripped."""
    return "\n".join(
        line
        for line in LAUNCH_CMD.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().lower().startswith("rem")
    )


# --- the declaration and the launcher agree ------------------------------------


def test_launch_env_block_matches_the_solus_declaration() -> None:
    """solus/env_allowlist.py is the single written declaration (README §
    launcher law); the shell script must assign exactly that set."""
    assert _launch_env_names() == CHILD_ENV_ALLOWLIST


def test_declaration_includes_the_overlay_knobs_and_pins() -> None:
    assert "SOLUS_MCP_WORKSPACE" in CHILD_ENV_ALLOWLIST
    assert "PATH" in CHILD_ENV_ALLOWLIST
    for pin in ("EDA_AGENT_BACKEND", "EDA_AGENT_WORKSPACE", "EDA_AGENT_POINTER_FILE"):
        assert pin in CHILD_ENV_ALLOWLIST, f"launcher-set pin {pin} missing from the declaration"


def test_declaration_admits_no_secret_shaped_names() -> None:
    for name in CHILD_ENV_ALLOWLIST:
        assert not any(fragment in name for fragment in SECRETISH_FRAGMENTS), (
            f"secret-shaped env var {name} in the child allowlist"
        )


def test_launch_execs_the_solus_entry_not_upstream() -> None:
    text = LAUNCH.read_text(encoding="utf-8")
    assert '"$PYTHON" "$FORK_DIR/solus/server.py"' in text
    commands = _launch_command_text()
    assert "eda_agent" not in commands, (
        "the launcher must exec the Solus entry, never upstream's eda_agent module"
    )
    assert "upstream/" not in commands, "the launcher must never reach into upstream/ directly"


# --- the scrub set ---------------------------------------------------------------


def test_scrub_set_is_disjoint_from_the_child_allowlist() -> None:
    overlap = UPSTREAM_ENV_NEVER_FORWARDED & CHILD_ENV_ALLOWLIST
    assert not overlap, f"names both allowlisted and scrubbed: {sorted(overlap)}"


def test_launchers_mention_no_scrubbed_name() -> None:
    """`env -i` drops the scrub set mechanically; neither launcher may name a
    scrubbed variable in command text (a passthrough would be drift, an
    assignment would be an undeclared knob)."""
    for text, label in (
        (_launch_command_text(), "bin/launch"),
        (_cmd_command_text(), "launch.cmd"),
    ):
        for name in sorted(UPSTREAM_ENV_NEVER_FORWARDED):
            assert name not in text, f"{label} mentions scrubbed env name {name}"


def test_every_upstream_env_name_is_declared() -> None:
    """Drift guard: every env-shaped name upstream/src reads must be either an
    allowlisted pin or in the scrub set — a re-vendor that grows the env
    surface fails HERE instead of silently widening the child environment."""
    found: set[str] = set()
    for path in UPSTREAM_SRC.rglob("*.py"):
        found.update(_ENV_NAME_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    declared = CHILD_ENV_ALLOWLIST | UPSTREAM_ENV_NEVER_FORWARDED | _KNOWN_NON_ENV_NAMES
    undeclared = sorted(found - declared)
    assert not undeclared, f"upstream env names missing from the declarations: {undeclared}"


def test_scrub_set_covers_the_known_upstream_surface() -> None:
    """Spot-pin the load-bearing names so a declaration rewrite cannot
    quietly drop them."""
    for name in (
        "EDA_AGENT_TOOLSET",
        "EDA_AGENT_ALTIUM_PROCESS",
        "_EDA_AGENT_BACKEND_REEXEC",
        "PARTS_REGISTRY_URL",
        "EASYEDA_API_BASE",
        "USERPROFILE",
        "LOCALAPPDATA",
        "DIGIKEY_CLIENT_SECRET",
        "MOUSER_API_KEY",
    ):
        assert name in UPSTREAM_ENV_NEVER_FORWARDED, f"{name} missing from the scrub set"


# --- workspace resolution --------------------------------------------------------


def test_workspace_root_honors_the_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    assert workspace_root() == tmp_path.resolve()


def test_workspace_root_refuses_when_the_env_var_is_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail closed rather than defaulting to cwd — an unconfigured workspace
    must never be silently treated as confined."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotConfiguredError):
        workspace_root()


def test_workspace_root_refuses_on_an_empty_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", "")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotConfiguredError):
        workspace_root()
