"""Wire the allowlisted roster onto a server instance (SOLUSDEV-102 ALT-5,
completed by ALT-6/ALT-7).

Only the three upstream register functions whose modules are DOMINATED by
roster tools are ever invoked against the registrar —
`register_application_tools` (app_get_status), `register_project_tools` (the
six proj_* reads plus the proj_set_parameter write), and `register_eda_tools`
(list_nets) — so their non-allowlisted siblings land on the registrar's
blocked audit trail, never on the server.

Two roster tools arrive by other means, both AFTER those three calls and
both through the SAME registrar (so they inherit the hardened wrapper —
path confinement, write guards, ctx strip, stdout diversion):

* `export_netlist` (ALT-6) — Solus-authored, `solus/netlist_export.py`,
  registered by its own `register_export_tools`.
* `sch_set_components_parameters` (ALT-7) — upstream defines it in
  `tools/generic.py`, a module whose OTHER tools (obj_run_process, the
  object mutators) are hard exclusions that must never even REACH the
  registrar's audit trail (tests pin that). Its register function therefore
  runs against an inert `_ClosureHarvester` that captures ONLY the wanted
  closure and drops everything else on the floor unregistered; the captured
  function is then registered through the registrar like any roster tool.

Never invoked against anything: upstream's `register_meta_tools` (the
tool_catalog/tool_invoke meta-dispatch pair), `register_library_tools`,
`register_pcb_tools`, `register_review_tools`, `register_sim_tools`,
`register_design_tools` (which also carries upstream's only `@mcp.prompt`
registration), `register_render_tools`, `register_audit_tools`,
`register_route_tools`, `register_kicad_tools`, `register_calc_tools`,
`register_plan_tools`, `register_parts_tools`, and the aggregates
`register_all_tools` / `register_backend` (whose minimal-toolset path is the
only place upstream's ToolRegistry dispatch table is ever populated — so
that table never exists in this process either).

NOTE: importing ONE of the upstream tool modules still executes
`eda_agent.tools.__init__`, which merely IMPORTS every tool module — imports
define register functions; nothing is registered until a register function is
invoked against a server object. Likewise the harvester invocation of
`register_generic_tools` only DEFINES that module's closures; the unwanted
ones are garbage the moment the call returns.

Tested by tests/test_overlay_tool_trimming.py,
tests/test_meta_tools_are_dead.py, tests/test_overlay_offline_degrade.py,
and tests/test_write_tool_guard.py.
"""

from collections.abc import Callable
from typing import Any, cast

from .netlist_export import register_export_tools
from .roster import registered_roster
from .trimming import SupportsToolDecorator, TrimmingRegistrar

#: Roster tools extracted by closure capture from upstream modules whose
#: register functions must not run against the registrar (see docstring).
_HARVESTED_WRITE_TOOLS = frozenset({"sch_set_components_parameters"})


class _ClosureHarvester:
    """Inert `.tool()` recorder handed to an upstream register function
    purely to EXTRACT named tool closures. Nothing is registered anywhere:
    unwanted closures are returned to upstream's register function (so its
    sibling-call internals keep working) and otherwise dropped."""

    def __init__(self, wanted: frozenset[str]) -> None:
        self._wanted = wanted
        self.captured: dict[str, Callable[..., Any]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        name_override = kwargs.get("name")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            name = name_override if isinstance(name_override, str) else fn.__name__
            if name in self._wanted:
                self.captured[name] = fn
            return fn

        return decorator


def _register_harvested_write_tools(registrar: TrimmingRegistrar) -> None:
    """Capture the allowlisted write tool out of `tools/generic.py` and
    register it through the registrar's hardened path (write guards +
    confinement included)."""
    from eda_agent.tools.generic import register_generic_tools

    harvester = _ClosureHarvester(_HARVESTED_WRITE_TOOLS)
    register_generic_tools(cast(Any, harvester))
    for name in sorted(_HARVESTED_WRITE_TOOLS):
        fn = harvester.captured.get(name)
        if fn is None:
            raise RuntimeError(f"upstream no longer defines {name} — re-vendor review required")
        registrar.tool()(fn)


def register_allowlisted_tools(mcp: SupportsToolDecorator) -> TrimmingRegistrar:
    """Register exactly `registered_roster()` on *mcp*; returns the registrar
    so callers can audit what was registered vs. blocked."""
    roster = registered_roster()
    registrar = TrimmingRegistrar(mcp, allowed=roster)

    # Imported lazily: the vendored upstream lives on sys.path only after the
    # entry module's bootstrap (or the test scaffolding) has run.
    from eda_agent.tools.application import register_application_tools
    from eda_agent.tools.eda import register_eda_tools
    from eda_agent.tools.project import register_project_tools

    # Upstream's register functions take the FastMCP instance untyped and use
    # only the @mcp.tool() decorator surface — exactly what the registrar
    # duck-types (SupportsToolDecorator). The trim depends on NOT being a real
    # FastMCP, so the mismatch is intentional, not incidental.
    shim = cast(Any, registrar)
    register_application_tools(shim)
    register_project_tools(shim)
    register_eda_tools(shim)
    # Solus-authored overlay tools and harvested write tools, registered
    # through the SAME registrar so they inherit the hardened wrapper exactly
    # like upstream roster tools.
    register_export_tools(registrar)
    _register_harvested_write_tools(registrar)

    if set(registrar.registered) != roster:
        missing = roster - set(registrar.registered)
        raise RuntimeError(
            "upstream no longer provides the allowlisted roster "
            f"(missing: {sorted(missing)}) — re-vendor review required"
        )
    return registrar
