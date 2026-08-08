"""SOLUSDEV-102 ALT-3 — `solus/confinement.py`: the single-place
path-argument confinement every registered MCP tool call goes through
(ALT-5's registrar wires it in), plus its fail-closed behavior when the
workspace is unconfigured. Mirrors the kicad fork's confinement contract:
same `confinement_refusal` name, same semantics, same stable refusal
envelope."""

from pathlib import Path

import pytest

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import overlay_module  # isort: skip

_confinement = overlay_module("confinement")

REASON_PATH_ESCAPES_WORKSPACE: str = _confinement.REASON_PATH_ESCAPES_WORKSPACE
confinement_refusal = _confinement.confinement_refusal


def _workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    return workspace


# --- no path-shaped arguments: never touches the workspace -----------------------


def test_no_path_shaped_kwargs_never_consults_the_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool with no path-shaped arguments must be a no-op here rather than
    requiring a workspace it never needs."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert confinement_refusal({}) is None
    assert confinement_refusal({"designator": "R1", "value": "10k"}) is None


# --- happy path: a confined path-shaped argument passes through ------------------


def test_absolute_path_inside_the_workspace_is_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    project = workspace / "board.PrjPcb"
    project.write_text("")
    assert confinement_refusal({"project_path": str(project)}) is None


def test_relative_path_inside_the_workspace_is_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    assert confinement_refusal({"schematic_path": "board.SchDoc"}) is None


def test_multiple_path_shaped_kwargs_all_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    assert (
        confinement_refusal(
            {
                "project_path": str(workspace / "a.PrjPcb"),
                "output_path": str(workspace / "out" / "a.PcbDoc"),
                "designator": "R1",
            }
        )
        is None
    )


# --- refusals: traversal, absolute-outside, symlink-escape -----------------------


def test_refuses_a_traversal_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": str(workspace / ".." / "outside.PrjPcb")})
    assert refusal == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


def test_refuses_an_absolute_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "elsewhere.PrjPcb"
    refusal = confinement_refusal({"project_path": str(outside)})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_symlink_that_resolves_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "secret.PrjPcb"
    outside.write_text("")
    link = workspace / "innocent.PrjPcb"
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
            "project_path": str(workspace / "a.PrjPcb"),
            "schematic_path": "/etc/passwd",
        }
    )
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_non_string_path_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": 42})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_an_absolute_system_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": "/etc"})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_a_nul_byte_path_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M1: `Path.resolve()` raises ValueError on embedded NUL bytes; the
    never-raises contract demands the stable refusal envelope instead."""
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": "a\x00b"})
    assert refusal == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


def test_refuses_a_relative_parent_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"project_path": "../x"})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


# --- SDK default values are ABSENT, not escapes (H1) -------------------------------
#
# The MCP SDK's FuncMetadata.call_fn_with_arg_validation passes EVERY
# arg-model field to the tool — unsupplied defaults included — so wrappers
# see `project_path=None` (the six proj_* reads) and `sheet_path=""`
# (sch_set_components_parameters) on every call. Upstream tool bodies drop
# falsy path args before building IPC params (`if project_path:`), so a
# falsy value here IS "argument absent": skip it, never refuse the default.


def test_none_path_argument_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    assert confinement_refusal({"project_path": None}) is None


def test_empty_string_path_argument_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    assert confinement_refusal({"sheet_path": ""}) is None


def test_absent_style_defaults_never_mask_a_real_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    refusal = confinement_refusal({"sheet_path": "", "project_path": "/etc/passwd"})
    assert refusal is not None
    assert refusal["reason"] == REASON_PATH_ESCAPES_WORKSPACE


def test_absent_style_defaults_skip_the_workspace_when_nothing_is_supplied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """All-falsy path args must not even require a configured workspace —
    the call carries no path to confine."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert confinement_refusal({"project_path": None, "sheet_path": ""}) is None


# --- unconfigured workspace fails closed -------------------------------------------


def test_refuses_cleanly_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    refusal = confinement_refusal({"project_path": "board.PrjPcb"})
    assert refusal == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}


# --- name-shape detection ----------------------------------------------------------


@pytest.mark.parametrize("name", ["project_path", "schematic_path", "PROJECT_PATH", "Path"])
def test_path_shaped_names_are_detected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    assert confinement_refusal({name: str(outside)}) is not None
    assert confinement_refusal({name: str(workspace / "in.PrjPcb")}) is None


@pytest.mark.parametrize("name", ["designator", "property", "value", "filename", "ctx"])
def test_non_path_shaped_names_are_never_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    assert confinement_refusal({name: "/etc/passwd"}) is None
