"""Builtin W0-04 tools over the real subsystems (SOLUS-SYS-03).

`run_checkers`, `query_graph`, `retrieve_errors`, `get_telemetry` — thin
closures over the real `SolSystems` (SYS-04's `DbSolSystems`), so the tool
layer and `build_context` share ONE data path per subsystem and cannot drift.
`run_checkers` additionally feeds the graph slice through CHK-01's real rules.

Scope discipline (CLAUDE.md §7): `project_id` is bound in the closure at
registration by Solus code and appears in NO params schema — ingested content
can never alter team scope. All four tools are reads: no confirmation gate,
default per-call timeout. Failures surface as structured `ToolResult(ok=False)`
via the registry's exception trapping — never an exception to the model.

Checker note: the empty `FingerprintOutput` is the sanctioned production shape
(the v1 rules read attributes straight off graph entities — see
`impact/consequences.py`, the only other production caller). `Warning.message`
and `.evidence` carry connector-ingested strings and are untrusted; they re-enter
the model only through the existing `prompt.contain_result` fencing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from solus_api.agent.interfaces import (
    ContextBudget,
    GraphScope,
    RetrievalFilter,
    TelemetryWindow,
)
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.checkers.core import run_all
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.widgets.graph_nodes import NON_WORKSPACE_DOMAINS

if TYPE_CHECKING:
    from solus_api.agent.interfaces import SolSystems

#: Matches `reason.plan_query`'s context cap — a tool result re-enters the model
#: context, so it gets the same sub-sampling budget as the planned context pull.
_GRAPH_BUDGET = ContextBudget(max_entities=200)
#: Checkers read attributes off the whole reachable slice — always 2 hops.
_CHECKER_DEGREE = 2

#: The checkers accept fingerprint output, but the v1 rules read the graph only —
#: empty is the sanctioned production shape (`impact/consequences.py`).
_EMPTY_FINGERPRINT = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])

_ENTITY_IDS_PARAM: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "format": "uuid"},
    "minItems": 1,
    "maxItems": 16,
    "description": "Anchor entity UUIDs (from query_graph/get_entity results).",
}

QUERY_GRAPH_DESCRIPTOR = ToolDescriptor(
    name="query_graph",
    description=(
        "Fetch the project's graph neighborhood around anchor entities: entities, "
        "typed relations between them, and whether the result was truncated."
    ),
    params={
        "type": "object",
        "properties": {
            "entity_ids": _ENTITY_IDS_PARAM,
            "degree": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2,
                "default": 1,
                "description": "Traversal hops from the anchors.",
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string", "maxLength": 64},
                "maxItems": 16,
                "description": "Narrow to these entity kinds.",
            },
            "domains": {
                "type": "array",
                # SOLUSDEV-246 ST2: a closed enum — the model cannot name the
                # `workspace` layer, so it cannot be steered into reading it.
                "items": {"type": "string", "enum": [d.value for d in NON_WORKSPACE_DOMAINS]},
                "maxItems": 16,
                "description": (
                    "Narrow to these domains (code/electrical/mechanical/simulation/runtime)."
                ),
            },
        },
        "required": ["entity_ids"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "entities": {"type": "array"},
            "edges": {"type": "array"},
            "truncated": {"type": "boolean"},
        },
        "required": ["entities", "edges", "truncated"],
        "additionalProperties": False,
    },
)

GET_TELEMETRY_DESCRIPTOR = ToolDescriptor(
    name="get_telemetry",
    description=(
        "Summarize the project's recent live telemetry over a window: per-signal "
        "stats bucketed into sub-windows. Empty when nothing is streaming."
    ),
    params={
        "type": "object",
        "properties": {
            "duration_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 3600,
                "description": "How far back to summarize.",
            },
            "signals": {
                "type": "array",
                "items": {"type": "string", "maxLength": 64},
                "maxItems": 16,
                "description": "Narrow to these signal names.",
            },
        },
        "required": ["duration_seconds"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {"windows": {"type": "array"}},
        "required": ["windows"],
        "additionalProperties": False,
    },
)

RETRIEVE_ERRORS_DESCRIPTOR = ToolDescriptor(
    name="retrieve_errors",
    description=(
        "Search the project's recorded error/solution history for entries similar "
        "to a query. Empty until errors have been captured for this project."
    ),
    params={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "The error or symptom to match.",
            },
            "k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
                "description": "Max hits to return.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {"hits": {"type": "array"}},
        "required": ["hits"],
        "additionalProperties": False,
    },
)

RUN_CHECKERS_DESCRIPTOR = ToolDescriptor(
    name="run_checkers",
    description=(
        "Run the cross-domain compatibility checkers over the graph around anchor "
        "entities; returns structured warnings sorted most-severe first."
    ),
    params={
        "type": "object",
        "properties": {"entity_ids": _ENTITY_IDS_PARAM},
        "required": ["entity_ids"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "warnings": {"type": "array"},
            "truncated": {"type": "boolean"},
        },
        "required": ["warnings", "truncated"],
        "additionalProperties": False,
    },
)


def _parse_entity_ids(raw: list[str]) -> list[UUID]:
    try:
        return [UUID(item) for item in raw]
    except ValueError as exc:
        # jsonschema's "format": "uuid" is annotation-only; enforce here so a bad
        # id is INVALID_ARGS, not an opaque tool crash.
        raise ToolException("entity_ids must be UUIDs", code=ToolErrorCode.INVALID_ARGS) from exc


def build_builtin_tools(systems: SolSystems, project_id: UUID) -> list[Tool]:
    """The four SYS-03 tools bound to ONE project scope, wrapping the real feeds."""

    async def query_graph_handler(args: dict[str, Any]) -> dict[str, Any]:
        scope = GraphScope(
            anchor_entity_ids=_parse_entity_ids(args["entity_ids"]),
            degree=int(args.get("degree", 1)),
            kinds=args.get("kinds"),
            domains=args.get("domains"),
        )
        context = await systems.get_graph_context(project_id, scope, _GRAPH_BUDGET)
        return context.model_dump(mode="json")

    async def get_telemetry_handler(args: dict[str, Any]) -> dict[str, Any]:
        window = TelemetryWindow(
            duration_seconds=float(args["duration_seconds"]), signals=args.get("signals")
        )
        view = await systems.get_telemetry(project_id, window)
        return view.model_dump(mode="json")

    async def retrieve_errors_handler(args: dict[str, Any]) -> dict[str, Any]:
        hits = await systems.get_error_history(
            args["query"], int(args.get("k", 5)), RetrievalFilter(project_id=project_id)
        )
        return {"hits": [hit.model_dump(mode="json") for hit in hits]}

    async def run_checkers_handler(args: dict[str, Any]) -> dict[str, Any]:
        scope = GraphScope(
            anchor_entity_ids=_parse_entity_ids(args["entity_ids"]), degree=_CHECKER_DEGREE
        )
        context = await systems.get_graph_context(project_id, scope, _GRAPH_BUDGET)
        warnings = run_all(context, _EMPTY_FINGERPRINT)
        return {
            "warnings": [warning.model_dump(mode="json") for warning in warnings],
            "truncated": context.truncated,
        }

    return [
        InProcessTool(QUERY_GRAPH_DESCRIPTOR, query_graph_handler),
        InProcessTool(GET_TELEMETRY_DESCRIPTOR, get_telemetry_handler),
        InProcessTool(RETRIEVE_ERRORS_DESCRIPTOR, retrieve_errors_handler),
        InProcessTool(RUN_CHECKERS_DESCRIPTOR, run_checkers_handler),
    ]
