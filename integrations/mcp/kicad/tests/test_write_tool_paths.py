"""SOLUSDEV-100 T2b — `solus/write/paths.py`: workspace confinement for the
ONE file `set_symbol_property` may mutate (traversal, symlink escape,
missing, oversize, wrong-suffix — all refused, original never touched)."""

from pathlib import Path

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.write.errors import REASON_FILE_TOO_LARGE, REASON_PATH_ESCAPES_WORKSPACE, RefusalError  # isort: skip
from solus.write.paths import MAX_SCHEMATIC_BYTES, resolve_confined_schematic_path  # isort: skip


def _workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    return workspace


def _schematic(
    workspace: Path, name: str = "board.kicad_sch", content: bytes = b"(kicad_sch)"
) -> Path:
    path = workspace / name
    path.write_bytes(content)
    return path


# --- happy path -----------------------------------------------------------------


def test_resolves_an_absolute_path_inside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    schematic = _schematic(workspace)
    resolved = resolve_confined_schematic_path(str(schematic))
    assert resolved == schematic.resolve()


def test_resolves_a_relative_path_against_the_workspace_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    _schematic(workspace)
    resolved = resolve_confined_schematic_path("board.kicad_sch")
    assert resolved == (workspace / "board.kicad_sch").resolve()


def test_resolves_a_nested_relative_path_inside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    (workspace / "sub").mkdir()
    schematic = _schematic(workspace, name="sub/board.kicad_sch")
    resolved = resolve_confined_schematic_path("sub/board.kicad_sch")
    assert resolved == schematic.resolve()


# --- refusals: path_escapes_workspace --------------------------------------------


def test_refuses_a_traversal_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "outside.kicad_sch"
    outside.write_bytes(b"(kicad_sch)")
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(workspace / ".." / "outside.kicad_sch"))
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE
    assert outside.read_bytes() == b"(kicad_sch)"


def test_refuses_an_absolute_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "elsewhere.kicad_sch"
    outside.write_bytes(b"(kicad_sch)")
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(outside))
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_symlink_that_resolves_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "secret.kicad_sch"
    outside.write_bytes(b"(kicad_sch secret)")
    link = workspace / "innocent.kicad_sch"
    link.symlink_to(outside)
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(link))
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE
    assert outside.read_bytes() == b"(kicad_sch secret)"


def test_refuses_a_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(workspace / "nope.kicad_sch"))
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_the_wrong_suffix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    wrong = workspace / "board.txt"
    wrong.write_bytes(b"not a schematic")
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(wrong))
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_directory_given_as_the_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    directory = workspace / "board.kicad_sch"
    directory.mkdir()
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(directory))
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_an_empty_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _workspace(monkeypatch, tmp_path)
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path("")
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_cleanly_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """H3: `workspace_root()` now raises `WorkspaceNotConfiguredError` rather
    than defaulting to cwd; this confinement layer maps that to the same
    stable `path_escapes_workspace` reason (the closest honest bucket —
    there is no workspace to confine into, so nothing can be proven inside
    it) rather than letting a bare exception escape."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path("board.kicad_sch")
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


# --- refusal: file_too_large ------------------------------------------------------


def test_refuses_a_file_over_the_size_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    oversize = _schematic(workspace, content=b"x" * (MAX_SCHEMATIC_BYTES + 1))
    with pytest.raises(RefusalError) as excinfo:
        resolve_confined_schematic_path(str(oversize))
    assert excinfo.value.reason == REASON_FILE_TOO_LARGE


def test_accepts_a_file_exactly_at_the_size_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    at_cap = _schematic(workspace, content=b"x" * MAX_SCHEMATIC_BYTES)
    resolved = resolve_confined_schematic_path(str(at_cap))
    assert resolved == at_cap.resolve()
