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
    from solus_api.agent.tools.shapes import ToolCall as _ToolCallHint
    from solus_api.bridge.registry import BridgeSessionRegistry
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.widgets.capability import WidgetCapability

    #: Parks a gated call for approval; None when the call is not gated.
    ParkFn = Callable[[_ToolCallHint], Awaitable[ParkedCall | None]]
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent import prompt, reason
from solus_api.agent.context import Context, build_context
from solus_api.agent.interfaces import GraphScope, SolSystems
from solus_api.agent.modes import ActionMode
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
from solus_api.models import SolMode
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import InteractionContext
from solus_api.orchestration.providers import ToolConversation, ToolOutcome, Turn
from solus_api.orchestration.router import derive_complexity

# §7 loop/recursion guard: an upper bound on tool calls per turn so a runaway loop
# can never fan out unboundedly. The scaffold proposes ≤1; the guard protects the seam
# for the real runner that swaps in later.
MAX_TOOL_CALLS = 8
# Graph traversal depth for the scaffold's W0-07 context pull (the 2-degree perf lever).
_CONTEXT_DEGREE = 1

# The shared UUID parser lives in reason.py (one instance, no drift).
_UUID_RE = reason.UUID_RE

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
) -> ToolRegistry:
    """Assemble the tool set SOL may invoke for ONE request, each tool bound to the
    request's project scope by Solus code. v1 exposes the W0-04 reference tool; new
    tools are registered here, never proposed by a model.

    When a bridge session registry + full scope are supplied (SOLUSDEV-154), one
    BridgeTool per entry of the LIVE session's cloud-validated inventory is added —
    the turn's tool set reflects the requesting user's connected companion at turn
    start, fixed here before any model or ingested content is seen. The bridge
    package relays JSON only, so the reasoning import graph stays MCP-free."""
    registry = ToolRegistry()
    registry.register(build_get_entity_tool(session_factory, project_id))
    if systems is not None:
        # SYS-03: the four builtin reads (query_graph / get_telemetry /
        # retrieve_errors / run_checkers) as thin closures over the real
        # SolSystems, sharing build_context's data paths. Function-local import
        # (house pattern) so the reasoning import graph grows the checker
        # dependency only when wired.
        from solus_api.agent.tools.builtin import build_builtin_tools

        for tool in build_builtin_tools(systems, project_id):
            registry.register(tool)
    if connectors is not None:
        # SOLUS-ONS-A1: Onshape operations as in-process tools. Function-local
        # import for the same reason the bridge one is — the reasoning import
        # graph must not grow a connector dependency. Each tool is bound to THIS
        # project and resolves the team's stored OAuth credentials per call.
        # Registered ALONGSIDE the SOLX-04 tools below, not instead of them: the
        # two sets are disjoint (`onshape.*` vs `solus.*`) and answer different
        # questions — connecting a source versus operating one.
        from solus_api.agent.tools.onshape_tools import build_onshape_tools

        for tool in build_onshape_tools(
            session_factory, project_id, secret_store=secret_store, connectors=connectors
        ):
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
    if bridge is not None and user_id is not None and team_id is not None:
        _register_bridge_tools(
            registry,
            session_factory,
            project_id,
            bridge=bridge,
            user_id=user_id,
            team_id=team_id,
            bridge_call_cap_bytes=bridge_call_cap_bytes,
            secret_store=secret_store,
        )
    if bundle_capabilities:
        _register_bundle_tools(
            registry, session_factory, project_id, user_id=user_id, bundles=bundle_capabilities
        )
    return registry


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
) -> None:
    """One BridgeTool per entry of the LIVE session's cloud-validated inventory.

    Function-local imports like BridgeTool itself: the reasoning import graph
    stays MCP-ignorant; the catalog is consulted only when a bridge is wired."""
    from solus_api.agent.tools.mcp_servers import (
        MCP_SERVER_CATALOG,
        build_license_preflight,
    )
    from solus_api.agent.tools.mcp_tool import LicenseTier
    from solus_api.bridge.tool import BridgeTool

    session = bridge.get(user_id, team_id, project_id)
    if session is None:
        return
    for spec in session.inventory:
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
        registry.register(
            BridgeTool(
                descriptor=spec.descriptor,
                sessions=bridge,
                user_id=user_id,
                team_id=team_id,
                project_id=project_id,
                call_cap_bytes=bridge_call_cap_bytes,
                preflight=preflight,
            )
        )


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
    #: SOLUSDEV-233: the user's saved preference note. Reaches the prompt only
    #: through prompt.system_prompt's fenced data block, never as raw text.
    custom_instruction: str | None = None
    history: tuple[TurnView, ...] = ()
    #: SOLUSDEV-168: graph entities the user pointed at explicitly (the
    #: composer's `@`). They become the neighbourhood's anchors, so SOL is
    #: grounded on the node the user meant rather than on whatever similarity
    #: search surfaced. Untrusted ids: `load_neighborhood` is project-scoped, so
    #: one from another team yields nothing rather than leaking.
    mentions: tuple[uuid.UUID, ...] = ()
    interaction_context: InteractionContext = InteractionContext.SOL_OPEN_QUESTION
    #: Model-call identity (ADR-018). A runner that makes a PAID call MUST refuse
    #: without these: `gateway.complete` defaults them to None and then silently
    #: skips every rate limit and every debit, so inheriting that default would
    #: be an unmetered, unlimited model path. Optional in the signature only so
    #: the model-free ScaffoldRunner and its tests construct unchanged.
    user_id: uuid.UUID | None = None
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


