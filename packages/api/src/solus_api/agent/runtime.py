"""The SOL reasoning-loop plumbing (SOLUS-SYS-01) — the SYSTEMS side of the seam.

This is the wiring the reasoning loop runs on, NOT the reasoning itself. It ships:

- `build_sol_registry` — assembles the per-request W0-04 `ToolRegistry`. The tool set
  and each tool's project scope are fixed HERE, by Solus code, BEFORE any model or
  ingested content is seen (CLAUDE.md §7: ingested content can never add a tool or
  change scope).
- `AgentRunContext` + `AgentRunner` — the seam Pratham's SOL-01/02 reasoning plugs into.
  A runner consumes the live context (prompt + history), the W0-04 registry, and the
  W0-07 `SolSystems` data access, and STREAMS `AgentEvent`s. The transport never learns
  which runner produced them.
- `ScaffoldRunner` — a deterministic, model-free runner (mock-and-swap, like the
  systems test double). It proves the plumbing end to end: it lists tools, invokes the
  W0-04 reference tool through the registry, pulls W0-07 graph context, respects the
  per-user SOL mode (ADR-016), and honors a bounded tool-call loop guard (§7). The real
  model-backed loop swaps in behind `AgentRunner` with NO transport or endpoint change.
"""

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from solus_contracts.extension_manifest import ExtensionManifest

    from solus_api.agent.confirmations import ParkedCall
    from solus_api.agent.deterministic import FactSources
    from solus_api.agent.drive.binding import FrontAppBinding
    from solus_api.agent.drive.executor import Budget
    from solus_api.agent.execution_policy import BuildExecutionPolicy
    from solus_api.agent.expertise import Expertise
    from solus_api.agent.research import ResearchCache
    from solus_api.agent.tools.mcp_tool import MCPTool
    from solus_api.agent.tools.shapes import ToolCall as _ToolCallHint
    from solus_api.agent.tools.simulate import SimEnqueue
    from solus_api.agent.tools.tool import Tool
    from solus_api.bridge.allowlist import BridgeToolSpec
    from solus_api.bridge.registry import BridgeSessionRegistry
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.graph.live import LiveHub
    from solus_api.services.code_environment_adapter import EnvironmentFetch
    from solus_api.storage import ArtifactStore
    from solus_api.widgets.capability import WidgetCapability

    #: Parks a gated call for approval; None when the call is not gated.
    ParkFn = Callable[[_ToolCallHint], Awaitable[ParkedCall | None]]
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent import citations, prompt, reason, reasoning_frame, screen, turn_scope
from solus_api.agent.command_auto import AUTO_COMMAND_TOOL, model_result, stream_view
from solus_api.agent.context import Context, build_context
from solus_api.agent.deterministic import DeterministicAnswer, answer_first_tier, first_tier_events
from solus_api.agent.errors_filing import file_tool_error
from solus_api.agent.front_app import front_app_block
from solus_api.agent.guide_toolkb_version import placed_tools
from solus_api.agent.interfaces import GraphScope, SolSystems
from solus_api.agent.modes import ActionMode
from solus_api.agent.project_card import CardInputs, project_card_section
from solus_api.agent.research import ResearchStep, model_visible, withhold_server_driven
from solus_api.agent.sol_anchors import resolve_anchor_inputs
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools import (
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolRegistry,
    ToolResult,
    build_get_entity_tool,
)
from solus_api.agent.tools.exec import run_tool
from solus_api.agent.tools.flash_history import record_tool_history
from solus_api.agent.turn_budget import BudgetHit, TurnBudget
from solus_api.agent.turn_limits import GUIDE_MODEL_ROUNDS, GUIDE_TOOL_CALLS, turn_limits
from solus_api.models import SolMode
from solus_api.orchestration import bump_complexity, estimate_complexity, gateway
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.providers import ToolConversation, ToolOutcome, Turn
from solus_api.orchestration.router import derive_complexity
from solus_api.orchestration.type_estimator import (
    estimate_tokens,
    round_one_complexity,
    round_one_route_type,
)

# §7 loop/recursion guard: an upper bound on tool calls per turn so a runaway loop
# can never fan out unboundedly. The scaffold proposes ≤1; the guard protects the seam
# for the real runner that swaps in later.
MAX_TOOL_CALLS = GUIDE_TOOL_CALLS
#: The companion's ungated inventory read, by its composed bridge name. Feeds
#: `link_environment` the facts the model is not allowed to supply.
_CODE_ENVIRONMENTS: Final = "code.probe_environment"
# Graph traversal depth for the scaffold's W0-07 context pull (the 2-degree perf lever).
_CONTEXT_DEGREE = 1

# The shared UUID parser lives in reason.py (one instance, no drift).
_UUID_RE = reason.UUID_RE

#: A preview read is a live round-trip to the machine (SOLUSDEV-251); bounded.
_PREVIEW_READ_TIMEOUT_SECONDS = 8.0

logger = logging.getLogger("solus.agent.runtime")


def build_sol_registry(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    bridge: "BridgeSessionRegistry | None" = None,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    bridge_call_cap_bytes: int = 262_144,
    secret_store: "SecretStore | None" = None,
    connectors: "ConnectorRegistry | None" = None,
    systems: SolSystems | None = None,
    hosted_inventory: "Mapping[str, Any] | None" = None,
    redis: Any | None = None,
    bundle_capabilities: "Sequence[tuple[WidgetCapability, ExtensionManifest]] | None" = None,
    artifact_store: "ArtifactStore | None" = None,
    enqueue: Any | None = None,
    artifact_ttl_seconds: int | None = None,
    brave_tools: "Sequence[MCPTool] | None" = None,
    presence_service: Any | None = None,
    companion_deployment_service: Any | None = None,
    scene_enqueue: Any | None = None,
    drive_budget: "Budget | None" = None,
    graph_hub: "LiveHub | None" = None,
    enqueue_sim: "SimEnqueue | None" = None,
    artifact_max_bytes: int | None = None,
) -> ToolRegistry:
    """Assemble the tool set SOL may invoke for ONE request, each tool bound to the
    request's project scope by Solus code. v1 exposes the W0-04 reference tool; new
    tools are registered here, never proposed by a model.

    When a bridge session registry + full scope are supplied (SOLUSDEV-154), one
    BridgeTool per model-facing entry of the LIVE cloud-validated inventory is added —
    the turn's tool set reflects the requesting user's connected companion at turn
    start, fixed here before any model or ingested content is seen. The bridge
    package relays JSON only, so the reasoning import graph stays MCP-free."""
    registry = ToolRegistry()
    _register_scene(registry, session_factory, project_id, user_id, scene_enqueue)
    _register_presence(registry, presence_service)
    _register_companion_deployment(registry, companion_deployment_service)
    registry.register(build_get_entity_tool(session_factory, project_id))
    # The bridge tools come FIRST: the machine's own `list_environments` read is
    # what `link_environment` (a user tool) files from, and a tool cannot be built
    # from an inventory that has not been walked yet.
    fetch_environments: EnvironmentFetch | None = None
    if bridge is not None and user_id is not None and team_id is not None:
        fetch_environments = _register_bridge_tools(
            registry,
            session_factory,
            project_id,
            bridge=bridge,
            user_id=user_id,
            team_id=team_id,
            bridge_call_cap_bytes=bridge_call_cap_bytes,
            secret_store=secret_store,
        )
    _register_drive_step(
        registry,
        session_factory,
        project_id,
        bridge=bridge,
        user_id=user_id,
        team_id=team_id,
        call_cap_bytes=bridge_call_cap_bytes,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
        budget=drive_budget,
    )
    if user_id is not None:
        _register_user_tools(
            registry,
            session_factory,
            project_id,
            user_id=user_id,
            artifact_store=artifact_store,
            secret_store=secret_store,
            redis=redis,
            enqueue=enqueue,
            artifact_ttl_seconds=artifact_ttl_seconds,
            fetch_environments=fetch_environments,
            graph_hub=graph_hub,
            enqueue_sim=enqueue_sim,
        )
    # SOLUSDEV-321 P5 (R104, D10): SOL looks at one labelled view, as the requesting person;
    # absent without the person, their team and both stores (the guard is in the call).
    from solus_api.agent.vision.render_view import register_render_view_tool

    register_render_view_tool(
        registry,
        session_factory,
        project_id,
        user_id=user_id,
        team_id=team_id,
        secret_store=secret_store,
        artifact_store=artifact_store,
        artifact_ttl_seconds=artifact_ttl_seconds,
        connectors=connectors,
        bridge=bridge,
        bridge_call_cap_bytes=bridge_call_cap_bytes,
        artifact_max_bytes=artifact_max_bytes,
        redis=redis,
        enqueue=enqueue,
    )
    # SOLUSDEV-321 P6 (R134): firmware from the topology, written only through machine.write_file's
    # card; absent without the person, their team, the secret store and that owned write.
    from solus_api.agent.firmware_recipe import register_firmware_recipe

    register_firmware_recipe(
        registry,
        session_factory,
        project_id,
        user_id=user_id,
        team_id=team_id,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
    )
    if systems is not None:
        # SYS-03: the four builtin reads (query_graph / get_telemetry /
        # retrieve_errors / run_checkers) as thin closures over the real
        # SolSystems, sharing build_context's data paths. Function-local import
        # (house pattern) so the reasoning import graph grows the checker
        # dependency only when wired.
        from solus_api.agent.tools.builtin import build_builtin_tools
        from solus_api.agent.tools.rail_current import build_rail_current_tool

        for tool in build_builtin_tools(systems, project_id, session_factory=session_factory):
            registry.register(tool)
        registry.register(build_rail_current_tool(systems, project_id))
    if connectors is not None:
        from solus_api.agent.tools.read_code_file import build_read_code_file_tool

        registry.register(
            build_read_code_file_tool(
                session_factory,
                project_id,
                secret_store=secret_store,
                connectors=connectors,
                bridge=bridge,
                user_id=user_id,
                team_id=team_id,
                bridge_call_cap_bytes=bridge_call_cap_bytes,
            )
        )
        # SOLUS-ONS-A1: Onshape operations as in-process tools. Function-local
        # import for the same reason the bridge one is — the reasoning import
        # graph must not grow a connector dependency. Each tool is bound to THIS
        # project and resolves the team's stored OAuth credentials per call.
        # Registered ALONGSIDE the SOLX-04 tools below, not instead of them: the
        # two sets are disjoint (`onshape.*` vs `solus.*`) and answer different
        # questions — connecting a source versus operating one.
        from solus_api.agent.execution_policy import register_owned_routine
        from solus_api.agent.tools.onshape_tools import build_onshape_tools

        for tool in build_onshape_tools(
            session_factory, project_id, secret_store=secret_store, connectors=connectors
        ):
            register_owned_routine(tool, family="onshape")
            registry.register(tool)
    if connectors is not None and user_id is not None and team_id is not None:
        # SOLX-04: connecting a tool is a SOL action. Function-local import so
        # the reasoning import graph only touches connectors when wired.
        from solus_api.agent.connect_integration import (
            ConnectIntegrationDeps,
            build_integration_tools,
        )

        deps = ConnectIntegrationDeps(
            session_factory=session_factory,
            project_id=project_id,
            team_id=team_id,
            user_id=user_id,
            connectors=connectors,
        )
        for tool in build_integration_tools(deps):
            registry.register(tool)
    if hosted_inventory:
        _register_hosted_tools(
            registry,
            session_factory,
            project_id,
            secret_store=secret_store,
            hosted_inventory=hosted_inventory,
            redis=redis,
        )
    _register_bundle_tools(
        registry, session_factory, project_id, user_id=user_id, bundles=bundle_capabilities or ()
    )
    _register_research_tool(registry, brave_tools or ())
    return registry


