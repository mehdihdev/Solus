"""SOLUSDEV-321 P5 (R124) — `kicad.export_schematic_pdf` / `kicad.export_board_pdf`.

A sheet and the board as PDF, for SOL's render of an electrical design. The export is
`kicad-cli sch export pdf` / `kicad-cli pcb export pdf --layers …` with a FIXED argv, over a
private, no-follow snapshot of the workspace-confined design, written into a private directory
outside the workspace. The PDF is read back bounded (`MAX_PDF_BYTES`) and published as this call's
one artifact (`publish_artifact`): the result names it by `artifact_path`, which the companion
uploads and rewrites into an `artifact_ref`. Without a native CLI, or under the Flatpak adapter,
the result is degraded with no artifact. Every CLI here is a fake script using only shell builtins:
no test launches KiCad.
"""

import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus`/`kicad_mcp` import — keep this line first.
from test_overlay_support import write_minimal_project  # isort: skip

from solus import pdf_export
from solus.cli_detect import detect_kicad_cli
from solus.development.models import DevelopmentError
from solus.pdf_export import (
    BOARD_LAYERS,
    MAX_PDF_BYTES,
    NO_BOARD_REASON,
    PDF_CLI_FAILED_REASON,
    PDF_CLI_UNAVAILABLE_REASON,
    PDF_FLATPAK_REASON,
    export_board_pdf_impl,
    export_schematic_pdf_impl,
)
from solus.workspace import ARTIFACT_DIR_NAME

WRITTEN = "%PDF-1.4 fake export"


@pytest.fixture(autouse=True)
def _fresh_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """The launcher's headless posture per test: no kicad-cli and no flatpak on PATH, no
    KICAD_CLI_PATH, and the detection cache cleared on both sides."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    detect_kicad_cli.cache_clear()
    yield
    detect_kicad_cli.cache_clear()


def _fake_cli(tmp_path: Path, body: str) -> Path:
    """A fake kicad-cli outside the workspace, pinned the way the launcher pins one. It records its
    argv, finds the path after `--output` as `$out`, then runs `body`."""
    cli = tmp_path / "bin" / "kicad-cli"
    cli.parent.mkdir()
    cli.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/argv.txt"\n'
        'out=""; prev=""\n'
        'for a in "$@"; do if [ "$prev" = "--output" ]; then out="$a"; fi; prev="$a"; done\n'
        f"{body}\n"
    )
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    return cli


def _pin_cli(monkeypatch: pytest.MonkeyPatch, cli: Path) -> None:
    monkeypatch.setenv("KICAD_CLI_PATH", str(cli))
    detect_kicad_cli.cache_clear()


def _pdf_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    project = write_minimal_project(workspace / "proj")
    (project.parent / "board.kicad_pcb").write_text("(kicad_pcb (version 20240108))\n")
    return workspace, project


def _argv(tmp_path: Path) -> list[str]:
    return (tmp_path / "argv.txt").read_text().splitlines()


def test_the_schematic_export_runs_the_pinned_cli_and_publishes_the_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, project = _pdf_project(monkeypatch, tmp_path)
    _pin_cli(monkeypatch, _fake_cli(tmp_path, f"printf '%s' '{WRITTEN}' > \"$out\""))

    result = export_schematic_pdf_impl(str(project))

    assert result == {
        "format": "pdf",
        "filename": "board-schematic.pdf",
        "bytes": len(WRITTEN),
        "artifact_path": f"{ARTIFACT_DIR_NAME}/board-schematic.pdf",
        "degraded": False,
        "reason": None,
    }
    argv = _argv(tmp_path)
    assert argv[:4] == ["sch", "export", "pdf", "--output"] and len(argv) == 6
    # The CLI reads a private copy of the schematic and writes outside the workspace.
    assert argv[5].endswith("/proj/board.kicad_sch")
    assert not Path(argv[4]).is_relative_to(workspace)
    assert not Path(argv[5]).is_relative_to(workspace)
    published = workspace / ARTIFACT_DIR_NAME / "board-schematic.pdf"
    assert published.read_text() == WRITTEN
    # The design itself is untouched: the artifact is the one file written.
    written = {p for p in workspace.rglob("*") if p.is_file()}
    assert written == {published, project, project.with_suffix(".kicad_sch"),
                       project.with_suffix(".kicad_pcb")}  # fmt: skip


def test_the_board_export_reads_a_private_copy_with_the_fixed_layers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, project = _pdf_project(monkeypatch, tmp_path)
    _pin_cli(monkeypatch, _fake_cli(tmp_path, f"printf '%s' '{WRITTEN}' > \"$out\""))

    result = export_board_pdf_impl(str(project))

    assert (result["filename"], result["artifact_path"], result["degraded"]) == (
        "board-board.pdf",
        f"{ARTIFACT_DIR_NAME}/board-board.pdf",
        False,
    )
    argv = _argv(tmp_path)
    assert argv[:6] == ["pcb", "export", "pdf", "--layers", BOARD_LAYERS, "--output"]
    assert len(argv) == 8 and argv[7].endswith("/board.kicad_pcb")
    assert not Path(argv[7]).is_relative_to(workspace)


def test_without_a_cli_the_exports_degrade_with_no_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, project = _pdf_project(monkeypatch, tmp_path)

    for export in (export_schematic_pdf_impl, export_board_pdf_impl):
        result = export(str(project))
        assert (result["degraded"], result["reason"], result["artifact_path"]) == (
            True,
            PDF_CLI_UNAVAILABLE_REASON,
            None,
        )
    assert not (workspace / ARTIFACT_DIR_NAME).exists()


def test_under_the_flatpak_adapter_the_exports_degrade_and_run_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The adapter's fixed operations hold no PDF export, so nothing is launched through it."""
    workspace, project = _pdf_project(monkeypatch, tmp_path)
    adapter = Path(pdf_export.__file__).resolve().parents[1] / "bin/kicad-cli-flatpak"
    monkeypatch.setattr(pdf_export, "detect_kicad_cli", lambda: str(adapter))

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("nothing may run under the adapter")

    monkeypatch.setattr(subprocess, "run", never)
    for export in (export_schematic_pdf_impl, export_board_pdf_impl):
        result = export(str(project))
        assert (result["degraded"], result["reason"]) == (True, PDF_FLATPAK_REASON)
    assert not (workspace / ARTIFACT_DIR_NAME).exists()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("exit 1", id="the-cli-fails"),
        pytest.param("printf 'not a pdf' > \"$out\"", id="not-a-pdf"),
        pytest.param(
            f"printf '%%PDF-' > \"$out\"; i=0; while [ $i -lt {MAX_PDF_BYTES // 1024 + 1} ]; "
            "do printf '%01024d' 0; i=$((i+1)); done >> \"$out\"",
            id="past-2-mib",
        ),
        pytest.param("exit 0", id="nothing-written"),
    ],
)
def test_a_failed_oversize_or_non_pdf_export_degrades_with_no_artifact(
    body: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, project = _pdf_project(monkeypatch, tmp_path)
    _pin_cli(monkeypatch, _fake_cli(tmp_path, body))

    result = export_schematic_pdf_impl(str(project))

    assert (tmp_path / "argv.txt").is_file()  # the CLI ran, and its output was refused
    assert (result["degraded"], result["reason"], result["artifact_path"], result["bytes"]) == (
        True,
        PDF_CLI_FAILED_REASON,
        None,
        0,
    )
    assert not (workspace / ARTIFACT_DIR_NAME).exists()


def test_a_project_without_a_board_degrades_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, project = _pdf_project(monkeypatch, tmp_path)
    project.with_suffix(".kicad_pcb").unlink()
    _pin_cli(monkeypatch, _fake_cli(tmp_path, "exit 0"))

    result = export_board_pdf_impl(str(project))

    assert (result["degraded"], result["reason"]) == (True, NO_BOARD_REASON)
    assert not (tmp_path / "argv.txt").exists()


def test_a_board_that_escapes_the_workspace_never_reaches_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The board is a sibling of the project, read no-follow from the workspace root: a symlink
    to a board elsewhere on the machine is refused before anything runs."""
    _, project = _pdf_project(monkeypatch, tmp_path)
    secret = tmp_path / "secret.kicad_pcb"
    secret.write_text("(kicad_pcb (version 20240108))\n")
    project.with_suffix(".kicad_pcb").unlink()
    project.with_suffix(".kicad_pcb").symlink_to(secret)
    _pin_cli(monkeypatch, _fake_cli(tmp_path, "exit 0"))

    with pytest.raises(DevelopmentError, match="path_escapes_workspace"):
        export_board_pdf_impl(str(project))
    assert not (tmp_path / "argv.txt").exists()


@pytest.mark.parametrize(
    ("name", "why"),
    [
        pytest.param("board.kicad_sch", "expected a .kicad_pro", id="not-a-project"),
        pytest.param("missing.kicad_pro", "project not found", id="missing"),
    ],
)
def test_only_an_existing_project_file_is_exported(
    name: str, why: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, project = _pdf_project(monkeypatch, tmp_path)
    for export in (export_schematic_pdf_impl, export_board_pdf_impl):
        with pytest.raises(ValueError, match=why):
            export(str(project.parent / name))
