"""SOLUSDEV-102 ALT-3 — `solus/pointer.py`: the confined file-drop IPC paths.

Upstream's DelphiScript bridge locates its IPC workspace through a pointer
file whose DEFAULT path is machine-global (upstream/src/eda_agent/config.py).
The Solus overlay never uses that default: both the IPC directory and the
pointer file are pure functions of the Solus workspace root, must RESOLVE
(symlinks included) inside it, and match the launcher pins byte-for-byte.
An unconfigured workspace refuses upstream of these functions
(`solus.workspace.workspace_root()`), so the machine-global path is
unreachable on every code path.
"""

from pathlib import Path

import pytest

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import LAUNCH, LAUNCH_CMD, SOLUS_DIR, overlay_module  # isort: skip

_pointer = overlay_module("pointer")
_workspace = overlay_module("workspace")

IPC_DIR_NAME: str = _pointer.IPC_DIR_NAME
POINTER_FILE_NAME: str = _pointer.POINTER_FILE_NAME
PointerConfinementError: type[Exception] = _pointer.PointerConfinementError
ipc_workspace_dir = _pointer.ipc_workspace_dir
pointer_file_path = _pointer.pointer_file_path
WorkspaceNotConfiguredError: type[Exception] = _workspace.WorkspaceNotConfiguredError
workspace_root = _workspace.workspace_root


# --- happy path: both paths land inside the workspace -----------------------------


def test_ipc_dir_is_the_confined_subdirectory(tmp_path: Path) -> None:
    ipc = ipc_workspace_dir(tmp_path)
    assert ipc == (tmp_path / IPC_DIR_NAME).resolve()
    assert ipc.is_relative_to(tmp_path.resolve())


def test_pointer_file_lives_inside_the_ipc_dir(tmp_path: Path) -> None:
    pointer = pointer_file_path(tmp_path)
    assert pointer == (tmp_path / IPC_DIR_NAME / POINTER_FILE_NAME).resolve()
    assert pointer.parent == ipc_workspace_dir(tmp_path)
    assert pointer.is_relative_to(tmp_path.resolve())


def test_a_symlinked_workspace_root_is_normalized_not_refused(tmp_path: Path) -> None:
    """A workspace that is ITSELF a symlink is legitimate — everything
    resolves consistently under the real root."""
    real = tmp_path / "real-workspace"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert ipc_workspace_dir(alias) == (real / IPC_DIR_NAME).resolve()
    assert pointer_file_path(alias).is_relative_to(real.resolve())


# --- the launcher pins and this module agree ---------------------------------------


def test_names_match_the_launcher_pins_exactly() -> None:
    launch_text = LAUNCH.read_text(encoding="utf-8")
    cmd_text = LAUNCH_CMD.read_text(encoding="utf-8")
    for text, label in ((launch_text, "bin/launch"), (cmd_text, "bin/launch.cmd")):
        assert IPC_DIR_NAME in text, f"{label} does not pin the {IPC_DIR_NAME} IPC dir"
        assert POINTER_FILE_NAME in text, f"{label} does not pin the {POINTER_FILE_NAME} pointer"


# --- refusals: symlink escapes ------------------------------------------------------


def test_refuses_an_ipc_dir_symlinked_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / IPC_DIR_NAME).symlink_to(outside, target_is_directory=True)
    with pytest.raises(PointerConfinementError):
        ipc_workspace_dir(workspace)
    with pytest.raises(PointerConfinementError):
        pointer_file_path(workspace)


def test_refuses_a_pointer_file_symlinked_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ipc = workspace / IPC_DIR_NAME
    ipc.mkdir(parents=True)
    evil = tmp_path / "evil-pointer.txt"
    evil.write_text("", encoding="utf-8")
    (ipc / POINTER_FILE_NAME).symlink_to(evil)
    with pytest.raises(PointerConfinementError):
        pointer_file_path(workspace)


# --- unconfigured workspace refuses upstream of the pointer computation ------------


def test_an_unconfigured_workspace_refuses_before_any_pointer_math(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ALT-5's bootstrap composes `pointer_file_path(workspace_root())`; with
    no workspace the guard raises first and no IPC path — least of all the
    machine-global default — is ever produced."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotConfiguredError):
        pointer_file_path(workspace_root())


# --- the machine-global default is dead code in the overlay ------------------------


def test_program_data_literal_appears_only_in_comments() -> None:
    """The overlay must never construct upstream's machine-global pointer
    path. Docstrings are runtime strings, so the literal is allowed in `#`
    comments only."""
    for module_path in sorted(SOLUS_DIR.glob("*.py")):
        for number, line in enumerate(
            module_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "ProgramData" in line:
                assert line.lstrip().startswith("#"), (
                    f"{module_path.name}:{number} mentions ProgramData outside a comment"
                )
