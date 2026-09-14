"""Project-bound rail accounting over the existing systems graph read boundary."""

import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from solus_api.agent.interfaces import ContextBudget, GraphScope, SolSystems
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.agent.tools.untrusted import redact_value
from solus_api.checkers.rail_current import analyze_rail_current


class RailArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rail_entity_id: str


DESCRIPTOR = ToolDescriptor(
    name="analyze_rail_current",
    description=(
        "Report declared current contributions for one electrical net in the project graph. "
        "Use a net entity UUID, not a net name or file path. Missing or unqualified part currents "
        "remain unknown; incomplete subtotals never mean the rail is safe. No device access."
    ),
    params={
        "type": "object",
        "properties": {"rail_entity_id": {"type": "string", "format": "uuid"}},
        "required": ["rail_entity_id"],
        "additionalProperties": False,
    },
    returns={"type": "object"},
    result_cap=64_000,
)


def build_rail_current_tool(systems: SolSystems, project_id: UUID) -> Tool:
    async def invoke(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            args = RailArgs.model_validate(raw)
            identity = UUID(args.rail_entity_id)
        except (ValidationError, ValueError):
            raise ToolException(
                "rail_entity_id must be a UUID", code=ToolErrorCode.INVALID_ARGS
            ) from None
        context = await systems.get_graph_context(
            project_id,
            GraphScope(anchor_entity_ids=[identity], degree=2),
            ContextBudget(max_entities=256),
        )
        try:
            report = analyze_rail_current(context, identity)
        except ValueError:
            raise ToolException(
                "Electrical rail not found in this project graph.", code=ToolErrorCode.NOT_FOUND
            ) from None

        # Match the prompt's redaction/ASCII/fence escaping before its cap can
        # slice a complete report into a misleading JSON prefix.
        encoded = json.dumps(
            {"ok": True, "value": redact_value(report)}, ensure_ascii=True, separators=(",", ":")
        ).replace("<", "\\u003c")
        if len(encoded) > 64_000:
            raise ToolException(
                "The complete rail report exceeds its output limit.", code=ToolErrorCode.UNAVAILABLE
            )
        return report

    return InProcessTool(DESCRIPTOR, invoke)
