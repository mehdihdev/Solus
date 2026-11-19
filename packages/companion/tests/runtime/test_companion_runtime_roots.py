"""App-data roots — mcp-fork-runtime.md §2."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest
from solus_companion.runtime.roots import (
    ENVS_ROOT_ENV,
    data_root,
    env_interpreter,
    envs_root,
    is_fork_name,
    python_root,
)

HOME = Path("/home/u")


def test_macos_root_is_application_support() -> None:
    assert data_root("darwin", {}, HOME) == HOME / "Library" / "Application Support" / "Solus"


def test_windows_root_is_local_appdata_not_roaming() -> None:
    env = {"LOCALAPPDATA": r"C:\Users\u\AppData\Local", "APPDATA": r"C:\Users\u\AppData\Roaming"}
    root = data_root("win32", env, HOME)
    assert PureWindowsPath(str(root)) == PureWindowsPath(r"C:\Users\u\AppData\Local\Solus")


def test_windows_without_localappdata_falls_back_under_home() -> None:
    assert data_root("win32", {}, HOME) == HOME / "AppData" / "Local" / "Solus"


def test_linux_uses_xdg_data_home_when_absolute() -> None:
    assert data_root("linux", {"XDG_DATA_HOME": "/xdg"}, HOME) == Path("/xdg/solus")
    assert data_root("linux", {"XDG_DATA_HOME": "rel"}, HOME) == HOME / ".local/share/solus"
    assert data_root("linux", {}, HOME) == HOME / ".local" / "share" / "solus"


def test_envs_root_is_under_data_and_python_root_is_its_sibling() -> None:
    envs = envs_root("darwin", {}, HOME)
    assert envs == data_root("darwin", {}, HOME) / "mcp-envs"
    assert python_root(envs) == data_root("darwin", {}, HOME) / "mcp-python"


def test_override_replaces_envs_root(tmp_path: Path) -> None:
    assert envs_root("darwin", {ENVS_ROOT_ENV: str(tmp_path)}, HOME) == tmp_path


def test_relative_override_is_refused() -> None:
    with pytest.raises(ValueError):
        envs_root("darwin", {ENVS_ROOT_ENV: "relative/envs"}, HOME)


def test_env_interpreter_per_platform(tmp_path: Path) -> None:
    assert env_interpreter(tmp_path, "darwin") == tmp_path / "bin" / "python"
    assert env_interpreter(tmp_path, "win32") == tmp_path / "Scripts" / "python.exe"


@pytest.mark.parametrize("name", ["kicad", "a", "my-fork_2", "x" * 32])
def test_fork_names_accepted(name: str) -> None:
    assert is_fork_name(name)


@pytest.mark.parametrize("name", ["", "Kicad", "1abc", "../x", "x" * 33, "a b", "a/b"])
def test_fork_names_refused(name: str) -> None:
    assert not is_fork_name(name)