#: A proposed call → its result. The gate is inside; see `build_dispatch`.
DispatchFn = Callable[[ToolCall], Awaitable[ToolResult]]


def confirmation_refusal(registry: ToolRegistry, call: ToolCall) -> ToolResult | None:
    """The CENTRAL destructive-action gate (CLAUDE.md §7, SEC-H1). A tool whose
    descriptor carries `requires_confirmation` may NOT be dispatched without the
    user explicitly approving the concrete action.

    This is the FALLBACK: a flat refusal, used when no confirmation flow is
    wired. When a `park` IS supplied to `build_dispatch` (SOLUS-ONS-A5) the call
    is parked for approval instead — see `gate_tool_call`. Either way a
    destructive tool is never dispatched from inside a turn.

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


def build_dispatch(registry: ToolRegistry, park: "ParkFn | None") -> "DispatchFn":
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
        for call in plan_tool_calls(ctx.prompt)[:MAX_TOOL_CALLS]:
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
MAX_MODEL_ROUNDS: Final = 5
#: A tool loop needs more headroom than the gateway's 4096 text default.
SOL_MAX_TOKENS: Final = 8192

_ROUND_LIMIT = (
    "I stopped after several rounds of tool calls without reaching an answer. "
    "Try narrowing the question."
)


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

        system = prompt.system_prompt(ctx.sol_mode, ctx.custom_instruction)
        tools = prompt.tool_specs(ctx.tools)
        nonce = prompt.new_nonce()
        # SOL-02: plan what to pull (deterministic, no model call), assemble
        # the W0-07 context, and hand it to the model as fenced data blocks.
        plan = reason.plan_query(ctx.prompt, mentions=ctx.mentions)
        context = await build_context(
            ctx.systems,
            ctx.prompt,
            project_id=ctx.project_id,
            scope=plan.scope,
            window=plan.window,
            budget=plan.budget,
            k=plan.k,
        )
        # SOLUSDEV-233: declare the turn's context up front so clients can show
        # what SOL is grounded in. Manifest only — no section text.
        yield AgentEvent.context_used(
            sections=[
                {"kind": s.kind, "citation": s.citation, "tokens": s.tokens}
                for s in context.sections
            ],
            truncated=context.truncated,
            dropped=len(context.dropped),
        )
        turns = self._opening_turns(ctx, nonce, context)
        completion = None

        for _ in range(MAX_MODEL_ROUNDS):
            completion = None
            async with ctx.sessionmaker() as session:
                stream = gateway.stream(
                    prompt.flatten(turns),
                    secret_store=ctx.secret_store,
                    context=ctx.interaction_context,
                    conversation=ToolConversation(system=system, messages=turns, tools=tools),
                    user_id=ctx.user_id,
                    session=session,
                    redis=ctx.redis,
                    enqueue=ctx.enqueue,
                    adapters=self._adapters,
                    max_tokens=SOL_MAX_TOKENS,
                    extension_id=ctx.extension_id,
                )
                try:
                    async for chunk in stream:
                        yield AgentEvent.token(chunk)
                finally:
                    # The transport breaks out of `async for event in runner.run()`
                    # when it trips its own guard, which throws GeneratorExit here.
                    # Without this the provider connection is abandoned open.
                    if stream.completion is None:
                        await stream.aclose()
                completion = stream.completion

            if completion is None:
                break
            if not completion.tool_calls:
                # Post-process: prose stripped of any model-authored Sources
                # line; verified citations travel as STRUCTURED data the model
                # cannot impersonate (SOL-02 review H1).
                prose, citations = reason.sanitize_reply(completion.text, context)
                yield AgentEvent.message(prose, citations=citations)
                return

            turns = (
                *turns,
                Turn(role="assistant", text=completion.text, tool_uses=completion.tool_calls),
            )
            outcomes: list[ToolOutcome] = []
            for use in completion.tool_calls:
                # The provider's own tool_use id becomes the call id, so results
                # correlate exactly with no mapping table anywhere.
                # The model answers with the name it was OFFERED (provider
                # charset); dispatch needs the real, dotted tool name back.
                call = ToolCall(
                    tool=prompt.resolve_tool_name(use.name, ctx.tools),
                    args=use.args,
                    call_id=use.id,
                )
                yield AgentEvent.tool_call(call)
                result = await ctx.dispatch(call)  # gates, then invokes
                # EVERY outcome goes back to the model, including a parked one.
                # A failure it can correct (NOT_FOUND for a hallucinated tool,
                # INVALID_ARGS, TIMEOUT) it corrects; a park it is told to leave
                # alone and work around. See the note below the loop.
                yield AgentEvent.tool_result(result)
                descriptor = next((d for d in ctx.tools if d.name == call.tool), None)
                outcomes.append(
                    prompt.contain_result(
                        call, result, cap=descriptor.result_cap if descriptor else None
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
        prose, citations = reason.sanitize_reply(final, context)
        yield AgentEvent.message(prose, citations=citations)

    @staticmethod
    def _opening_turns(ctx: AgentRunContext, nonce: str, context: "Context") -> tuple[Turn, ...]:
        """History, then the reasoning context, then the live message — every
        ingested string fenced as DATA (context sections fence themselves via
        Context.fenced)."""
        turns: list[Turn] = []
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
        turns.append(Turn(role="user", text=context.fenced(nonce) + "\n" + live))
        return tuple(turns)
