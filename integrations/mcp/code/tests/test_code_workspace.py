"""SOLUSDEV-250 — the `code` fork's `workspace.py` is the local fork's
confinement module (verbatim below the docstring): fail-closed root, the
one path gate."""

from pathlib import Path

import pytest

from code_paths import MCP_ROOT, SOLUS_DIR, overlay_module  # isort: skip

workspace = overlay_module("workspace")


def _code_part(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split('"""', 2)[2]


def test_is_verbatim_the_local_forks_module_below_the_docstring() -> None:
    assert _code_part(SOLUS_DIR / "workspace.py") == _code_part(
        MCP_ROOT / "local" / "solus" / "workspace.py"
    )


def test_workspace_root_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    with pytest.raises(workspace.WorkspaceNotConfiguredError):
        workspace.workspace_root()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", "")
    with pytest.raises(workspace.WorkspaceNotConfiguredError):
        workspace.workspace_root()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    assert workspace.workspace_root() == tmp_path.resolve()


@pytest.mark.parametrize("rel", ["../x", "/abs", "", ".", "a/../b", "C:\\x", "a\\b", "./a"])
def test_resolve_inside_refuses_unsafe(rel: str, tmp_path: Path) -> None:
    assert workspace.resolve_inside(rel, tmp_path) is None
