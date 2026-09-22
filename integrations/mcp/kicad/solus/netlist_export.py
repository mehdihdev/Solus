"""`kicad.export_netlist` — the plan-locked netlist export (SOLUSDEV-100 T1b).

Interface (PLAN-LOCKED, `docs/contracts/metadata-extraction.md` §2.1):
    args   {"project_path": str}
    result {"format": "kicadxml", "filename": str, "bytes": int,
            "content": str|null, "artifact_path": str|null,
            "degraded": bool, "reason": str|null}
Exactly one of content/artifact_path is non-null, branching at
ARTIFACT_INLINE_MAX_BYTES; artifact_path is WORKSPACE-relative and the file
always lives inside the workspace (solus/workspace.py confinement).

Acquisition: `kicad-cli sch export netlist --format kicadxml` when the pinned
CLI is present; otherwise (or when the CLI fails) upstream's KiCad-free
schematic file parse (`kicad_mcp.utils.netlist_parser.extract_netlist`)
synthesized into kicadxml, returned with `degraded: true` and a stable reason
— never an exception for headlessness. Tested by
tests/test_overlay_headless_degrade.py.
"""

import posixpath
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Generation only — this module never parses XML, untrusted or otherwise.
from xml.etree.ElementTree import Element, SubElement, tostring  # noqa: S405

from solus.cli_detect import (
    KICAD_CLI_FAILED_REASON,
    KICAD_CLI_UNAVAILABLE_REASON,
    detect_kicad_cli,
)
from solus.development.commit import read_schematic
from solus.development.flatpak_export import encode_snapshot
from solus.development.models import DevelopmentError
from solus.development.structural import children, document, value
from solus.export_files import publish_artifact
from solus.trimming import SupportsToolDecorator
from solus.workspace import (
    WorkspaceNotConfiguredError,
    workspace_root,
)

# Local mirror of the cloud `artifact_inline_max_bytes` (bridge-contract size
# caps): results at or below this inline the netlist as `content`; above it
# the bytes land as a workspace artifact referenced by `artifact_path`.
ARTIFACT_INLINE_MAX_BYTES = 512 * 1024

RESULT_FORMAT = "kicadxml"
_CLI_EXPORT_TIMEOUT_SECONDS = 30.0  # matches upstream TIMEOUT_CONSTANTS["kicad_cli_export"]
_MAX_SNAPSHOT_SHEETS = 64
_MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
_MAX_SNAPSHOT_DEPTH = 32
_MAX_EXPORT_BYTES = 32 * 1024 * 1024


def _find_schematic(project: Path) -> Path:
    """The project's schematic, via upstream's project-file discovery."""
    from kicad_mcp.utils.file_utils import get_project_files

    files = get_project_files(str(project))
    schematic = files.get("schematic")
    if not schematic:
        raise ValueError(f"no schematic found for project: {project}")
    return Path(schematic)


def _parse_netlist(schematic_path: str) -> dict[str, Any]:
    """Upstream's KiCad-free schematic parse (the degradation seam)."""
    from kicad_mcp.utils.netlist_parser import extract_netlist

    netlist: dict[str, Any] = extract_netlist(schematic_path)
    if "error" in netlist:
        raise ValueError(f"schematic parse failed: {netlist['error']}")
    return netlist


def _child_sheets(raw: bytes, path: str) -> Iterator[str]:
    for sheet in children(document(raw), "sheet"):
        references = [
            value(prop, 2)
            for prop in children(sheet, "property")
            if value(prop).casefold() == "sheetfile"
        ]
        if len(references) != 1:
            raise DevelopmentError("unsupported_symbol")
        reference = references[0]
        if not reference or reference.startswith("/") or any(c in reference for c in "$\\:"):
            raise DevelopmentError("path_escapes_workspace")
        yield posixpath.normpath(posixpath.join(posixpath.dirname(path), reference))


