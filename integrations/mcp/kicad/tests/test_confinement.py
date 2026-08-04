"""SOLUSDEV-100 Phase 4 H2/H3 — `solus/confinement.py`: the single-place
path-argument confinement every registered MCP tool call goes through
(`solus/trimming.py`), plus its fail-closed behavior when the workspace is
unconfigured (H3)."""

from pathlib import Path

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line first.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.confinement import REASON_PATH_ESCAPES_WORKSPACE, confinement_refusal  # isort: skip


def _workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    return workspace


# --- no path-shaped arguments: never touches the workspace -----------------------


def test_no_path_shaped_kwargs_never_consults_the_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`list_projects` takes no arguments at all — confinement must be a
    no-op rather than requiring a workspace that tool never needs."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert confinement_refusal({}) is None
    assert confinement_refusal({"reference": "R1", "value": "10k"}) is None


# --- happy path: a confined path-shaped argument passes through ------------------


def test_absolute_path_inside_the_workspace_is_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    project = workspace / "board.kicad_pro"
    project.write_text("{}")
    assert confinement_refusal({"project_path": str(project)}) is None


def test_relative_path_inside_the_workspace_is_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    assert confinement_refusal({"schematic_path": "board.kicad_sch"}) is None


def test_multiple_path_shaped_kwargs_all_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    assert (
        confinement_refusal(
            {
                "project_path": str(workspace / "a.kicad_pro"),
                "schematic_path": str(workspace / "sub" / "a.kicad_sch"),
                "reference": "R1",
            }
        )
        is None
    )


# --- refusals: traversal, absolute-outside, symlink-escape -----------------------


def test_refuses_a_traversal_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": str(workspace / ".." / "outside.kicad_pro")})
    assert refusal == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


def test_refuses_an_absolute_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "elsewhere.kicad_pro"
    refusal = confinement_refusal({"project_path": str(outside)})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_symlink_that_resolves_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "secret.kicad_pro"
    outside.write_text("{}")
    link = workspace / "innocent.kicad_pro"
    link.symlink_to(outside)
    refusal = confinement_refusal({"project_path": str(link)})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_when_any_one_of_several_path_kwargs_escapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal(
        {
            "project_path": str(workspace / "a.kicad_pro"),
            "schematic_path": "/etc/passwd",
        }
    )
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_an_empty_path_argument(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": ""})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_non_string_path_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": None})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


# --- H3: unconfigured workspace fails closed --------------------------------------


def test_refuses_cleanly_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    refusal = confinement_refusal({"project_path": "board.kicad_pro"})
    assert refusal == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


# --- name-shape detection covers the actual roster schemas ------------------------


@pytest.mark.parametrize("name", ["project_path", "schematic_path", "PROJECT_PATH", "Path"])
def test_path_shaped_names_from_the_roster_are_detected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    assert confinement_refusal({name: str(outside)}) is not None
    assert confinement_refusal({name: str(workspace / "in.kicad_pro")}) is None


@pytest.mark.parametrize("name", ["reference", "property", "value", "filename", "ctx"])
def test_non_path_shaped_names_are_never_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert confinement_refusal({name: "/etc/passwd"}) is None
