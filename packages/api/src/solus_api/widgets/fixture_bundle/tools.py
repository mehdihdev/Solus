"""The fixture bundle's two SOL tools (SOLUSDEV-246).

`fixture-bundle.add_note` writes one `ext:fixture-bundle:note` entity;
`fixture-bundle.clear_notes` soft-deletes them all and is confirmation-gated
with a Solus-authored `consent_summary` and a before/after `preview`, so the
fixture exercises the W0-04 registry AND the action gate end to end. Scope is
bound by Solus code (`BundleScope`), never by args — `additionalProperties:
false` makes a smuggled `project_id` an `INVALID_ARGS` result.
"""

from __future__ import annotations

import uuid
from typing import Any

from solus_contracts.extension_manifest import composed_tool_name, graph_kind_name
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool, Tool
from solus_api.models import Domain, GraphEntity, utcnow
from solus_api.widgets.capability import BundleScope

SLUG = "fixture-bundle"
NOTE_KIND = graph_kind_name(SLUG, "note")
NOTE_MAX_LEN = 200
ORIGIN = "extension"

ADD_NOTE = ToolDescriptor(
    name=composed_tool_name(SLUG, "add_note"),
    description=(
        "Add a short note to this project as a Fixture Bundle note entity "
        "(kind ext:fixture-bundle:note). Returns the new entity's id."
    ),
    params={
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": NOTE_MAX_LEN},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "kind": {"type": "string"},
        },
        "required": ["id", "name", "kind"],
        "additionalProperties": False,
    },
)

CLEAR_NOTES = ToolDescriptor(
    name=composed_tool_name(SLUG, "clear_notes"),
    description="Remove every Fixture Bundle note from this project.",
    params={"type": "object", "properties": {}, "additionalProperties": False},
    returns={
        "type": "object",
        "properties": {"cleared": {"type": "integer", "minimum": 0}},
        "required": ["cleared"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
    consent_summary="Delete every note the Fixture Bundle added to this project",
)


def _live_notes(project_id: uuid.UUID) -> Any:
    return (
        GraphEntity.project_id == project_id,
        GraphEntity.kind == NOTE_KIND,
        GraphEntity.deleted_at.is_(None),
    )


async def _count(session: AsyncSession, project_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count()).select_from(GraphEntity).where(*_live_notes(project_id))
    )
    return int(total or 0)


def build_add_note(scope: BundleScope) -> Tool:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        text = str(args["text"])
        async with scope.session_factory() as session:
            row = GraphEntity(
                project_id=scope.project_id,
                kind=NOTE_KIND,
                domain=Domain.CODE,
                name=text,
                origin=ORIGIN,
                attrs={
                    "text": text,
                    "created_by": str(scope.user_id) if scope.user_id else None,
                },
            )
            session.add(row)
            await session.commit()
            return {"id": str(row.id), "name": text, "kind": NOTE_KIND}

    return InProcessTool(ADD_NOTE, handler)


def build_clear_notes(scope: BundleScope) -> Tool:
    async def preview(_args: dict[str, Any]) -> list[dict[str, Any]]:
        async with scope.session_factory() as session:
            before = await _count(session, scope.project_id)
        return [{"label": "Notes in this project", "before": str(before), "after": "0"}]

    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        async with scope.session_factory() as session:
            cleared = await _count(session, scope.project_id)
            if cleared:
                await session.execute(
                    update(GraphEntity)
                    .where(*_live_notes(scope.project_id))
                    .values(deleted_at=utcnow())
                )
            await session.commit()
            return {"cleared": cleared}

    return InProcessTool(CLEAR_NOTES, handler, preview=preview)