@contextmanager
def _schematic_snapshot(schematic: Path) -> Iterator[Path]:
    """Capture no-follow reads once; neither export sink reopens customer paths."""
    try:
        root = workspace_root()
        candidate = schematic if schematic.is_absolute() else root / schematic
        relative = candidate.relative_to(root).as_posix()
    except (ValueError, WorkspaceNotConfiguredError) as exc:
        raise DevelopmentError("path_escapes_workspace") from exc
    captured: dict[str, bytes] = {}
    active: set[str] = set()
    total = 0

    def capture(path: str) -> None:
        nonlocal total
        if path in active or len(active) >= _MAX_SNAPSHOT_DEPTH:
            raise DevelopmentError("unsupported_symbol")
        if path in captured:
            return
        if len(captured) >= _MAX_SNAPSHOT_SHEETS:
            raise DevelopmentError("file_too_large")
        raw = read_schematic(root, path)
        total += len(raw)
        if total > _MAX_SNAPSHOT_BYTES:
            raise DevelopmentError("file_too_large")
        captured[path] = raw
        active.add(path)
        for child in _child_sheets(raw, path):
            capture(child)
        active.remove(path)

    capture(relative)
    # Keep relative child-sheet references functional inside the private mirror.
    # Outside the bound workspace, the 0700 mirror cannot be renamed or written
    # by workspace-confined tool capabilities. Same-user arbitrary OS code is
    # outside this boundary. Flatpak receives the closure as bytes over stdin.
    with tempfile.TemporaryDirectory(prefix=".solus-export-") as directory:
        snapshot_root = Path(directory)
        if snapshot_root.is_relative_to(root):
            raise DevelopmentError("path_escapes_workspace")
        for path, raw in captured.items():
            destination = snapshot_root / path
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(raw)
        yield snapshot_root / relative


def _cli_export(cli: str, schematic: Path, filename: str) -> bytes | None:
    """Run the pinned kicad-cli with a FIXED argv; None on any failure so the
    caller degrades to the file parse instead of raising."""
    try:
        adapter = Path(__file__).resolve().parents[1] / "bin/kicad-cli-flatpak"
        if Path(cli).resolve() == adapter:
            completed = subprocess.run(  # noqa: S603 — owned fixed helper adapter
                [
                    cli,
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    RESULT_FORMAT,
                    "--output",
                    "-",
                    "-",
                ],
                input=_snapshot_payload(schematic),
                capture_output=True,
                timeout=_CLI_EXPORT_TIMEOUT_SECONDS + 5,
                check=False,
            )
            data = completed.stdout if completed.returncode == 0 else None
        else:
            data = _native_cli_export(cli, schematic)
        if data is not None and len(data) > _MAX_EXPORT_BYTES:
            raise DevelopmentError("file_too_large")
        return data
    except (OSError, subprocess.SubprocessError):
        return None


def _snapshot_payload(schematic: Path) -> bytes:
    root = next(parent for parent in schematic.parents if parent.name.startswith(".solus-export-"))
    files = {
        path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*.kicad_sch")
    }
    return encode_snapshot(schematic.relative_to(root).as_posix(), files)


