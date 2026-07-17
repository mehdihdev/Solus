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
- `ScaffoldRunner` — a deterministic, model-free runner (mock-and-swap, like
  `FakeSolSystems`). It proves the plumbing end to end: it lists tools, invokes the
  W0-04 reference tool through the registry, pulls W0-07 graph context, respects the
  per-user SOL mode (ADR-016), and honors a bounded tool-call loop guard (§7). The real
  model-backed loop swaps in behind `AgentRunner` with NO transport or endpoint change.
"""

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.interfaces import GraphScope, SolSystems
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools import ToolCall, ToolRegistry, ToolResult, build_get_entity_tool
from solus_api.models import SolMode
from solus_api.orchestration.enums import InteractionContext
from solus_api.orchestration.router import derive_complexity

# §7 loop/recursion guard: an upper bound on tool calls per turn so a runaway loop
# can never fan out unboundedly. The scaffold proposes ≤1; the guard protects the seam
# for the real runner that swaps in later.
MAX_TOOL_CALLS = 8
# Graph traversal depth for the scaffold's W0-07 context pull (the 2-degree perf lever).
_CONTEXT_DEGREE = 1

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def build_sol_registry(
    session_factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ToolRegistry:
    """Assemble the tool set SOL may invoke for ONE request, each tool bound to the
    request's project scope by Solus code. v1 exposes the W0-04 reference tool; new
    tools are registered here, never proposed by a model."""
    registry = ToolRegistry()
    registry.register(build_get_entity_tool(session_factory, project_id))
    return registry


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
    `registry` and `project_id` are already scoped before the runner runs."""

    prompt: str
    registry: ToolRegistry
    systems: SolSystems
    project_id: uuid.UUID
    sol_mode: SolMode = SolMode.GUIDE
    history: tuple[TurnView, ...] = ()
    interaction_context: InteractionContext = InteractionContext.SOL_OPEN_QUESTION


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
        tools = ctx.registry.list()
        # W0-03 gateway: derive the complexity tier with NO model call (wired, not used
        # to pick a real model here — that lands in MO-01).
        complexity = derive_complexity(ctx.interaction_context)

        results: list[ToolResult] = []
        for call in plan_tool_calls(ctx.prompt)[:MAX_TOOL_CALLS]:
            yield AgentEvent.tool_call(call)
            result = await ctx.registry.invoke(call)  # registry validates + scopes + never raises
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