def _register_research_tool(registry: ToolRegistry, brave_tools: "Sequence[MCPTool]") -> None:
    """SOLUSDEV-252 P6: the web `research` tool. Discovery is async and spawns the
    vendored Brave fork, so it happens in `deps.get_sol_registry` (request scope)
    and only its RESULT reaches this synchronous assembly. With no brave tools
    the loop is not registered at all — SOL learns from the capability's absence
    rather than from a failure per call.

    ponytail: nothing bounds research per team beyond MAX_MODEL_ROUNDS, and every
    tenant shares one `brave_api_key` — per-team research budgets are the named
    upgrade path (ADR-019)."""
    if not brave_tools:
        return
    from solus_api.agent.tools.research_tool import register_research_tool

    register_research_tool(registry, brave_tools=brave_tools)


def _register_user_tools(
    registry: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    artifact_store: "ArtifactStore | None",
    secret_store: "SecretStore | None" = None,
    redis: Any | None = None,
    enqueue: Any | None = None,
    artifact_ttl_seconds: int | None = None,
    fetch_environments: "EnvironmentFetch | None" = None,
    graph_hub: "LiveHub | None" = None,
    enqueue_sim: "SimEnqueue | None" = None,
) -> None:
    """Tools that act AS the requesting user (their id is recorded on every row).
    Function-local imports throughout (house pattern)."""
    # SOLUSDEV-321 P4-T4 (R90, R110): `get_sim_result`; with the app's hub, `simulate` and the gated
    # `apply_sim_change`. No model call: rungs 1 and 3 are code, rungs 2 and 4 named gated tools.
    from solus_api.agent.tools.simulate import register_simulation_tools

    register_simulation_tools(
        registry,
        session_factory,
        project_id,
        user_id=user_id,
        hub=graph_hub,
        enqueue_sim=enqueue_sim,
    )
    # SOLUSDEV-240: SOL may file a note into the project `.solus`.
    from solus_api.agent.tools.solus_entry import build_add_solus_entry_tool

    registry.register(build_add_solus_entry_tool(session_factory, project_id, user_id=user_id))
    # SOLUSDEV-246 (STORE ST5): a READ — torque is Solus arithmetic over the
    # graph, never the model's.
    from solus_api.sourcing.tools import build_derive_torque_tool

    registry.register(build_derive_torque_tool(session_factory, project_id))
    from solus_api.agent.tools.environment import build_resolve_environment_tool

    registry.register(build_resolve_environment_tool(session_factory, project_id))
    # SOLUSDEV-321 P1-T4: the retrieval tools — ungated reads that let the model look things up
    # itself. They read AS this user (`get_machine`'s owner rule), so they need one.
    from solus_api.agent.tools.finding_tools import register_finding_tools
    from solus_api.agent.tools.machine_tools import register_machine_tools
    from solus_api.agent.tools.search_tools import register_search_tools

    register_search_tools(registry, session_factory, project_id)
    register_finding_tools(registry, session_factory, project_id)
    register_machine_tools(registry, session_factory, project_id, user_id=user_id)
    if secret_store is not None:
        # SOLUSDEV-321 P3-T4 (R57): the one model path for netlist motifs, metered as this user.
        from solus_api.agent.tools.label_motifs import register_label_motifs_tool

        register_label_motifs_tool(
            registry,
            session_factory,
            project_id,
            user_id=user_id,
            secret_store=secret_store,
            redis=redis,
            enqueue=enqueue,
        )
    if artifact_store is not None:
        # SOLUSDEV-252 S5: SOL draws a diagram into a TTL artifact (ungated, like
        # add_solus_entry — see make_diagram.py). Needs the store the artifacts
        # route serves from, so the reference it returns is fetchable.
        from solus_api.agent.tools.make_diagram import register_diagram_tools

        register_diagram_tools(
            registry,
            session_factory=session_factory,
            store=artifact_store,
            project_id=project_id,
            user_id=user_id,
        )
        # SOLUSDEV-252 S5: the GATED `.solus` writers (edit / delete / hardware
        # config field). Every one carries a preview and requires_confirmation,
        # so they reach dispatch through the same park-and-approve gate as any
        # other destructive tool — the registry stays a pure dispatcher.
        from solus_api.agent.tools.solus_tools import register_solus_write_tools

        register_solus_write_tools(
            registry,
            session_factory=session_factory,
            store=artifact_store,
            project_id=project_id,
            user_id=user_id,
            # Present only with a connected companion: `link_environment` files
            # what the machine reports, so with no machine there is nothing to
            # offer (S5, "creates and links environments").
            fetch_environments=fetch_environments,
        )
        if secret_store is not None:
            # SOLUSDEV-252 S5c: read a datasheet (fetch or a stored artifact),
            # render it, and extract specs with page citations; the second tool
            # (proposing a part definition) is gated. Needs the secret store,
            # redis and the enqueue seam because the extraction is a METERED
            # model call through the gateway.
            from solus_api.agent.tools.read_document import register_document_tools
            from solus_api.agent.tools.rulebook_tools import register_rulebook_tool

            ttl = (
                {"artifact_ttl_seconds": artifact_ttl_seconds}
                if artifact_ttl_seconds is not None
                else {}
            )
            # SOLUSDEV-321 P3-T4 (R58): `extract_rulebook` reads a filed rulebook through the
            # same extractor and returns candidate constraints; it files nothing.
            for register in (register_document_tools, register_rulebook_tool):
                register(
                    registry,
                    session_factory=session_factory,
                    store=artifact_store,
                    project_id=project_id,
                    user_id=user_id,
                    secret_store=secret_store,
                    redis=redis,
                    enqueue=enqueue,
                    **ttl,
                )


def _register_bundle_tools(
    registry: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
    bundles: "Sequence[tuple[WidgetCapability, ExtensionManifest]]",
) -> None:
    """SOLUSDEV-246 (STORE ST1): first-party bundle tools, one `InProcessTool`
    per name the PINNED manifest declares, built by the in-repo capability and
    bound to this request's project/user. The caller (`deps.get_sol_registry`)
    decided which bundles are installed, enabled and unblocked; this is pure
    assembly. Wrapped per bundle like the hosted path: a capability that fails
    to build is logged and skipped — never a 500 for every SOL request."""
    from solus_contracts.extension_manifest import composed_tool_name

    from solus_api.widgets.capability import BundleScope

    for capability, manifest in bundles:
        scope = BundleScope(
            session_factory=session_factory,
            project_id=project_id,
            user_id=user_id,
            manifest=manifest,
        )
        try:
            for name in manifest.tools.names:
                builder = capability.tools.get(name)
                if builder is None:
                    logger.warning(
                        "bundle %s declares tool %s it does not provide", capability.id, name
                    )
                    continue
                tool = builder(scope)
                expected = composed_tool_name(capability.id, name)
                if tool.descriptor.name != expected:
                    raise ValueError(f"tool {tool.descriptor.name!r} must be named {expected!r}")
                registry.register(tool)
        except Exception:
            logger.exception(
                "bundle %s tools unavailable for project %s", capability.id, project_id
            )