def _native_cli_export(cli: str, schematic: Path) -> bytes | None:
    with tempfile.TemporaryFile() as output:
        descriptor = output.fileno()
        descriptor_root = "/proc/self/fd" if Path("/proc/self/fd").is_dir() else "/dev/fd"
        argv = [
            cli,
            "sch",
            "export",
            "netlist",
            "--format",
            RESULT_FORMAT,
            "--output",
            f"{descriptor_root}/{descriptor}",
            str(schematic.absolute()),
        ]
        # Fixed argv against the pinned binary — no shell or PATH resolution.
        completed = subprocess.run(  # noqa: S603
            argv,
            pass_fds=(descriptor,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_CLI_EXPORT_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            return None
        output.seek(0)
        return output.read(_MAX_EXPORT_BYTES + 1)


def _synthesize_kicadxml(netlist: dict[str, Any], schematic: Path) -> bytes:
    """kicadxml-shaped document from the parsed netlist (degraded fidelity)."""
    export = Element("export", version="E")
    design = SubElement(export, "design")
    SubElement(design, "source").text = str(schematic)
    SubElement(design, "tool").text = "solus kicad overlay (KiCad-free file parse)"

    components_element = SubElement(export, "components")
    components: dict[str, Any] = netlist.get("components", {})
    for reference in sorted(components):
        info = components[reference] or {}
        component = SubElement(components_element, "comp", ref=str(reference))
        SubElement(component, "value").text = str(info.get("value", ""))
        lib_id = str(info.get("lib_id", ""))
        library, _, part = lib_id.partition(":")
        SubElement(component, "libsource", lib=library, part=part or library)

    nets_element = SubElement(export, "nets")
    nets: dict[str, Any] = netlist.get("nets", {})
    for code, net_name in enumerate(sorted(nets), start=1):
        net = SubElement(nets_element, "net", code=str(code), name=str(net_name))
        for pin in nets[net_name] or ():
            SubElement(
                net,
                "node",
                ref=str(pin.get("component", "")),
                pin=str(pin.get("pin", "")),
            )
    document: bytes = tostring(export, encoding="utf-8", xml_declaration=True)
    return document


def _package_result(
    xml_bytes: bytes, filename: str, degraded: bool, reason: str | None
) -> dict[str, Any]:
    """The plan-locked envelope: inline at or below the cap, artifact above."""
    size = len(xml_bytes)
    if size > _MAX_EXPORT_BYTES:
        raise DevelopmentError("file_too_large")
    content: str | None = None
    artifact_path: str | None = None
    if size <= ARTIFACT_INLINE_MAX_BYTES:
        content = xml_bytes.decode("utf-8", errors="replace")
    else:
        artifact_path = publish_artifact(filename, xml_bytes)
    return {
        "format": RESULT_FORMAT,
        "filename": filename,
        "bytes": size,
        "content": content,
        "artifact_path": artifact_path,
        "degraded": degraded,
        "reason": reason,
    }


def export_netlist_impl(project_path: str) -> dict[str, Any]:
    """Export a project's schematic netlist as kicadxml (plan-locked shape)."""
    project = Path(project_path)
    if project.suffix != ".kicad_pro":
        raise ValueError(f"expected a .kicad_pro project path, got: {project}")
    if not project.is_file():
        raise ValueError(f"project not found: {project}")
    schematic = _find_schematic(project)
    filename = f"{project.stem}-netlist.xml"

    cli = detect_kicad_cli()
    xml_bytes: bytes | None = None
    degraded = False
    reason: str | None = None
    with _schematic_snapshot(schematic) as snapshot:
        if cli is None:
            degraded, reason = True, KICAD_CLI_UNAVAILABLE_REASON
        else:
            xml_bytes = _cli_export(cli, snapshot, filename)
            if xml_bytes is None:
                degraded, reason = True, KICAD_CLI_FAILED_REASON
        if xml_bytes is None:
            xml_bytes = _synthesize_kicadxml(_parse_netlist(str(snapshot)), schematic)
    return _package_result(xml_bytes, filename, degraded, reason)


def register_export_tools(mcp: SupportsToolDecorator) -> None:
    """Register the Solus-authored export tool (driven through the trimming
    registrar so it gets the same hardening as upstream tools)."""

    @mcp.tool()
    async def export_netlist(project_path: str) -> dict[str, Any]:
        """Export the KiCad project's schematic netlist in kicadxml format.

        Returns the netlist inline (`content`) up to 512 KiB, else as a
        workspace-relative `artifact_path`. On machines without kicad-cli the
        netlist is synthesized from a KiCad-free schematic parse and the
        result carries `degraded: true` with the reason.
        """
        return export_netlist_impl(project_path)
