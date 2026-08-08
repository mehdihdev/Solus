"""The registered-tool roster for the altium fork (SOLUSDEV-102 ALT-4).

Mirrors `allowlist.yaml` exactly — `tests/test_overlay_allowlist_shape.py`
pins the equality, so the yaml (human-ratified) and this module (what the
trimming registrar enforces in-process) can never drift.

Staging: `FULL_ROSTER` is the ratified end state. Tools whose implementation
has not landed yet are listed in `PENDING_TOOLS` and must NOT be registered
(the registrar asserts against `registered_roster()`); ALT-6/ALT-7 shrink
`PENDING_TOOLS` to empty as they land.
"""

from __future__ import annotations

#: Upstream tools registered verbatim through the hardened trimming wrapper.
EXPOSED_UPSTREAM_TOOLS: frozenset[str] = frozenset(
    {
        "app_get_status",
        "proj_get_path",
        "proj_list_documents",
        "proj_get_stats",
        "proj_get_bom",
        "proj_get_nets",
        "proj_get_component_info",
        "list_nets",
    }
)

#: Solus-authored overlay tools (no upstream equivalent).
SOLUS_AUTHORED_TOOLS: frozenset[str] = frozenset({"export_netlist"})

#: Confirmation-gated write tools (requires_confirmation: true in the yaml).
WRITE_ROSTER: frozenset[str] = frozenset(
    {
        "proj_set_parameter",
        "sch_set_components_parameters",
    }
)

#: The ratified end-state surface — must equal the allowlist.yaml tool set.
FULL_ROSTER: frozenset[str] = EXPOSED_UPSTREAM_TOOLS | SOLUS_AUTHORED_TOOLS | WRITE_ROSTER

#: Allowlisted tools whose implementation has not landed yet — never
#: registered. Empty since ALT-6 (export_netlist, solus/netlist_export.py)
#: and ALT-7 (the write guards) landed; the staging mechanism stays so a
#: future allowlist ratification can draft ahead again.
PENDING_TOOLS: frozenset[str] = frozenset()


def registered_roster() -> frozenset[str]:
    """What the registrar must have registered after bootstrap, today."""
    return FULL_ROSTER - PENDING_TOOLS
