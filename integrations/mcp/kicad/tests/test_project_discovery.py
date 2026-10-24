"""`list_projects` lists the linked workspace's projects and flags the open one.

Upstream walked `~/Documents/KiCad` and search paths outside the workspace, so
SOL "found" projects (e.g. KiCad's own template) that every read tool then
refused as escaping the workspace (SOLUSDEV-319)."""

from pathlib import Path

import pytest

from test_overlay_support import FakeMCP  # isort: skip
from solus.project_discovery import MAX_PROJECTS, list_projects
from solus.registration import register_allowlisted_tools


def _project(root: Path, relative: str, *, open_in_kicad: bool = False) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    if open_in_kicad:
        (path.parent / f"~{path.name}.lck").write_text("user@host")
    return path


def test_lists_only_workspace_projects_and_flags_the_open_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    outside = _project(tmp_path, "elsewhere/other.kicad_pro")
    opened = _project(workspace, "USB Charger Lab/USB Charger Lab.kicad_pro", open_in_kicad=True)
    closed = _project(workspace, "old/old.kicad_pro")
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    monkeypatch.setenv("HOME", str(tmp_path))

    projects = list_projects()

    assert [p["path"] for p in projects] == [str(opened.resolve()), str(closed.resolve())]
    assert projects[0]["open_in_kicad"] is True
    assert projects[0]["name"] == "USB Charger Lab"
    assert projects[0]["relative_path"] == "USB Charger Lab/USB Charger Lab.kicad_pro"
    assert projects[1]["open_in_kicad"] is False
    assert str(outside) not in {p["path"] for p in projects}


def test_skips_backups_hidden_dirs_and_symlinked_escapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    _project(workspace, "p/p.kicad_pro")
    _project(workspace, "p/p-backups/p.kicad_pro")
    _project(workspace, ".git/x/x.kicad_pro")
    _project(workspace, "node_modules/y/y.kicad_pro")
    escape = _project(tmp_path, "secret/s.kicad_pro")
    (workspace / "link").symlink_to(escape.parent, target_is_directory=True)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))

    assert [p["relative_path"] for p in list_projects()] == ["p/p.kicad_pro"]


def test_bounded_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "ws"
    for index in range(MAX_PROJECTS + 5):
        _project(workspace, f"p{index:03}/p.kicad_pro")
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))

    assert len(list_projects()) == MAX_PROJECTS


def test_unconfigured_workspace_lists_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)

    assert list_projects() == []


def test_registered_list_projects_is_the_workspace_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    _project(workspace, "a/a.kicad_pro", open_in_kicad=True)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    server = FakeMCP()
    registrar = register_allowlisted_tools(server)

    assert registrar.registered.count("list_projects") == 1
    result = server.tools["list_projects"]()
    assert [p["relative_path"] for p in result] == ["a/a.kicad_pro"]
    assert result[0]["open_in_kicad"] is True
