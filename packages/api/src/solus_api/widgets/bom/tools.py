"""The BOM widget's SOL tool (SOLUSDEV-246 ST4): `bom.add_item`.

Adds a planned purchase or raw-material row — the "planned motor from sourcing"
path when the user asks SOL for it. Additive and reversible (a soft-deletable
graph row), so it is not confirmation-gated. Scope is bound by Solus code
(`BundleScope`); `additionalProperties: false` makes a smuggled `project_id` an
`INVALID_ARGS` result at the registry.
"""

from __future__ import annotations

from typing import Any

from solus_contracts.extension_manifest import composed_tool_name

from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool, Tool
from solus_api.widgets.bom import service
from solus_api.widgets.bom.rows import (
    COST_MAX,
    DEFAULT_ITEM_STATE,
    ITEM_CATEGORIES,
    NAME_MAX,
    NOTES_MAX,
    QUANTITY_MAX,
    SLUG,
    TEXT_MAX,
)
from solus_api.widgets.capability import BundleScope

_STRING = {"type": "string", "minLength": 1, "maxLength": TEXT_MAX}

ADD_ITEM = ToolDescriptor(
    name=composed_tool_name(SLUG, "add_item"),
    description=(
        "Add a row to this project's bill of materials for something the design does not "
        "know about yet: a planned purchase (a motor being sourced) or a raw material "
        "(stock, plate, fasteners). The row starts in the 'planned' lifecycle state. "
        "Parts already in CAD or the schematic are listed automatically — never add those."
    ),
    params={
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": NAME_MAX},
            "category": {"type": "string", "enum": list(ITEM_CATEGORIES)},
            "quantity": {"type": "integer", "minimum": 1, "maximum": QUANTITY_MAX},
            "part_number": {"type": "string", "minLength": 1, "maxLength": 64},
            "manufacturer": _STRING,
            "supplier": _STRING,
            "unit_cost": {"type": "number", "minimum": 0, "maximum": COST_MAX},
            "notes": {"type": "string", "minLength": 1, "maxLength": NOTES_MAX},
        },
        "required": ["name", "category"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "key": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string"},
            "state": {"type": "string"},
        },
        "required": ["id", "key", "name", "category", "state"],
        "additionalProperties": False,
    },
)


def build_add_item(scope: BundleScope) -> Tool:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        fields = {
            k: args[k]
            for k in ("quantity", "part_number", "manufacturer", "supplier", "unit_cost", "notes")
            if k in args
        }
        async with scope.session_factory() as session:
            row = await service.create_item(
                session,
                project_id=scope.project_id,
                user_id=scope.user_id,
                name=str(args["name"]),
                category=str(args["category"]),
                fields=fields,
                manifest=scope.manifest,
            )
            await session.commit()
            return {
                "id": str(row.id),
                "key": f"item:{row.id}",
                "name": row.name,
                "category": str(args["category"]),
                "state": DEFAULT_ITEM_STATE,
            }

    return InProcessTool(ADD_ITEM, handler)
