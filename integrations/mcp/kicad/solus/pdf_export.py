"""`kicad.export_schematic_pdf` / `kicad.export_board_pdf` — a sheet and the board as PDF, for
SOL's render of an electrical design (SOLUSDEV-321 P5; R124).

Interface (both):
    args   {"project_path": str}
    result {"format": "pdf", "filename": str, "bytes": int, "artifact_path": str | null,
            "degraded": bool, "reason": str | null}

The export is `kicad-cli sch export pdf` (the schematic, every sheet) or `kicad-cli pcb export pdf
--layers <BOARD_LAYERS>` (the board), run with a FIXED argv against the pinned binary: no shell, no
PATH lookup, devnull stdio, a 30 s timeout. The CLI reads a private, no-follow snapshot of the
workspace-confined design (`_schematic_snapshot`, and `_board_snapshot` for the board, a sibling of
the project read component by component from the workspace root) and writes into a private
directory outside the workspace. The PDF is read back no-follow, at most `MAX_PDF_BYTES` (the
cloud's own bound on a render's export), and must start `%PDF-`.

It is then published as this call's one artifact (`solus/export_files.py:publish_artifact`): the
companion uploads it and rewrites `artifact_path` into an `artifact_ref`, and the cloud consumes it
once, checks its bytes — never the type claimed for them — and rasterises its first page with its
own pinned renderer. Nothing else is written; the design itself is never touched.

There is no KiCad-free fallback: a PDF needs KiCad's own plotter. Without a native kicad-cli, or
under the Flatpak adapter (whose fixed operations hold no PDF export), the result is
`degraded: true` with a stable reason and no artifact.
"""

import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

from solus.cli_detect import detect_kicad_cli
from solus.development.models import DevelopmentError
from solus.export_files import publish_artifact, read_regular_at
from solus.netlist_export import _find_schematic, _schematic_snapshot
from solus.spice_export import _is_flatpak_adapter
from solus.trimming import SupportsToolDecorator
from solus.workspace import WorkspaceNotConfiguredError, workspace_root

RESULT_FORMAT = "pdf"
#: The cloud's own bound on a render's export (`bridge/service.py:MAX_TOOL_IMAGE_BYTES`).
MAX_PDF_BYTES = 2 * 1024 * 1024
MAX_BOARD_BYTES = 32 * 1024 * 1024
SCHEMATIC_PDF = ["sch", "export", "pdf"]
BOARD_LAYERS = "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,Edge.Cuts"
BOARD_PDF = ["pcb", "export", "pdf", "--layers", BOARD_LAYERS]
_TIMEOUT_SECONDS = 30
_OUTPUT_NAME = "export.pdf"
_PDF_MAGIC = b"%PDF-"

# Stable degradation reasons (asserted verbatim by tests and shown to users).
PDF_CLI_UNAVAILABLE_REASON = (
    "kicad-cli unavailable (headless posture): a PDF needs KiCad's own export"
)
PDF_FLATPAK_REASON = "the Flatpak kicad-cli adapter holds no PDF export"
PDF_CLI_FAILED_REASON = "kicad-cli PDF export failed, or passed 2 MiB"
NO_BOARD_REASON = "the project has no .kicad_pcb board to export"


def _pdf_result(
    filename: str, artifact_path: str | None, size: int, reason: str | None
) -> dict[str, Any]:
    """The envelope: the published PDF's workspace-relative path, or degraded with none."""
    return {
        "format": RESULT_FORMAT,
        "filename": filename,
        "bytes": size,
        "artifact_path": artifact_path,
        "degraded": artifact_path is None,
        "reason": reason,
    }


def _project_file(project_path: str) -> Path:
    project = Path(project_path)
    if project.suffix != ".kicad_pro":
        raise ValueError(f"expected a .kicad_pro project path, got: {project}")
    if not project.is_file():
        raise ValueError(f"project not found: {project}")
    return project


def _cli_or_reason() -> tuple[str | None, str | None]:
    """The pinned native CLI, or the stable reason there is none to export with."""
    cli = detect_kicad_cli()
    if cli is None:
        return None, PDF_CLI_UNAVAILABLE_REASON
    if _is_flatpak_adapter(cli):
        return None, PDF_FLATPAK_REASON
    return cli, None


