"""SOLUSDEV-102 ALT-5 — upstream's meta-dispatch pair is dead, twice over.

Upstream's `tool_catalog`/`tool_invoke` (registered by
`eda_agent.tools.application.register_meta_tools`, dispatching through the
`list_tools()`/`call_tool()` surface of whatever object they were registered
against — `eda_agent.tools.registry.ToolRegistry` in the minimal toolset)
can invoke ANY registered tool by name, which would make the allowlist
decorative. The overlay therefore guarantees BOTH:

1. the pair is never registered (register_meta_tools is never invoked; and
   even if it were, the TrimmingRegistrar blocks both names); and
2. the pair is unreachable in principle: every dispatch table a meta-tool
   could consult in this process — the served FastMCP's own tool table, or
   an upstream ToolRegistry — contains only roster tools, so even a
   hypothetically resurrected tool_invoke could reach nothing beyond the
   allowlist. Asserted against upstream's REAL registry and REAL tool_invoke
   implementation, not a mock of the overlay's own shim.
"""

import asyncio
from typing import Any, cast

import pytest

# The bootstrap module must run before any overlay/upstream import — keep the
# support import first (it installs sys.path + the lockfile-dep stubs).
from .test_overlay_support import (  # isort: skip
    FakeMCP,
    register_overlay,
    registered_roster,
    upstream_full_surface,
)
from .altium_paths import overlay_module

_trimming = overlay_module("trimming")
TrimmingRegistrar = _trimming.TrimmingRegistrar

META_TOOLS = ("tool_catalog", "tool_invoke")


# --- not registered -------------------------------------------------------------


def test_meta_tools_exist_upstream_so_their_absence_is_a_real_trim() -> None:
    """Guards against a re-vendor renaming the pair out from under these
    assertions: upstream's full surface still registers both."""
    surface = upstream_full_surface().tools
    for name in META_TOOLS:
        assert name in surface, f"upstream no longer registers {name} — re-review the trim"


def test_meta_tools_are_not_in_the_registered_surface() -> None:
    fake = FakeMCP()
    register_overlay(fake)
    for name in META_TOOLS:
        assert name not in fake.tools


def test_meta_tools_never_even_reach_the_registrar() -> None:
    """Dead by omission, not by trimming: register_meta_tools is never
    invoked, so the pair appears on neither the registered nor the blocked
    audit trail."""
    registrar = register_overlay(FakeMCP())
    seen = set(registrar.registered) | set(registrar.blocked)
    for name in META_TOOLS:
        assert name not in seen


def test_registrar_blocks_the_meta_pair_even_if_registration_were_attempted() -> None:
    """Defense in depth: if a future refactor ever invoked upstream's REAL
    register_meta_tools against the registrar, both names are outside the
    allowed set — blocked, with the backing server never seeing them."""
    from eda_agent.tools.application import register_meta_tools

    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=registered_roster())
    register_meta_tools(cast(Any, registrar))

    assert set(registrar.blocked) == set(META_TOOLS)
    assert registrar.registered == ()
    assert fake.tools == {}


# --- unreachable: every dispatch table in this process is trimmed ----------------


def _trimmed_upstream_registry() -> Any:
    """The overlay registration run against upstream's REAL ToolRegistry —
    the exact object whose `list_tools()`/`call_tool()` surface tool_invoke
    dispatches through in upstream's minimal toolset."""
    from eda_agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_overlay(registry)
    return registry


def test_upstreams_own_dispatch_table_holds_only_roster_tools() -> None:
    registry = _trimmed_upstream_registry()
    assert set(registry.names) == set(registered_roster())
    for name in META_TOOLS:
        assert name not in registry
        assert registry.get(name) is None


def test_upstreams_dispatch_refuses_non_roster_tools_by_name() -> None:
    """`ToolRegistry.call_tool` is the real dispatch mechanism; a non-roster
    name — meta pair included — raises its real unknown-tool refusal."""
    registry = _trimmed_upstream_registry()
    for name in ("obj_run_process", "proj_compile", *META_TOOLS):
        with pytest.raises(KeyError, match="unknown tool"):
            asyncio.run(registry.call_tool(name, {}))


def test_even_a_resurrected_tool_invoke_cannot_reach_a_trimmed_tool() -> None:
    """Worst-case drill, against upstream's REAL tool_invoke implementation:
    hand register_meta_tools a dispatch table that the overlay has already
    trimmed. Even then, invoking a non-roster tool by name comes back as
    upstream's own unknown-tool error — the table itself is trimmed, so the
    allowlist holds even if the meta pair somehow existed."""
    from eda_agent.tools.application import register_meta_tools

    registry = _trimmed_upstream_registry()
    register_meta_tools(registry)  # closes over `registry` as its dispatch table
    tool_invoke = registry.get("tool_invoke")
    assert tool_invoke is not None

    result = asyncio.run(tool_invoke.fn(name="obj_run_process", arguments={}))
    assert result == {"error": "unknown tool: obj_run_process"}

    recursion = asyncio.run(tool_invoke.fn(name="tool_invoke", arguments={}))
    assert recursion == {"error": "tool_invoke cannot invoke itself"}


def test_catalog_view_of_the_trimmed_table_omits_the_pinned_parameter() -> None:
    """Upstream's own schema view (ToolSpec.inputSchema, what tool_catalog
    would serialize) reads the hardened wrapper's signature — so even the
    catalog path cannot advertise proj_get_nets.force_recompile."""
    registry = _trimmed_upstream_registry()
    spec = registry.get("proj_get_nets")
    assert spec is not None
    assert "force_recompile" not in spec.inputSchema["properties"]


def test_the_minimal_toolset_machinery_is_never_wired_into_the_overlay() -> None:
    """The overlay's registration source drives the three module-level
    register functions only — never upstream's register_backend /
    _register_minimal, the ONLY code paths that build a live ToolRegistry
    and register the meta pair over it."""
    from .altium_paths import SOLUS_DIR

    source = (SOLUS_DIR / "registration.py").read_text(encoding="utf-8")
    for needle in ("register_backend(", "register_meta_tools(", "_register_minimal("):
        assert needle not in source, f"registration.py must never call {needle.rstrip('(')}"