def _register_hosted_tools(
    registry: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    secret_store: "SecretStore | None",
    hosted_inventory: "Mapping[str, Any]",
    redis: Any | None,
) -> None:
    """SOLUSDEV-168: vendor-hosted MCP servers (Onshape Labs' FeatureScript),
    authenticated as the CUSTOMER.

    Built from the inventory the CONNECT step discovered and persisted. This
    function is synchronous and does zero I/O by design: live discovery here
    would put a 30s-bounded network round-trip on every message, every
    confirmation decision, and every `GET /sol/tools` — the one route in that
    file with no role floor. Same shape as the bridge inventory below.

    Wrapped, because a hosted server must never be able to take the agent
    offline: a stored inventory that somehow yielded a duplicate NAME would
    raise out of `register` at wiring time and 500 every SOL request for this
    project — including the one that would REJECT an already-parked destructive
    action.
    """
    from solus_api.agent.tools.hosted_tools import build_hosted_tools

    try:
        for tool in build_hosted_tools(
            session_factory,
            project_id,
            secret_store=secret_store,
            inventory=hosted_inventory,
            redis=redis,
        ):
            registry.register(tool)
    except Exception:
        logger.exception("hosted MCP tools unavailable for project %s", project_id)


def _register_drive_step(
    registry: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    bridge: "BridgeSessionRegistry | None",
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    call_cap_bytes: int,
    secret_store: "SecretStore | None",
    redis: Any,
    enqueue: Any,
    budget: "Budget | None",
) -> None:
    """ADR-041: `drive.step` — the only model-facing way to the internal drive
    tools, offered when this user's companion advertises all of them and the
    metered model call has a secret store."""
    tool = _drive_step_tool(
        session_factory,
        project_id,
        bridge=bridge,
        user_id=user_id,
        team_id=team_id,
        call_cap_bytes=call_cap_bytes,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
        budget=budget,
    )
    if tool is not None:
        registry.register(tool)


def _drive_step_tool(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    bridge: "BridgeSessionRegistry | None",
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    call_cap_bytes: int,
    secret_store: "SecretStore | None",
    redis: Any,
    enqueue: Any,
    budget: "Budget | None",
    front_app: "FrontAppBinding | None" = None,
) -> "Tool | None":
    if bridge is None or user_id is None or team_id is None or secret_store is None:
        return None
    from solus_api.agent.drive.executor import Budget
    from solus_api.agent.drive.wiring import build_drive_step

    return build_drive_step(
        bridge=bridge,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        call_cap_bytes=call_cap_bytes,
        session_factory=session_factory,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
        budget=budget or Budget(),
        front_app=front_app,
    )


def with_front_app(
    registry: ToolRegistry,
    front_app: "FrontAppBinding | None",
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    bridge: "BridgeSessionRegistry | None",
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    call_cap_bytes: int,
    secret_store: "SecretStore | None",
    redis: Any,
    enqueue: Any,
    budget: "Budget | None",
) -> ToolRegistry:
    """SOLUSDEV-319 slice 4 (sol-drive.md §2.2): this turn's registry with `drive.step`
    rebuilt from the turn's `front_app`, so it offers `app: "front"` — bound to exactly
    that window — only when the app is drivable and window-bound. The rebuild goes
    through the same scope (this user's own companion for this team and project); with
    no window, no drive.step in the registry, or no companion, the registry is returned
    unchanged. A new registry, never a mutation: the per-request dependency stays as built."""
    if front_app is None or front_app.window() is None:
        return registry
    current = {tool.descriptor.name: tool for tool in registry.tools()}
    fronted = _drive_step_tool(
        session_factory,
        project_id,
        bridge=bridge,
        user_id=user_id,
        team_id=team_id,
        call_cap_bytes=call_cap_bytes,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
        budget=budget,
        front_app=front_app,
    )
    if fronted is None or fronted.descriptor.name not in current:
        return registry
    out = ToolRegistry()
    for name, tool in current.items():
        out.register(fronted if name == fronted.descriptor.name else tool)
    return out


def _internal_only(spec: "BridgeToolSpec") -> bool:
    """Bridge tools Solus code dispatches but the model is never offered."""
    # `exposure: internal` (sol-drive.md §3): accepted from the companion for
    # Solus code to dispatch — the ADR-041 drive executor calls `drive.act`.
    if spec.internal:
        return True
    # Internal simulator inputs carry resolved graph data. Only the owned
    # graph adapter may expose Isaac operations to SOL.
    if spec.server == "isaac" or spec.descriptor.name.startswith("isaac."):
        return True
    # Automatic code reads must resolve graph identity and the turn's selected
    # revision through read_code_file. Keep this native primitive available to
    # that wrapper's internal dispatch, never as a model-visible fallback.
    # The separate general machine.read_file remains confirmation-gated.
    # SOLUSDEV-321 P5 (D2, R125): a `returns_image` export is reached only through
    # `render_view`, which consumes and checks its one artifact; never the model.
    return spec.descriptor.name == "machine.read_code_file" or spec.returns_image


def _register_bridge_tools(
    registry: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    bridge: "BridgeSessionRegistry",
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    bridge_call_cap_bytes: int,
    secret_store: "SecretStore | None",
) -> "EnvironmentFetch | None":
    """Register model-facing entries from the live cloud-validated inventory.

    Native graph-reader primitives stay internal to their scoped wrappers.

    Returns the machine's environment read (`code.probe_environment`) as a
    plain callable when this companion advertises it, so `link_environment` can
    file OBSERVED environments without reaching into the registry. This is the
    only place a tool handle is invoked outside the gated dispatcher, and it is
    deliberate: `list_environments` is the ungated read of the same inventory the
    model already sees, and the write it feeds is itself gated (SEC-H4).

    Function-local imports like BridgeTool itself: the reasoning import graph
    stays MCP-ignorant; the catalog is consulted only when a bridge is wired."""
    from solus_api.agent.execution_policy import register_owned_routine
    from solus_api.agent.tools.mcp_servers import (
        MCP_SERVER_CATALOG,
        build_license_preflight,
    )
    from solus_api.agent.tools.mcp_tool import LicenseTier
    from solus_api.bridge.previews import preview_builder
    from solus_api.bridge.tool import BridgeTool

    session = bridge.get(user_id, team_id, project_id)
    if session is None:
        return None
    environments: EnvironmentFetch | None = None
    tools: list[BridgeTool] = []
    for spec in session.inventory:
        if _internal_only(spec):
            continue
        # MCP-05: byo_paid servers get the invoke-time license gate;
        # free-tier and uncataloged servers get zero new checks.
        catalog_spec = MCP_SERVER_CATALOG.get(spec.server)
        preflight = None
        if catalog_spec is not None and catalog_spec.license_tier is LicenseTier.BYO_PAID:
            preflight = build_license_preflight(
                catalog_spec,
                session_factory=session_factory,
                user_id=user_id,
                team_id=team_id,
                secret_store=secret_store,
            )
        tool = BridgeTool(
            descriptor=spec.descriptor,
            sessions=bridge,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            call_cap_bytes=bridge_call_cap_bytes,
            preflight=preflight,
            # SOLUSDEV-251: a companion WRITE previews by reading through the
            # same bridge first, so the approval card shows before → after.
            # The reader carries the SAME license preflight as the tool
            # (review M1): a BYO-paid server never yields a free read.
            preview=preview_builder(
                spec.descriptor.name,
                _bridge_reader(
                    bridge, user_id, team_id, project_id, bridge_call_cap_bytes, preflight
                ),
            ),
        )
        tools.append(tool)
        register_owned_routine(tool, family="bridge")
        # BOTH conditions, every time. The name pins WHICH tool and the gate flag
        # pins WHAT KIND of tool may be reached this way: a rename in the machine
        # allowlist must lose `link_environment`, and a gated tool must never be
        # reachable from here even if it somehow answered to this name. The
        # default-argument bind is what keeps the closure on THIS spec rather
        # than late-binding to the last one in the loop.
        if spec.descriptor.name == _CODE_ENVIRONMENTS and not spec.descriptor.requires_confirmation:

            async def environments(
                environment: str | None = None, _tool: "BridgeTool" = tool
            ) -> Any:
                from solus_api.services.code_environment_adapter import observed_environments

                return observed_environments(
                    await _tool.invoke(
                        {"environment": environment} if environment is not None else {}
                    )
                )

    from solus_api.agent.tools.ros_live import live_graph_tool
    from solus_api.services.code_environment_adapter import with_environment_recording

    for owned_tool in _owned_isaac_tools(
        session_factory, project_id, bridge, user_id, team_id, bridge_call_cap_bytes
    ):
        register_owned_routine(owned_tool, family="isaac")
        registry.register(owned_tool)

    for tool in tools:
        registered = with_environment_recording(
            _owned_machine_tool(tool), environments, session_factory, project_id, user_id
        )
        # SOLUSDEV-321 P6 (R131): the live ROS reads also raise the standing edges they name.
        registered = live_graph_tool(
            registered, session_factory, project_id, user_id=user_id, team_id=team_id
        )
        # §10.1: marks the plan-snapshot `code.exec` only; every other tool is a no-op.
        register_owned_routine(registered, family="command")
        registry.register(registered)
    return environments


