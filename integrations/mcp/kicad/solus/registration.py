"""Wire the allowlisted roster onto a server instance (SOLUSDEV-100 T1b).

Only the upstream tool modules that CONTAIN allowlisted tools are ever
invoked, and each runs against the TrimmingRegistrar so its non-allowlisted
siblings are never registered. Upstream modules never touched here (their
tools are dead by omission): analysis_tools, export_tools (thumbnails via
kicad-cli), drc_tools, pattern_tools, validation_tools, and every upstream
resource/prompt registration. Tested by tests/test_overlay_tool_trimming.py.
"""

from typing import Any, cast

from solus.development_registration import register_development_tools
from solus.netlist_export import register_export_tools
from solus.netlist_reads import register_netlist_reads
from solus.roster import FULL_ROSTER
from solus.trimming import SupportsToolDecorator, TrimmingRegistrar
from solus.write.set_symbol_property import register_write_tools


def register_allowlisted_tools(mcp: SupportsToolDecorator) -> TrimmingRegistrar:
    """Register exactly FULL_ROSTER on `mcp`; returns the registrar so callers
    can audit what was registered vs. blocked."""
    registrar = TrimmingRegistrar(mcp, allowed=FULL_ROSTER)

    # Imported lazily: upstream lives on sys.path only after the entry
    # module's bootstrap (or the test scaffolding) has run.
    from kicad_mcp.tools.bom_tools import register_bom_tools
    from kicad_mcp.tools.project_tools import register_project_tools

    # Upstream's register functions annotate their parameter as FastMCP, but
    # only use the @mcp.tool() decorator surface — exactly what the registrar
    # duck-types (SupportsToolDecorator). The trim depends on NOT being a real
    # FastMCP, so the mismatch is intentional, not incidental.
    shim = cast(Any, registrar)
    register_project_tools(shim)
    register_netlist_reads(registrar)
    register_bom_tools(shim)
    register_export_tools(registrar)
    register_write_tools(registrar)
    register_development_tools(registrar)

    if set(registrar.registered) != FULL_ROSTER:
        missing = FULL_ROSTER - set(registrar.registered)
        raise RuntimeError(
            "upstream no longer provides the allowlisted roster "
            f"(missing: {sorted(missing)}) — re-vendor review required"
        )
    return registrar
