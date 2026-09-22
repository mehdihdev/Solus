"""The curated tool roster the Solus kicad server registers (SOLUSDEV-100 T1b).

Single Python-side statement of what `allowlist.yaml` (the human-ratified
source of truth for the cloud gate) exposes. The registration shim registers
EXACTLY `READ_ROSTER`; everything else upstream defines is never registered —
dead in-process, not merely hidden.

Draft-name mapping (spec draft -> upstream reality, recorded in PROVENANCE):
    list_projects         -> list_projects           (exact)
    get_project_summary   -> get_project_structure
    extract_netlist       -> extract_project_netlist
    get_schematic_summary -> analyze_schematic_connections
    analyze_bom           -> analyze_bom             (exact)
    export_netlist        -> Solus-authored (solus/netlist_export.py); upstream
                             has no single-shot netlist FILE export tool.

Composed-name discipline: every `kicad.{name}` fits the 128-char bound
(`packages/api/src/solus_api/bridge/allowlist.py::COMPOSED_NAME_MAX`).
"""

# Upstream-defined tools the allowlist exposes, registered verbatim by name.
EXPOSED_UPSTREAM_TOOLS: frozenset[str] = frozenset(
    {
        "list_projects",
        "get_project_structure",
        "extract_project_netlist",
        "analyze_schematic_connections",
        "analyze_bom",
    }
)

# Solus-authored tools this overlay adds.
SOLUS_AUTHORED_TOOLS: frozenset[str] = frozenset(
    {
        "export_netlist",
        "get_symbol_definition",
        "get_schematic_geometry",
        "check_erc",
    }
)

# What the running server actually registers.
READ_ROSTER: frozenset[str] = EXPOSED_UPSTREAM_TOOLS | SOLUS_AUTHORED_TOOLS

# Solus-authored write tools (T2b). Allowlisted from day one (so no later MR
# widened an existing allowlist - integrations/mcp/CLAUDE.md rule 2); each
# carries requires_confirmation: true in allowlist.yaml.
WRITE_ROSTER: frozenset[str] = frozenset(
    {
        "set_symbol_property",
        "create_schematic",
        "add_symbol",
        "add_wire",
        "add_net_label",
        "mark_no_connect",
    }
)

# The full registered surface: reads + confirmation-gated writes.
FULL_ROSTER: frozenset[str] = READ_ROSTER | WRITE_ROSTER
