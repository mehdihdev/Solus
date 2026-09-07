"""SOLUSDEV-249 — workspace resolution fails closed; `resolve_inside` confines
every relative path to the linked folder (no absolute, no `..`, no symlink
escape) and answers None instead of raising."""

import os
from pathlib import Path

import pytest

from .local_paths import overlay_module  # isort: skip

workspace = overlay_module("workspace")


def test_workspace_root_honors_the_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    assert workspace.workspace_root() == tmp_path.resolve()


@pytest.mark.parametrize("value", [None, ""])
def test_workspace_root_refuses_when_unset_or_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    else:
        monkeypatch.setenv("SOLUS_MCP_WORKSPACE", value)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(workspace.WorkspaceNotConfiguredError):
        workspace.workspace_root()


def test_resolve_inside_returns_the_resolved_file(tmp_path: Path) -> None:
    target = tmp_path / "hw" / "main" / "main.kicad_pro"
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    assert workspace.resolve_inside("hw/main/main.kicad_pro", root=tmp_path) == target.resolve()


@pytest.mark.parametrize(
    "hostile",
    [
        "../escape.kicad_pro",
        "..",
        ".",
        "",
        "/etc/passwd",
        "a/../../b.kicad_pro",
        "..\\windows.kicad_pro",
        "C:\\Windows\\x",
        "hw/./../../x",
    ],
)
def test_resolve_inside_refuses_traversal_and_absolute(tmp_path: Path, hostile: str) -> None:
    assert workspace.resolve_inside(hostile, root=tmp_path) is None


def test_resolve_inside_refuses_a_missing_file(tmp_path: Path) -> None:
    assert workspace.resolve_inside("missing.kicad_pro", root=tmp_path) is None


def test_resolve_inside_refuses_a_symlink_escaping_the_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.kicad_pro"
    secret.write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(secret, root / "link.kicad_pro")
    assert workspace.resolve_inside("link.kicad_pro", root=root) is None


def test_resolve_inside_uses_the_env_workspace_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    (tmp_path / "a.py").write_text("")
    assert workspace.resolve_inside("a.py") == (tmp_path / "a.py").resolve()


def test_resolve_inside_answers_none_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert workspace.resolve_inside("a.py") is None