def _owned_machine_tool(tool: "Tool") -> "Tool":
    from solus_api.agent.execution_policy import register_owned_routine
    from solus_api.agent.tools.machine_writes import build_machine_write_tool

    if tool.descriptor.name != "machine.write_file":
        return tool
    writer = build_machine_write_tool(tool)
    register_owned_routine(writer, family="machine")
    return writer


def _owned_isaac_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    bridge: "BridgeSessionRegistry",
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    call_cap_bytes: int,
) -> list["Tool"]:
    from solus_api.agent.tools.isaac_tools import build_isaac_tools
    from solus_api.bridge.tool import BridgeTool

    session = bridge.get(user_id, team_id, project_id)
    if session is None:
        return []
    raw = {
        spec.descriptor.name: BridgeTool(
            descriptor=spec.descriptor,
            sessions=bridge,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            call_cap_bytes=call_cap_bytes,
        )
        for spec in session.inventory
        if spec.server == "isaac" and spec.descriptor.name.startswith("isaac.")
    }
    return build_isaac_tools(session_factory, project_id, raw)


def _bridge_reader(
    bridge: "BridgeSessionRegistry",
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    call_cap_bytes: int,
    preflight: "Callable[[], Awaitable[None]] | None" = None,
) -> "Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]":
    """One bounded read over the caller's OWN live session; None on any decline
    (offline, tool not offered, preflight refusal, timeout, failure)."""
    from solus_api.bridge.service import dispatch

    async def read(tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        session = bridge.get(user_id, team_id, project_id)
        if session is None or not any(t.descriptor.name == tool for t in session.inventory):
            return None
        try:
            if preflight is not None:
                await preflight()
            async with asyncio.timeout(_PREVIEW_READ_TIMEOUT_SECONDS):
                result = await dispatch(session, tool, args, call_cap_bytes=call_cap_bytes)
        except Exception:  # noqa: BLE001 — a preview read declines, never raises
            return None
        return result.value if result.ok and isinstance(result.value, dict) else None

    return read


def parse_entity_ids(prompt: str) -> list[uuid.UUID]:
    """Extract any UUIDs the user referenced — the scaffold's deterministic stand-in
    for 'the model decided to look this entity up'. Malformed ids are ignored."""
    found: list[uuid.UUID] = []
    for match in _UUID_RE.findall(prompt):
        try:
            found.append(uuid.UUID(match))
        except ValueError:  # pragma: no cover - regex already constrains the shape
            continue
    return found


def plan_tool_calls(prompt: str) -> list[ToolCall]:
    """Deterministically map a prompt → the tool calls to make. The scaffold looks up
    the first referenced entity via the W0-04 reference tool; it NEVER selects a tool
    from anything the ingested prompt says to do (§7)."""
    anchors = parse_entity_ids(prompt)
    if not anchors:
        return []
    return [ToolCall(tool="get_entity", args={"entity_id": str(anchors[0])})]


@dataclass(frozen=True)
class TurnView:
    """A read-only view of a prior turn fed to the runner as live context."""

    role: str
    content: str


@dataclass(frozen=True)
class AgentRunContext:
    """Everything a runner needs for one turn. Assembled by Solus code per request;
    the tool set and `project_id` are already scoped before the runner runs.

    **A runner is handed no object it can dispatch through.** It gets DESCRIPTORS
    (what may be called) and `dispatch` (the only way to call anything), and
    `dispatch` gates before it invokes. "Every runner MUST consult the gate" was
    previously a comment and a merge-blocker convention; now a runner holds
    nothing with an `invoke` method, so ungated dispatch is unwritable rather
    than merely forbidden (CLAUDE.md §7 — prefer structure to instructions).
    """

    prompt: str
    #: What the model may be offered. Fixed by Solus code before the runner runs
    #: and never derived from prompt content.
    tools: tuple[ToolDescriptor, ...]
    #: The ONLY path from a proposed call to a result. Gates, then invokes.
    dispatch: "DispatchFn"
    systems: SolSystems
    project_id: uuid.UUID
    sol_mode: SolMode = SolMode.GUIDE
    #: SOLX-01: how SOL may ACT this turn — Guide (explain + point) or Do
    #: (operate the tool). A different axis from `sol_mode`, which only sets the
    #: tone of prose. Enforcement is structural: `dispatch` is built mode-wrapped
    #: (see modes.build_mode_dispatch), this field just makes the choice explicit
    #: and inspectable. Guide is the safe default — it never mutates.
    action_mode: ActionMode = ActionMode.GUIDE
    executed_build_calls: set[str] = field(default_factory=set)
    #: S1-W3: the composer's "Think harder". One tier above what the estimator
    #: says the live message needs (HARD stays HARD), passed to the gateway as an
    #: EXPLICIT tier — so on window overflow it refuses rather than escalates,
    #: the documented override semantics. Never a model name.
    think_harder: bool = False
    #: SOLUSDEV-233: the user's saved preference note. Reaches the prompt only
    #: through prompt.system_prompt's fenced data block, never as raw text.
    custom_instruction: str | None = None
    #: SOLUSDEV-244: the person's engineering conventions (from their own
    #: `~/.solus/preferences.json`, attached to the turn and validated by
    #: `agent/preferences.py`), already labelled. Reaches the prompt only through
    #: prompt.system_prompt's fenced data block, never as raw text.
    engineering_preferences: Mapping[str, str] | None = None
    #: SOLUSDEV-321 P6: the levels the turn speaks to (`expertise.turn_expertise`, the person's
    #: stated levels winning); the system prompt's one register line comes from them alone.
    expertise: "Expertise | None" = None
    history: tuple[TurnView, ...] = ()
    #: SOLUSDEV-321 P0-T4: the turn's fences use `prompt.conversation_nonce` of this,
    #: so its prompt prefix is byte-stable across the conversation; None mints a fresh one.
    conversation_id: uuid.UUID | None = None
    #: SOLUSDEV-321 P0-T5: what the route read for layer 2 — the card cache and this request's
    #: own inputs (agent/project_card.py). None leaves the layer honestly empty.
    project_card: "CardInputs | None" = None
    #: SOLUSDEV-321 P1-T2: the facts the first tier answers lookups from — the route's
    #: `GraphFactSources`, bound to this project and user. None (tests, other runners) skips
    #: the first tier: every turn goes to the model.
    facts: "FactSources | None" = None
    #: SOLUSDEV-321 P1-T5: the query the composer's `/web <q>` carried (see
    #: `research.strip_web_command`; the route sets it from the person's own message), else None.
    #: The prompt keeps the full text.
    research_query: str | None = None
    #: The shared 7-day research cache; None runs every research uncached.
    research_cache: "ResearchCache | None" = None
    #: False for a turn whose prompt Solus wrote (a wake or resume turn embeds a ticket's
    #: program, which may say "search"): the web is for the person's own words only.
    research_allowed: bool = True
    #: SOLUSDEV-168: graph entities the user pointed at explicitly (the
    #: composer's `@`). They become the neighbourhood's anchors, so SOL is
    #: grounded on the node the user meant rather than on whatever similarity
    #: search surfaced. Untrusted ids: `load_neighborhood` is project-scoped, so
    #: one from another team yields nothing rather than leaking.
    mentions: tuple[uuid.UUID, ...] = ()
    #: SOLUSDEV-321 P0-T3: the other things the turn was pointed at, each an anchor with its
    #: own reason (`turn_scope.plan_scope`). `focus` is the workspace focus the SOL page sent
    #: with the turn (auto-sent: a stale id in it is dropped, not refused); `pins` the chat's
    #: pinned nodes (a selection, like `mentions`); `finding_id` / `robot_id` the finding or
    #: bench robot the person asked from. Untrusted ids: the route has refused the ones it
    #: could not see, and `load_neighborhood` is project-scoped regardless.
    focus: reason.FocusIn | None = None
    pins: tuple[uuid.UUID, ...] = ()
    finding_id: uuid.UUID | None = None
    robot_id: uuid.UUID | None = None
    #: Entities this conversation's recent tool calls named, newest first (at most eight).
    #: Hints for the planner to weigh; they anchor nothing by themselves.
    history_entity_ids: tuple[uuid.UUID, ...] = ()
    interaction_context: InteractionContext = InteractionContext.SOL_OPEN_QUESTION
    #: Model-call identity (ADR-018). A runner that makes a PAID call MUST refuse
    #: without these: `gateway.complete` defaults them to None and then silently
    #: skips every rate limit and every debit, so inheriting that default would
    #: be an unmetered, unlimited model path. Optional in the signature only so
    #: the model-free ScaffoldRunner and its tests construct unchanged.
    user_id: uuid.UUID | None = None
    #: SOLUSDEV-321 P1-T1: this turn's id on the gateway calls it makes (`turn_id=`), so they
    #: can be counted (P1-T3) and persisted (P8). Minted with the run context.
    turn_id: uuid.UUID = field(default_factory=uuid.uuid4)
    #: A SESSIONMAKER, not a session: the request session is already closed by
    #: the time the SSE body streams (which is why `_persist_turn` and `park`
    #: each open their own), so a debit against it would silently fail.
    sessionmaker: "async_sessionmaker[AsyncSession] | None" = None
    secret_store: "SecretStore | None" = None
    redis: Any = None
    enqueue: Any = None
    #: SOLUSDEV-235 / ADR-035 §2: the extension whose `sol.ask` started this
    #: turn, verified by the route against the project's installs (never from
    #: prompt content). Attribution only — the debit stays on `user_id`.
    extension_id: uuid.UUID | None = None
    #: Phase 4 H2: the attributed extension's validated slug. When set, the
    #: live message is framed as an extension REQUEST (prompt.extension_request)
    #: rather than as the user's own words — the extension's text is fenced
    #: data under Solus-authored framing, never first-class user text.
    extension_slug: str | None = None
    #: SOLUSDEV-252 S3 (sol-window.md §8): the screenshot the person attached,
    #: already decoded and sniffed by the route. Pixels for THIS turn only: the
    #: extractor pass reads them, the live user Turn carries them, the
    #: transcript never sees them.
    screenshot: "screen.ScreenshotBlock | None" = None
    #: SOLUSDEV-319 slice 4 (sol-drive.md §2.2): the app the person summoned SOL over,
    #: for THIS turn only — never stored. Its route ordering reaches the system prompt
    #: (`front_app.route_note`); its name and title only the live turn's fenced block.
    front_app: "FrontAppBinding | None" = None


#: A proposed call → its result. The gate is inside; see `build_dispatch`.
DispatchFn = Callable[[ToolCall], Awaitable[ToolResult]]


def confirmation_refusal(registry: ToolRegistry, call: ToolCall) -> ToolResult | None:
    """The CENTRAL destructive-action gate (CLAUDE.md §7, SEC-H1). A tool whose
    descriptor carries `requires_confirmation` reaches this fallback only when
    the trusted Build routine policy has not authorized its concrete action.

    This is the FALLBACK: a flat refusal, used when no confirmation flow is
    wired. When a `park` IS supplied to `build_dispatch` (SOLUS-ONS-A5) the call
    is parked for approval instead — see `gate_tool_call`. Either way a
    unclassified or destructive tool is never dispatched from inside a turn.

    A runner cannot skip this: `build_dispatch` fuses gate-then-invoke into one
    callable and hands out only that, so no runner ever holds the registry (the
    registry itself stays a pure dispatcher per the W0-04 contract). The
    guarantee is structural rather than a rule reviewers must enforce."""
    descriptor = next((d for d in registry.list() if d.name == call.tool), None)
    if descriptor is not None and descriptor.requires_confirmation:
        return ToolResult.failure(
            call.call_id,
            ToolError(
                code=ToolErrorCode.UNAUTHORIZED,
                message=(
                    f"{call.tool} is a destructive action requiring explicit user "
                    "confirmation; the confirmation flow is not yet available"
                ),
                retryable=False,
            ),
        )
    return None


async def gate_tool_call(
    registry: ToolRegistry, park: "ParkFn | None", call: ToolCall
) -> ToolResult | None:
    """The §7 gate. `None` means "safe, dispatch".

    With a confirmation flow wired, a destructive call is PARKED — recorded with
    the exact arguments and streamed to the user for approval — rather than flatly
    refused. Without one, it falls back to `confirmation_refusal`, so the gate can
    never fail open.
    """
    if park is None:
        return confirmation_refusal(registry, call)
    parked = await park(call)
    return None if parked is None else parked.result


def build_dispatch(
    registry: ToolRegistry,
    park: "ParkFn | None",
    *,
    routine_policy: "BuildExecutionPolicy | None" = None,
    routine_outcome: Callable[[ToolCall, ToolResult], Awaitable[ToolResult]] | None = None,
    routine_start: Callable[[ToolCall], Awaitable[None]] | None = None,
) -> "DispatchFn":
    """The gated dispatcher handed to a runner.

    Gate-then-invoke is fused into ONE callable so there is no ungated path to
    hand out. A runner cannot forget the gate, cannot be reviewed as having
    forgotten it, and cannot reach `registry.invoke` at all — it never receives
    the registry.

    SYS-02: the fused closure is wrapped in `exec.run_tool`, the ONE observable
    path — every dispatch, from every runner, gets the same duration/outcome
    logging and Sentry capture. This function is the only production holder of
    `registry.invoke` besides the confirmation flow's post-approval path
    (ratchet-tested in test_sol_runtime.py).
    """

    async def gated(call: ToolCall) -> ToolResult:
        call = call.model_copy(update={"args": deepcopy(call.args)})
        automatic = await routine_policy.prepare(call) if routine_policy is not None else False
        if isinstance(automatic, ToolResult):
            return automatic
        if automatic is True:
            assert routine_policy is not None
            try:
                if routine_start is not None:
                    await routine_start(call)
            except Exception:
                return routine_policy.finish(
                    ToolResult.failure(
                        call.call_id,
                        ToolError(
                            code=ToolErrorCode.UNAVAILABLE,
                            message="Build bookkeeping failed. Nothing was executed.",
                            retryable=False,
                        ),
                    )
                )
            routine_policy.execution_started(call)
            result = routine_policy.finish(await registry.invoke(call))
            if routine_outcome is not None:
                try:
                    result = await routine_outcome(call, result)
                except Exception:
                    logger.warning("Build post-action hook failed for %s", call.tool)
            return result
        refusal = await gate_tool_call(registry, park, call)
        if refusal is not None:
            # "Why did this tool not run?" must be answerable from logs. exec's
            # `tool call done` line cannot say: the gate lives inside this
            # closure by design, and its outcome code (`unauthorized`) is one a
            # tool could return on its own — so the two are indistinguishable
            # downstream. Logged HERE, at the decision, identifiers only (§7).
            logger.info(
                "tool call gated tool=%.128r call_id=%.128r parked=%s",
                call.tool,
                call.call_id,
                park is not None,
            )
            return refusal
        return await registry.invoke(call)

    async def dispatch(call: ToolCall) -> ToolResult:
        return await run_tool(gated, call)

    return dispatch


class AgentRunner:
    """The seam SOL-01/02 implements. Structural: any object with a matching `run`
    satisfies it (see `ScaffoldRunner`). `run` returns an async stream of events."""

    def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:  # pragma: no cover
        raise NotImplementedError


def _stream_chunks(text: str) -> list[str]:
    """Split a reply into incremental deltas so the client renders it progressively —
    the scaffold's stand-in for token streaming."""
    words = text.split(" ")
    return [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]


class ScaffoldRunner:
    """A deterministic, model-free `AgentRunner`. Proves the loop end to end without a
    provider call: list tools → invoke the reference tool → pull graph context →
    compose a mode-aware reply → stream it. Swapped for the real reasoning later."""

    async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
        tools = list(ctx.tools)
        # W0-03 gateway: derive the complexity tier with NO model call (wired, not used
        # to pick a real model here — that lands in MO-01).
        complexity = derive_complexity(ctx.interaction_context)

        results: list[ToolResult] = []
        for call in plan_tool_calls(ctx.prompt)[: turn_limits(ctx.action_mode).tool_calls]:
            yield AgentEvent.tool_call(call)
            result = await ctx.dispatch(call)  # gates, then invokes — §7
            results.append(result)
            yield AgentEvent.tool_result(result)

        graph_note = await self._graph_note(ctx)
        reply = self._compose(
            ctx,
            tools=[t.name for t in tools],
            complexity=str(complexity),
            results=results,
            graph_note=graph_note,
        )
        for chunk in _stream_chunks(reply):
            yield AgentEvent.token(chunk)
        yield AgentEvent.message(reply)

    async def _graph_note(self, ctx: AgentRunContext) -> str:
        """Consume the W0-07 systems seam: pull a bounded neighborhood around any
        referenced entity. Returns a short DATA summary (counts only — never raw
        ingested strings framed as instructions)."""
        anchors = parse_entity_ids(ctx.prompt)
        if not anchors:
            return ""
        context = await ctx.systems.get_graph_context(
            ctx.project_id, GraphScope(anchor_entity_ids=anchors, degree=_CONTEXT_DEGREE)
        )
        return f"{len(context.entities)} nearby entities and {len(context.edges)} relations"

    def _compose(
        self,
        ctx: AgentRunContext,
        *,
        tools: list[str],
        complexity: str,
        results: list[ToolResult],
        graph_note: str,
    ) -> str:
        """Build the assistant reply, mode-aware (ADR-016). Tool outputs and graph
        summaries are rendered as plain DATA, never executed as instructions (§7)."""
        tool_summary = self._summarize_results(results)
        if ctx.sol_mode is SolMode.EXPERT:
            parts = [tool_summary or "No tools were needed."]
            if graph_note:
                parts.append(f"Graph: {graph_note}.")
            return " ".join(parts)
        # GUIDE mode: explain what SOL is doing and what it can reach.
        parts = [
            "I'm SOL, wiring your robot's tools together.",
            f"This is a {complexity}-complexity question.",
            f"I can call these tools: {', '.join(tools)}.",
        ]
        if tool_summary:
            parts.append(tool_summary)
        if graph_note:
            parts.append(f"Around that entity I can see {graph_note}.")
        return " ".join(parts)

    @staticmethod
    def _summarize_results(results: list[ToolResult]) -> str:
        """Reflect tool outcomes as data — the entity name on success, the error code
        on failure (an author-safe string, never a traceback)."""
        notes = []
        for result in results:
            if result.ok and result.value is not None:
                name = result.value.get("name", "an entity")
                notes.append(f"I looked up {name}.")
            elif result.error is not None:
                notes.append(f"A tool call failed ({result.error.code.value}).")
        return " ".join(notes)


#: §7 SPEND bound, complementary to the transport's MAX_TOOL_CALLS EVENT bound.
#: The transport's guard stops the event stream but cannot stop the runner from
#: making another PAID model call, and cannot see a model that answers with zero
#: tool calls forever. One guard per concern — the runner does not re-count tool
#: calls, and the transport does not count rounds.
MAX_MODEL_ROUNDS: Final = GUIDE_MODEL_ROUNDS
#: A tool loop needs more headroom than the gateway's 4096 text default — and
#: Responses-style providers count REASONING tokens against max_output_tokens
#: (OpenAI recommends headroom), so 8192 could truncate a reasoned tool round.
SOL_MAX_TOKENS: Final = 16384

_ROUND_LIMIT = (
    "I stopped after several rounds of tool calls without reaching an answer. "
    "Try narrowing the question."
)


def _round_conversation(
    system: str, turns: tuple[Turn, ...], tools: tuple[Any, ...], synthesis: bool
) -> ToolConversation:
    # SOLUSDEV-321 P0-T4: the round's final user turn (live message, then latest
    # results) is a cache breakpoint the next round reads back. The last round keeps
    # `system` and `tools` byte-identical — dropping the tools changed the request from
    # its first byte — and withholds them through `tool_choice` instead.
    *earlier, last = turns
    messages = (*earlier, last.model_copy(update={"cache_breakpoint": True}))
    if synthesis:
        return ToolConversation(
            system=system,
            messages=(*messages, prompt.synthesis_turn()),
            tools=tools,
            tool_choice="none",
        )
    return ToolConversation(system=system, messages=messages, tools=tools)


def _limit_outcome(use: Any, tools: tuple[ToolDescriptor, ...]) -> ToolOutcome:
    call = ToolCall(tool=prompt.resolve_tool_name(use.name, tools), args=use.args, call_id=use.id)
    result = ToolResult.failure(
        call.call_id,
        ToolError(
            code=ToolErrorCode.UNAVAILABLE,
            message="This turn reached its tool limit. This request was not executed.",
            retryable=False,
        ),
    )
    return prompt.contain_result(call, result)


def _terminal_reply(
    completion: Any, synthesis: bool, context: Context, *, waiting: bool = False
) -> AgentEvent | None:
    if synthesis and completion.tool_calls:
        return AgentEvent.message(
            "The final summary was not completed. I stopped without executing additional "
            "tools; earlier results and pending approvals remain unchanged."
        )
    if not completion.tool_calls:
        prose, cited = citations.reply_parts(completion.text, context, waiting=waiting)
        return AgentEvent.message(prose, citations=cited)
    return None


async def _close_unfinished(stream: gateway.CompletionStream) -> None:
    """Close a model stream the round did not read to its end (the transport broke out)."""
    if stream.completion is None:
        await stream.aclose()


async def _round_events(
    stream: gateway.CompletionStream, hit: BudgetHit | None, ctx: AgentRunContext
) -> AsyncIterator[AgentEvent]:
    """One round's events: the `budget_reached` frame when a ceiling made this the closing round
    (announced before the round is asked, and logged with ids and counts only), then its tokens
    as they arrive. P1-T3. Its `<reasoning>` block arrives as one `reasoning` frame, never as
    tokens (P7)."""
    if hit is not None:
        logger.info(
            "turn budget reached limit=%s used=%d cap=%d turn_id=%s user_id=%s project_id=%s",
            hit.limit,
            hit.used,
            hit.cap,
            ctx.turn_id,
            ctx.user_id,
            ctx.project_id,
        )
        yield AgentEvent.budget_reached(hit.limit, hit.used, hit.cap)
    async for event in reasoning_frame.reasoned_tokens(stream):
        yield event


def _preferences_tokens(preferences: "Mapping[str, str] | None", estimator: Any) -> int:
    """What the system prompt spends on the root `~/.solus` preferences — the
    preferences layer carries no text of its own, only this count (S5).
    ponytail: counted off the same mapping prompt.system_prompt JSON-encodes;
    the answer-styling `custom_instruction` is a different layer's business."""
    if not preferences:
        return 0
    return estimate_tokens(json.dumps(dict(preferences), default=str), config=estimator)


def _conversation_tokens(history: "tuple[TurnView, ...]", live: str, estimator: Any) -> int:
    """The surrounding turns plus the live message — the conversation layer's
    text lives in the runner's Turns, so the layer reports only this count."""
    return estimate_tokens("\n".join((*(turn.content for turn in history), live)), config=estimator)


async def _opening_events(
    answer: DeterministicAnswer | None, scope: "turn_scope.TurnScope", step: ResearchStep
) -> AsyncIterator[AgentEvent]:
    """The frames a turn streams before any prompt: the first tier's answer when it gave one
    (P1-T2), else the turn's web research (P1-T5) — its frames, or none when the gate did not fire.
    One generator so `run` keeps a single branch for both."""
    if answer is not None:
        for event in first_tier_events(answer, scope):
            yield event
        return
    async for event in step.events():
        yield event


class LlmRunner:
    """The real `AgentRunner`: a model chooses the tools, Solus code gates them.

    What this does NOT own, deliberately: the tool set and project scope (fixed
    before it runs), the destructive gate (fused into `ctx.dispatch`), the
    tool-call event bound and turn timeout (the transport's), and metering (the
    gateway's, per call). It owns the conversation loop and nothing else.
    """

    def __init__(self, *, adapters: "Mapping[str, Any] | None" = None) -> None:
        #: The test seam the gateway already exposes, so tests exercise the REAL
        #: gateway — gates, cost hook, Completion assembly — and fake only the
        #: network.
        self._adapters = adapters

    async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
        if ctx.user_id is None or ctx.sessionmaker is None or ctx.secret_store is None:
            # Fail closed and LOUDLY. A text-only fallback would quietly become
            # an unmetered model path; the transport masks this to the user as a
            # generic error event, and it is obvious in dev.
            raise RuntimeError("LlmRunner requires request identity; refusing an unmetered call")

        # SOLUSDEV-321 P0-T4: ONE fence token, the conversation's own, for every fenced
        # surface, so system, tools and the prefix turn are byte-stable across turns.
        nonce = (
            prompt.conversation_nonce(ctx.conversation_id)
            if ctx.conversation_id is not None
            else prompt.new_nonce()
        )
        system = prompt.system_prompt(
            ctx.sol_mode,
            ctx.custom_instruction,
            ctx.engineering_preferences,
            with_screenshot=ctx.screenshot is not None,
            action_mode=ctx.action_mode,
            nonce=nonce,
            expertise=ctx.expertise,
            front_app=ctx.front_app,
        )
        # P1-T5: the model is offered every tool but the ones only the server drives (research).
        # P7: a GUI tool's knowledge note is read for the release on the asker's own machine.
        offered = await placed_tools(model_visible(ctx.tools), ctx.project_card, ctx.sessionmaker)
        tools = prompt.tool_specs(offered, nonce=nonce)
        # SOL-02: plan what to pull (deterministic, no model call), assemble
        # the W0-07 context, and hand it to the model as fenced data blocks.
        orchestration = gateway.default_orchestration_config()
        # P1-T3: what every round re-sends whatever the turns hold — the system prompt and the tool
        # specs — measured once, from the very `system` and `tools` the rounds send. It sizes this
        # turn's input cap (`turn_limits(…, fixed_tokens=)`) and is part of each round's measure.
        fixed_tokens = estimate_tokens(
            system, config=orchestration.type_estimator
        ) + estimate_tokens(prompt.tools_text(tools), config=orchestration.type_estimator)
        complexity = self._complexity_override(ctx)
        resolved = await resolve_anchor_inputs(
            ctx.sessionmaker, ctx.project_id, focus=ctx.focus, finding_id=ctx.finding_id
        )
        # SOLUSDEV-321 P0-T7: a turn that names a finding (its id, or the subjects that become
        # its `finding_subject` anchors) runs HARD, explicitly, above "think harder" too.
        complexity = round_one_complexity(
            complexity, about_finding=ctx.finding_id is not None or bool(resolved.finding_subjects)
        )
        # The tier the gateway will route this turn at — a finding's or "think harder"'s
        # explicit one, else the estimator's on the live message — so the context budget
        # matches the model that reads it.
        tier = complexity or estimate_complexity(ctx.prompt, config=orchestration.estimator)
        # P1-T3: this turn's ceilings for that tier and what it has spent against them. Counting
        # starts with the planner's tie-break below, so a first-tier answer (no model call at
        # all) leaves every counter at zero.
        turn_budget = TurnBudget(turn_limits(ctx.action_mode, tier, fixed_tokens=fixed_tokens))
        # P1-T1: the scope planner, before any prompt — anchors with their reasons, the names
        # the message resolves, ONE bounded graph pull, the turn's hints. build_context packs
        # its graph and pulls none of its own.
        scope = await turn_scope.plan_scope(
            turn_scope.ScopeInputs(
                message=ctx.prompt,
                tier=tier,
                mentions=ctx.mentions,
                pins=ctx.pins,
                focus=ctx.focus,
                robot_id=ctx.robot_id,
                finding_subjects=resolved.finding_subjects,
                history_entity_ids=ctx.history_entity_ids,
                not_visible=resolved.not_visible,
            ),
            search=turn_scope.index_search(ctx.sessionmaker, ctx.project_id),
            load=lambda graph_scope, budget: ctx.systems.get_graph_context(
                ctx.project_id, graph_scope, budget
            ),
            disambiguate=(
                self._disambiguator(
                    ctx, ctx.sessionmaker, ctx.secret_store, nonce, turn_budget.note_model_call
                )
                if tier is Complexity.HARD
                else None
            ),
            config=orchestration,
        )
        # P1-T2: the first tier — a lookup the scope's facts answer is answered here, with no
        # model call and no prompt; anything else goes on to the model with the same scope. A
        # `/web <q>` turn skips it: the person asked for the web, not for the graph (P1-T5).
        answer = (
            await answer_first_tier(ctx.prompt, scope, ctx.facts, mode=ctx.sol_mode)
            if ctx.facts and ctx.research_query is None
            else None
        )
        # P1-T5: a turn the first tier declined may research the web, once, before anything is
        # packed — the step runs the gate, the cache, one call through `ctx.dispatch`, and the
        # ledger; its digest rides into the context below.
        step = ResearchStep(
            ctx,
            missing=scope.missing,
            budget=turn_budget,
            limits=orchestration.limits,
            credits_per_call=orchestration.cost.web_call_credits,
        )
        async for event in _opening_events(answer, scope, step):
            yield event
        if answer is not None:
            return
        estimator = orchestration.type_estimator
        context = await build_context(
            ctx.systems,
            ctx.prompt,
            project_id=ctx.project_id,
            scope=scope.scope,
            graph=scope.graph,
            window=scope.window,
            budget=scope.budget,
            research=step.digest,
            # CORPUS C2 (ADR-036): mode only orders corpus ties — Guide reads
            # fundamentals first, Expert reference first. Never a filter.
            mode=ctx.sol_mode,
            # S5 (sol-context-layers.md): the request's sessionmaker loads THIS
            # project's live `.solus` entries into the project layer — without it
            # the layer reported ".solus not loaded" on every real turn — and
            # `preferences_tokens` is what the system prompt above already spent
            # on the person's root preferences, so the layer reports it honestly
            # instead of claiming "no preferences" while carrying them.
            sessionmaker=ctx.sessionmaker,
            preferences_tokens=_preferences_tokens(ctx.engineering_preferences, estimator),
            practice_question=scope.practice_question,
        )
        # ponytail: an open non-info finding on a part in scope surfaces only in the findings
        # read inside build_context, so it turns round 1 HARD on a context already packed at the
        # planned tier; re-packing would cost a second build_context. The scope planner leaves
        # that read where it is (P1-T1 R7); moving it before packing would lift this ceiling.
        complexity = round_one_complexity(complexity, about_finding=context.finding_in_scope)
        context = await self._with_screen_read(
            ctx, context, nonce, estimator, turn_budget.note_model_call
        )
        context = (
            context.with_conversation(
                tokens=_conversation_tokens(ctx.history, ctx.prompt, estimator)
            )
            .with_anchors(scope.anchors, scope.dropped)
            .with_card(
                await project_card_section(ctx.sessionmaker, ctx.project_id, ctx.project_card)
            )
        )
        sections = [
            {"kind": s.kind, "citation": s.citation, "tokens": s.tokens} for s in context.sections
        ]
        manifest = context.manifest()
        # SOLUSDEV-233: declare the turn's context up front so clients can show
        # what SOL is grounded in. Manifest only — no section text.
        yield AgentEvent.context_used(
            sections=sections,
            truncated=context.truncated,
            dropped=len(context.dropped),
            layers=manifest["layers"],
            anchors=manifest["anchors"],
            anchors_dropped=manifest["anchors_dropped"],
        )
        turns = self._opening_turns(ctx, nonce, context)
        completion = None
        # P0-T7: round 1 asks for CODE only for a turn anchored on code (or worded as code) whose
        # input leaves 20 % of that role's window spare — an explicit type refuses on overflow.
        route_type: RouteType | None = round_one_route_type(
            scope.type_hint,
            query=prompt.flatten(turns),
            tier=complexity or tier,
            config=orchestration,
        )

        limits = turn_budget.limits
        # P1-T5: what the MODEL proposes runs through the gated dispatcher minus the tools only the
        # server drives — a call it makes to one is an unknown tool, never a web query.
        from solus_api.agent.preferences import code_style_of  # P6, R134
        from solus_api.agent.turn_context import with_perception, with_turn  # R75/R83/R125

        # P5 (R125): beside the turn's id, its perception — the budget a tool's model call counts
        # against, and whether the scope planner turned renders off for this turn — and (P6) the
        # person's code style, for a tool that writes code.
        model_dispatch = with_perception(
            with_turn(withhold_server_driven(ctx.dispatch), ctx.turn_id, ctx.project_id),
            turn_budget,
            connectivity=scope.exclude_renders,
            counting=scope.counting,
            code_style=code_style_of(ctx.engineering_preferences),
        )
        for _ in range(limits.model_rounds):
            # P1-T3: this round and its model call counted (a call counts against its own cap),
            # its whole request measured, then the first ceiling the turn has reached. A hit makes
            # this the closing round (no tools) and is announced before it runs; the last round
            # always hits `model_rounds`.
            query = prompt.flatten(turns)
            turn_budget.note_model_round()
            turn_budget.note_model_call()
            turn_budget.note_input_tokens(fixed_tokens + estimate_tokens(query, config=estimator))
            hit = turn_budget.check()
            synthesis = hit is not None
            completion = None
            async with ctx.sessionmaker() as session:
                stream = gateway.stream(
                    query,
                    secret_store=ctx.secret_store,
                    # The context derives the route TYPE unless round 1 asked for CODE;
                    # the tier comes from the estimator on the person's live message (S1),
                    # never from the context's HARD default — unless "think harder" or a
                    # finding made it explicit.
                    # From round 2 on, BOTH axes are pinned to round 1's choice: the
                    # growing conversation must not escalate the model mid-turn,
                    # because `provider_items` (encrypted reasoning) are bound to
                    # the model that produced them and would 400 on another.
                    context=ctx.interaction_context,
                    estimate_from=ctx.prompt,
                    complexity=complexity,
                    type=route_type,
                    conversation=_round_conversation(system, turns, tools, synthesis),
                    user_id=ctx.user_id,
                    session=session,
                    redis=ctx.redis,
                    enqueue=ctx.enqueue,
                    adapters=self._adapters,
                    max_tokens=SOL_MAX_TOKENS,
                    extension_id=ctx.extension_id,
                    purpose="answer",
                    turn_id=ctx.turn_id,
                    project_id=ctx.project_id,
                )
                try:
                    async for event in _round_events(stream, hit, ctx):
                        yield event
                finally:
                    # The transport breaks out of `async for event in runner.run()`
                    # when it trips its own guard, which throws GeneratorExit here.
                    # Without this the provider connection is abandoned open.
                    await _close_unfinished(stream)
                completion = stream.completion

            if completion is None:
                break
            complexity, route_type = completion.model.complexity, completion.model.route_type
            terminal = _terminal_reply(
                completion,
                synthesis,
                context,
                # P7 fix 1 (M4): a reply that was only a block closes on a card this turn parked.
                waiting=citations.card_waiting(
                    turns, offered, ctx.executed_build_calls, ctx.action_mode
                ),
            )
            if terminal is not None:
                yield terminal
                return

            turns = (
                *turns,
                Turn(
                    role="assistant",
                    text=completion.text,
                    tool_uses=completion.tool_calls,
                    # Opaque replay items ride to the next round only; the
                    # transcript never sees them (_persist_turn builds from events).
                    provider_items=completion.provider_items,
                ),
            )
            outcomes: list[ToolOutcome] = []
            admitted = completion.tool_calls[: limits.tool_calls - turn_budget.tool_calls]
            turn_budget.note_tool_calls(len(admitted))
            outcomes.extend(
                _limit_outcome(use, ctx.tools) for use in completion.tool_calls[len(admitted) :]
            )
            for use in admitted:
                # The provider's own tool_use id becomes the call id, so results
                # correlate exactly with no mapping table anywhere.
                # The model answers with the name it was OFFERED (provider
                # charset); dispatch needs the real, dotted tool name back. Both the name and
                # the descriptor are looked up among the tools it was offered: a call to one it
                # was not (the server-driven `research`) is refused as unknown, and is filed
                # and recorded as a call that never ran.
                call = ToolCall(
                    tool=prompt.resolve_tool_name(use.name, offered),
                    args=use.args,
                    call_id=use.id,
                )
                yield AgentEvent.tool_call(call)
                result = await model_dispatch(call)  # gates, then invokes
                descriptor = next((d for d in offered if d.name == call.tool), None)
                # Mutation flags still protect Guide; actual Build dispatch
                # is recorded separately. A parked/refused write must never
                # be filed as though it ran. Manual failures remain in the
                # confirmation decision path.
                executed = call.call_id in ctx.executed_build_calls or (
                    descriptor is not None and not descriptor.requires_confirmation
                )
                # S5 Error logging: a failed local-machine action is filed into the
                # project's .solus errors section BEFORE the client sees the result,
                # so the Workspace already has the note. Never raises.
                await file_tool_error(
                    ctx.sessionmaker,
                    project_id=ctx.project_id,
                    user_id=ctx.user_id,
                    call=call,
                    result=result,
                    descriptor=descriptor,
                    executed=executed,
                )
                # SOLUSDEV-320 P5-T7: and a clean, executed flash is one history row.
                await record_tool_history(
                    ctx.sessionmaker,
                    project_id=ctx.project_id,
                    user_id=ctx.user_id,
                    call=call,
                    result=result,
                    executed=executed,
                )
                # EVERY outcome goes back to the model, including a parked one.
                # A failure it can correct (NOT_FOUND for a hallucinated tool,
                # INVALID_ARGS, TIMEOUT) it corrects; a park it is told to leave
                # alone and work around. See the note below the loop.
                # §10.1: an auto-run command streams its own row for the desktop
                # and reaches the model as its outcome clause, in this same turn.
                auto = call.tool == AUTO_COMMAND_TOOL and call.call_id in ctx.executed_build_calls
                yield AgentEvent.tool_result(
                    result, command=stream_view(result, call.args.get("argv")) if auto else None
                )
                artifact = AgentEvent.artifact_from_result(call.tool, result)
                if artifact is not None:
                    yield artifact  # a reference the renderer can view/file; never bytes
                outcomes.append(
                    prompt.contain_result(
                        call,
                        model_result(result) if auto else result,
                        cap=descriptor.result_cap if descriptor else None,
                    )
                )

            # A parked call USED to end the turn here. It no longer does.
            #
            # The old `return` was defensible — feeding "pending approval" back
            # naively would just have the model propose the same action again —
            # but it cost more than it bought. It discarded the round's other
            # results even though they had already executed, it capped a design
            # task at one change per turn, and it replaced the model's own
            # closing words with a canned string.
            #
            # Three things replace it, and none of them is the loop:
            #   * the parked result says, in words, that a PERSON now has it,
            #     that it is not a failure, and not to propose it again
            #     (`confirmations.request_confirmation`);
            #   * the turn's `park` hook dedupes by concrete action, so a model
            #     that re-proposes anyway gets the same confirmation back rather
            #     than a second card and a second live preview (`routers/sol.py`);
            #   * `MAX_MODEL_ROUNDS` still bounds the turn, exactly as it always
            #     bounded every ungated one.
            #
            # What the gate itself does is untouched: the call is still parked,
            # still never dispatched, still approved on a separate endpoint.
            #
            # ALL of a round's results go back in ONE user turn: splitting them
            # teaches the model to stop making parallel calls.
            turns = (*turns, Turn(role="user", tool_results=tuple(outcomes)))

        final = (completion.text if completion else "") or _ROUND_LIMIT
        prose, cited = citations.reply_parts(final, context)
        yield AgentEvent.message(prose, citations=cited)

    async def _with_screen_read(
        self,
        ctx: AgentRunContext,
        context: Context,
        nonce: str,
        estimator: Any,
        note_call: Callable[[], None],
    ) -> Context:
        """S3: the VISUAL_LOG extractor pass — THE vision call of the turn — when the person
        attached a screenshot. Degrades to an honest string on any failure; never fails the
        turn. The read goes into the screen LAYER rather than after the context: it reached
        the model either way, but it was absent from the manifest and out of precedence order.
        `note_call` counts the call against the turn's budget (P1-T3) where the runner makes it; it
        runs before any dispatch binds the turn, so it gets the turn's id and project (R148)."""
        if (
            ctx.screenshot is None
            or ctx.sessionmaker is None
            or ctx.secret_store is None
            or ctx.user_id is None
        ):
            return context
        note_call()
        async with ctx.sessionmaker() as session:
            screen_read = await screen.read_screen(
                ctx.screenshot,
                secret_store=ctx.secret_store,
                user_id=ctx.user_id,
                session=session,
                redis=ctx.redis,
                enqueue=ctx.enqueue,
                adapters=self._adapters,
                extension_id=ctx.extension_id,
                turn_id=ctx.turn_id,
                project_id=ctx.project_id,
            )
        return context.with_screen(
            screen.screen_section(nonce, ctx.screenshot, screen_read),
            estimate_tokens(screen_read, config=estimator),
        )

    @staticmethod
    def _complexity_override(ctx: AgentRunContext) -> Complexity | None:
        """None (the gateway's estimator decides) unless "think harder": the
        estimator's tier for the live message, one up, made explicit."""
        if not ctx.think_harder:
            return None
        estimator = gateway.default_orchestration_config().estimator
        tier = bump_complexity(estimate_complexity(ctx.prompt, config=estimator))
        logger.info(
            "think harder: tier=%s user_id=%s project_id=%s",
            tier.value,
            ctx.user_id,
            ctx.project_id,
        )
        return tier

    def _disambiguator(
        self,
        ctx: AgentRunContext,
        sessionmaker: "async_sessionmaker[AsyncSession]",
        secret_store: "SecretStore",
        nonce: str,
        note_call: Callable[[], None],
    ) -> "turn_scope.DisambiguateFn":
        """P1-T1: the scope planner's one tie-break on a HARD turn — TRIVIAL, GENERAL, metered
        to the requester. The prompt fences every string (turn_scope builds it) and the reply
        counts only as one of the ids it offered. `note_call` counts the call against the
        turn's budget (P1-T3)."""

        async def choose(
            message: str, candidates: "Sequence[turn_scope.Candidate]"
        ) -> uuid.UUID | None:
            async with sessionmaker() as session:
                note_call()
                completion = await gateway.complete(
                    turn_scope.disambiguation_prompt(message, candidates, nonce=nonce),
                    secret_store=secret_store,
                    complexity=Complexity.TRIVIAL,
                    type=RouteType.GENERAL,
                    adapters=self._adapters,
                    user_id=ctx.user_id,
                    session=session,
                    redis=ctx.redis,
                    enqueue=ctx.enqueue,
                    max_tokens=turn_scope.PLANNER_MAX_TOKENS,
                    extension_id=ctx.extension_id,
                    purpose="planner",
                    turn_id=ctx.turn_id,
                    project_id=ctx.project_id,
                )
            return turn_scope.offered_choice(completion.text, candidates)

        return choose

    @staticmethod
    def _opening_turns(ctx: AgentRunContext, nonce: str, context: "Context") -> tuple[Turn, ...]:
        """The stable prefix, the history, then the live turn — every ingested
        string fenced as DATA (context sections fence themselves). SOLUSDEV-321
        P0-T4: the prefix turn (`Context.fenced_prefix`) is stable while the turn's
        anchors are, so it is a cache breakpoint; everything else that varies with
        the message follows the history (`Context.fenced_suffix`, then the message,
        the screenshot's pixels riding along as `images`)."""
        turns = [Turn(role="user", text=context.fenced_prefix(nonce), cache_breakpoint=True)]
        if ctx.history:
            turns.append(
                Turn(
                    role="user",
                    text=prompt.data_block(
                        nonce,
                        "history",
                        [{"role": t.role, "content": t.content} for t in ctx.history],
                    ),
                )
            )
            turns.append(Turn(role="assistant", text="Understood — that is the prior context."))
        live = (
            prompt.extension_request(nonce, ctx.extension_slug, ctx.prompt)
            if ctx.extension_slug
            else prompt.data_block(nonce, "user_message", ctx.prompt)
        )
        images = (ctx.screenshot.image,) if ctx.screenshot is not None else ()
        # SOLUSDEV-319 slice 4: the front app's fenced block, after the live layers and
        # before the message — it varies per summon, so it stays out of the cached prefix.
        front = (front_app_block(nonce, ctx.front_app),) if ctx.front_app is not None else ()
        text = "\n".join((context.fenced_suffix(nonce), *front, live))
        turns.append(Turn(role="user", text=text, images=images))
        return tuple(turns)


def _register_presence(registry: ToolRegistry, service: Any | None) -> None:
    if service is not None:
        from solus_api.agent.tools.firmware_presence import make_presence_tool

        registry.register(make_presence_tool(service))


def _register_companion_deployment(registry: ToolRegistry, service: Any | None) -> None:
    if service is not None:
        from solus_api.agent.tools.companion_deployment import make_companion_deployment_tool

        registry.register(make_companion_deployment_tool(service))


def _register_scene(
    registry: ToolRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    scene_enqueue: Any | None,
) -> None:
    if user_id is not None and scene_enqueue is not None:
        from solus_api.agent.tools.bench_scene import build_bench_scene_tools

        for tool in build_bench_scene_tools(session_factory, project_id, user_id, scene_enqueue):
            registry.register(tool)
