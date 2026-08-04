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

import subprocess
from pathlib import Path
from typing import Any

# Generation only — this module never parses XML, untrusted or otherwise.
from xml.etree.ElementTree import Element, SubElement, tostring  # noqa: S405

from solus.cli_detect import (
    KICAD_CLI_FAILED_REASON,
    KICAD_CLI_UNAVAILABLE_REASON,
    detect_kicad_cli,
)
from solus.trimming import SupportsToolDecorator
from solus.workspace import artifact_destination, to_workspace_relative

# Local mirror of the cloud `artifact_inline_max_bytes` (bridge-contract size
# caps): results at or below this inline the netlist as `content`; above it
# the bytes land as a workspace artifact referenced by `artifact_path`.
ARTIFACT_INLINE_MAX_BYTES = 512 * 1024

RESULT_FORMAT = "kicadxml"
_CLI_EXPORT_TIMEOUT_SECONDS = 30.0  # matches upstream TIMEOUT_CONSTANTS["kicad_cli_export"]


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


def _cli_export(cli: str, schematic: Path, filename: str) -> bytes | None:
    """Run the pinned kicad-cli with a FIXED argv; None on any failure so the
    caller degrades to the file parse instead of raising."""
    destination = artifact_destination(f"{filename}.part")
    argv = [
        cli,
        "sch",
        "export",
        "netlist",
        "--format",
        RESULT_FORMAT,
        "--output",
        str(destination),
        str(schematic),
    ]
    try:
        # Fixed argv against the pinned binary — no shell, no PATH resolution.
        completed = subprocess.run(  # noqa: S603
            argv, capture_output=True, timeout=_CLI_EXPORT_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        destination.unlink(missing_ok=True)
        return None
    if completed.returncode != 0 or not destination.is_file():
        destination.unlink(missing_ok=True)
        return None
    data = destination.read_bytes()
    destination.unlink(missing_ok=True)
    return data


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
    content: str | None = None
    artifact_path: str | None = None
    if size <= ARTIFACT_INLINE_MAX_BYTES:
        content = xml_bytes.decode("utf-8", errors="replace")
    else:
        destination = artifact_destination(filename)
        destination.write_bytes(xml_bytes)
        artifact_path = to_workspace_relative(destination)
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
    if cli is None:
        degraded, reason = True, KICAD_CLI_UNAVAILABLE_REASON
    else:
        xml_bytes = _cli_export(cli, schematic, filename)
        if xml_bytes is None:
            degraded, reason = True, KICAD_CLI_FAILED_REASON
    if xml_bytes is None:
        xml_bytes = _synthesize_kicadxml(_parse_netlist(str(schematic)), schematic)
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
