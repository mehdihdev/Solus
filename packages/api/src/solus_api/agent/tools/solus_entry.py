"""`add_solus_entry` — SOL files a note into a project's `.solus` (SOLUSDEV-240).

The first WRITE builtin. It is deliberately NOT confirmation-gated: it appends one
bounded, project-scoped text row that the team can edit or delete from the
Workspace panel — none of CLAUDE.md §7's destructive classes (flash, deploy,
mutate an external system, delete graph data). Nothing it writes ever re-enters a
prompt as instructions; `.solus` text is data like every other ingested string.
Scope is bound at construction by Solus code: the model chooses only the section,
an optional subsection, and the text. `history` and `members` take no notes from
SOL. Automatic error filing (`agent/errors_filing.py`) writes through the same service.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.core.errors import APIError
from solus_api.models import SolusSection
from solus_api.services.solus_config import MAX_TEXT_CHARS, SECTION_LABELS, add_text_entry

_NO_NOTES = (SolusSection.HISTORY, SolusSection.MEMBERS)

ADD_SOLUS_ENTRY_DESCRIPTOR = ToolDescriptor(
    name="add_solus_entry",
    description=(
        "File a short note into a section of this project's .solus — the team's "
        "project-level configuration. Sections: "
        + "; ".join(f"{s.value} = {label}" for s, label in SECTION_LABELS.items())
        + ". Use it when the person asks you to find or record something for a section; "
        "name your sources in the text. Do not file when you found nothing."
    ),
    params={
        "type": "object",
        "properties": {
            "section": {"type": "string", "enum": [s.value for s in SolusSection]},
            "subsection": {"type": "string", "minLength": 1, "maxLength": 32},
            "text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_CHARS},
        },
        "required": ["section", "text"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "section": {"type": "string"},
            "subsection": {"type": ["string", "null"]},
            "text": {"type": "string"},
        },
        "required": ["id", "section", "subsection", "text"],
        "additionalProperties": False,
    },
)


def build_add_solus_entry_tool(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
) -> Tool:
    """Bound to ONE project and the requesting user (the tool runs with that
    user's permissions; the row records them as `created_by`, author `sol`)."""

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            section = SolusSection(args["section"])
        except ValueError:
            raise ToolException(
                f"Unknown .solus section {args['section']!r}", code=ToolErrorCode.INVALID_ARGS
            ) from None
        if section in _NO_NOTES:
            raise ToolException(
                f"The {section.value} section takes no notes", code=ToolErrorCode.INVALID_ARGS
            )
        subsection = args.get("subsection")
        async with session_factory() as session:
            try:
                entry = await add_text_entry(
                    session,
                    project_id,
                    section,
                    str(args["text"]),
                    author="sol",
                    created_by=user_id,
                    subsection=str(subsection) if subsection is not None else None,
                )
                await session.commit()
            except APIError as exc:
                raise ToolException(exc.message, code=ToolErrorCode.INVALID_ARGS) from None
            return {
                "id": str(entry.id),
                "section": section.value,
                "subsection": entry.subsection,
                "text": entry.text or "",
            }

    return InProcessTool(ADD_SOLUS_ENTRY_DESCRIPTOR, handler)
