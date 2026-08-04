"""SOLUSDEV-100 T1b — the env-allowlist declaration lives in solus/ and the
launcher agrees with it; workspace resolution and artifact confinement."""

import re
from pathlib import Path

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line first.
from test_overlay_support import LAUNCH  # isort: skip

from solus.env_allowlist import CHILD_ENV_ALLOWLIST
from solus.workspace import (
    WorkspaceNotConfiguredError,
    artifact_destination,
    to_workspace_relative,
    workspace_root,
)

SECRETISH_FRAGMENTS = ("SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "APIKEY", "API_KEY")


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


# --- the declaration and the launcher agree ------------------------------------


def test_launch_env_block_matches_the_solus_declaration() -> None:
    """solus/env_allowlist.py is the single written declaration (README §
    launcher law); the shell script must pass exactly that set."""
    assert _launch_env_names() == CHILD_ENV_ALLOWLIST


def test_declaration_includes_the_overlay_knobs() -> None:
    assert "SOLUS_MCP_WORKSPACE" in CHILD_ENV_ALLOWLIST
    assert "KICAD_CLI_PATH" in CHILD_ENV_ALLOWLIST
    assert "PATH" in CHILD_ENV_ALLOWLIST


def test_declaration_admits_no_secret_shaped_names() -> None:
    for name in CHILD_ENV_ALLOWLIST:
        assert not any(fragment in name for fragment in SECRETISH_FRAGMENTS), (
            f"secret-shaped env var {name} in the child allowlist"
        )


def test_launch_execs_the_solus_entry_not_upstream_main() -> None:
    text = LAUNCH.read_text(encoding="utf-8")
    assert '"$PYTHON" "$FORK_DIR/solus/server.py"' in text
    assert "upstream/main.py" not in text.replace("# ", ""), (
        "the launcher must exec the Solus entry, never upstream/main.py"
    )


# --- workspace resolution --------------------------------------------------------


def test_workspace_root_honors_the_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    assert workspace_root() == tmp_path.resolve()


def test_workspace_root_refuses_when_the_env_var_is_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """H3: fail closed rather than defaulting to cwd — an unconfigured
    workspace must never be silently treated as confined."""
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


def test_artifact_destination_refuses_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """H3: every confined operation built on workspace_root() must refuse
    cleanly rather than resolve against an arbitrary cwd."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotConfiguredError):
        artifact_destination("board-netlist.xml")


# --- artifact confinement ---------------------------------------------------------


def test_artifact_destination_stays_inside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    destination = artifact_destination("board-netlist.xml")
    assert destination.resolve().is_relative_to(tmp_path.resolve())
    assert destination.parent.is_dir(), "the artifact directory must exist after resolution"
    relative = to_workspace_relative(destination)
    assert not Path(relative).is_absolute()
    assert (tmp_path / relative).resolve() == destination.resolve()


@pytest.mark.parametrize(
    "hostile",
    [
        "../escape.xml",
        "..",
        ".",
        "",
        "/etc/passwd",
        "nested/dir.xml",
        "a/../../b.xml",
        "..\\windows.xml",
    ],
)
def test_artifact_destination_refuses_traversal_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostile: str
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    with pytest.raises(ValueError):
        artifact_destination(hostile)