def _run_export(cli: str, operation: list[str], source: Path) -> bytes | None:
    """The fixed argv, its output read back no-follow and bounded; None on any failure."""
    with tempfile.TemporaryDirectory(prefix=".solus-pdf-") as private:
        directory = Path(private)
        if directory.is_relative_to(workspace_root()):
            raise DevelopmentError("path_escapes_workspace")
        try:
            completed = subprocess.run(  # noqa: S603 — pinned binary and fixed operation
                [cli, *operation, "--output", str(directory / _OUTPUT_NAME), str(source)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data = read_regular_at(descriptor, _OUTPUT_NAME, MAX_PDF_BYTES)
        except (OSError, DevelopmentError):
            return None
        finally:
            os.close(descriptor)
    return data if data.startswith(_PDF_MAGIC) else None


@contextmanager
def _board_snapshot(board: Path) -> Iterator[Path]:
    """The board read once — every component of its path opened no-follow from the workspace
    root — into a private copy outside the workspace."""
    try:
        root = workspace_root()
        candidate = board if board.is_absolute() else root / board
        parts = candidate.relative_to(root).parts
    except (ValueError, WorkspaceNotConfiguredError) as exc:
        raise DevelopmentError("path_escapes_workspace") from exc
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise DevelopmentError("path_escapes_workspace")
    data = _read_confined(root, parts)
    with tempfile.TemporaryDirectory(prefix=".solus-board-") as private:
        snapshot_root = Path(private)
        if snapshot_root.is_relative_to(root):
            raise DevelopmentError("path_escapes_workspace")
        snapshot = snapshot_root / parts[-1]
        snapshot.write_bytes(data)
        yield snapshot


def _read_confined(root: Path, parts: tuple[str, ...]) -> bytes:
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in parts[:-1]:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        return read_regular_at(descriptors[-1], parts[-1], MAX_BOARD_BYTES)
    except OSError as exc:
        raise DevelopmentError("path_escapes_workspace") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _published(
    filename: str,
    cli: str,
    operation: list[str],
    snapshot: Callable[[], AbstractContextManager[Path]],
) -> dict[str, Any]:
    with snapshot() as source:
        data = _run_export(cli, operation, source)
    if data is None:
        return _pdf_result(filename, None, 0, PDF_CLI_FAILED_REASON)
    return _pdf_result(filename, publish_artifact(filename, data), len(data), None)


def export_schematic_pdf_impl(project_path: str) -> dict[str, Any]:
    """Export a project's schematic, every sheet, as one PDF (module docstring)."""
    project = _project_file(project_path)
    schematic = _find_schematic(project)
    filename = f"{project.stem}-schematic.pdf"
    cli, reason = _cli_or_reason()
    if cli is None:
        return _pdf_result(filename, None, 0, reason)
    return _published(filename, cli, SCHEMATIC_PDF, lambda: _schematic_snapshot(schematic))


def export_board_pdf_impl(project_path: str) -> dict[str, Any]:
    """Export a project's board as one PDF of its copper, silkscreen and outline (module
    docstring)."""
    project = _project_file(project_path)
    board = project.with_suffix(".kicad_pcb")
    filename = f"{project.stem}-board.pdf"
    cli, reason = _cli_or_reason()
    if cli is None:
        return _pdf_result(filename, None, 0, reason)
    if not board.exists() and not board.is_symlink():
        return _pdf_result(filename, None, 0, NO_BOARD_REASON)
    return _published(filename, cli, BOARD_PDF, lambda: _board_snapshot(board))


def register_pdf_export(mcp: SupportsToolDecorator) -> None:
    """Register the Solus-authored PDF exports (driven through the trimming registrar, so they get
    the same hardening as every other tool)."""

    @mcp.tool()
    async def export_schematic_pdf(project_path: str) -> dict[str, Any]:
        """Export the KiCad project's schematic as one PDF, for a render of its sheets.

        Publishes the PDF (at most 2 MiB) as this call's artifact; the design is never written.
        Without a native kicad-cli, or under the Flatpak adapter, the result carries
        `degraded: true` and a reason, with no artifact.
        """
        return export_schematic_pdf_impl(project_path)

    @mcp.tool()
    async def export_board_pdf(project_path: str) -> dict[str, Any]:
        """Export the KiCad project's board (copper, silkscreen, outline) as one PDF.

        Publishes the PDF (at most 2 MiB) as this call's artifact; the design is never written.
        Without a native kicad-cli, under the Flatpak adapter, or without a board, the result
        carries `degraded: true` and a reason, with no artifact.
        """
        return export_board_pdf_impl(project_path)
