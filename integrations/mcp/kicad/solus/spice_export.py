"""`kicad.export_spice_netlist` — the schematic's SPICE netlist, for rung 3's circuit simulation
(SOLUSDEV-321 P4-T3; docs/api/simulation.md §7).

Interface:
    args   {"project_path": str}
    result {"format": "spice", "filename": str, "bytes": int, "content": str|null,
            "degraded": bool, "reason": str|null}

The export is `kicad-cli sch export netlist --format spice`, run with a FIXED argv through the
fork's own native capture (`solus.development.flatpak_export._capture`): the pinned binary, its
output on an inherited descriptor, devnull stdio, a 30 s timeout and a bounded read. It reads the
same workspace-confined, no-follow private snapshot `export_netlist` reads (`_schematic_snapshot`).
The netlist comes back as data, inline only, at most `MAX_SPICE_BYTES` (the API's own bound on a
netlist), and nothing is ever written to the workspace. Each `.include` and `.lib` line keeps its
directive and loses its path: the path names a file on this machine, and the API's deck drops
the line unread.

There is no KiCad-free fallback: a SPICE netlist needs the simulation models KiCad itself
resolves. Without a native CLI, or under the Flatpak adapter (whose fixed operations hold no SPICE
export), the result is `degraded: true` with a stable reason and no content.

The text stays untrusted on the far side: it reaches a simulator only through the API's closed
grammar (`packages/api/src/solus_api/simulation/providers/spice_deck.py`).
"""

import re
from pathlib import Path
from typing import Any

from solus.cli_detect import detect_kicad_cli
from solus.development.flatpak_export import _capture
from solus.netlist_export import _find_schematic, _schematic_snapshot
from solus.trimming import SupportsToolDecorator

RESULT_FORMAT = "spice"
# The API's own bound on a netlist it reads (spice_deck.MAX_NETLIST_BYTES).
MAX_SPICE_BYTES = 256 * 1024
SPICE_EXPORT = ["sch", "export", "netlist", "--format", RESULT_FORMAT]
# The file directives the API's deck drops unread (spice_deck.DROPPED). Their paths name files on
# this machine, a username among them, so only the directive leaves it, on its own line.
_FILE_DIRECTIVE = re.compile(rb"^([ \t]*\.(?:include|lib))\b[^\r\n]*", re.IGNORECASE | re.MULTILINE)

# Stable degradation reasons (asserted verbatim by tests and shown to users).
SPICE_CLI_UNAVAILABLE_REASON = (
    "kicad-cli unavailable (headless posture): a SPICE netlist needs KiCad's own export"
)
SPICE_FLATPAK_REASON = "the Flatpak kicad-cli adapter holds no SPICE export"
SPICE_CLI_FAILED_REASON = "kicad-cli SPICE export failed, or passed 256 KiB"


def _is_flatpak_adapter(cli: str) -> bool:
    adapter = Path(__file__).resolve().parents[1] / "bin/kicad-cli-flatpak"
    return Path(cli).resolve() == adapter


def _spice_result(filename: str, data: bytes | None, reason: str | None) -> dict[str, Any]:
    """The envelope: the netlist inline, or degraded with no content."""
    return {
        "format": RESULT_FORMAT,
        "filename": filename,
        "bytes": 0 if data is None else len(data),
        "content": None if data is None else data.decode("utf-8", errors="replace"),
        "degraded": data is None,
        "reason": reason,
    }


def export_spice_netlist_impl(project_path: str) -> dict[str, Any]:
    """Export a project's schematic as a SPICE netlist (module docstring)."""
    project = Path(project_path)
    if project.suffix != ".kicad_pro":
        raise ValueError(f"expected a .kicad_pro project path, got: {project}")
    if not project.is_file():
        raise ValueError(f"project not found: {project}")
    schematic = _find_schematic(project)
    filename = f"{project.stem}.cir"
    cli = detect_kicad_cli()
    if cli is None:
        return _spice_result(filename, None, SPICE_CLI_UNAVAILABLE_REASON)
    if _is_flatpak_adapter(cli):
        return _spice_result(filename, None, SPICE_FLATPAK_REASON)
    with _schematic_snapshot(schematic) as snapshot:
        captured = _capture(str(snapshot), cli, SPICE_EXPORT, MAX_SPICE_BYTES)
    if captured is None:
        return _spice_result(filename, None, SPICE_CLI_FAILED_REASON)
    return _spice_result(filename, _FILE_DIRECTIVE.sub(rb"\1", captured[1]), None)


def register_spice_export(mcp: SupportsToolDecorator) -> None:
    """Register the Solus-authored SPICE export (driven through the trimming registrar, so it
    gets the same hardening as every other tool)."""

    @mcp.tool()
    async def export_spice_netlist(project_path: str) -> dict[str, Any]:
        """Export the KiCad project's schematic as a SPICE netlist, for circuit simulation.

        Returns the netlist inline (`content`), at most 256 KiB. Without a native kicad-cli, or
        under the Flatpak adapter, the result carries `degraded: true` and a reason, with no
        content.
        """
        return export_spice_netlist_impl(project_path)
