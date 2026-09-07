"""`code.resolve_environment` — the Code environment proposal as a SOL tool
(SOLUSDEV-250 / INTEGRATIONS I3; `docs/api/code-environment.md` §5).

Read-only and project-bound: it loads the project's `python_requirement` nodes
(landed by the local-folder scan), runs the pure `PinConflictChecker`, and
answers the same proposal the desktop row shows — one environment per
conflicting requirement file, otherwise one. It never installs anything: the
`code` server's gated tools do that, one approval card per command.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool, Tool
from solus_api.checkers.environment import REQUIREMENT_KIND, propose_environments
from solus_api.models import GraphEntity

MAX_REQUIREMENT_NODES: Final = 2000

RESOLVE_ENVIRONMENT_DESCRIPTOR = ToolDescriptor(
    name="code.resolve_environment",
    description=(
        "Propose the project's Python environment(s) from the dependency files Solus found in "
        "the linked folder: one environment per requirement file whose pins conflict with "
        "another's (for example an Isaac requirements file pinning one torch and the policy "
        "code wanting another), otherwise a single environment. Read-only. Use it before "
        "creating environments or installing packages with the code.* tools."
    ),
    params={"type": "object", "properties": {}, "additionalProperties": False},
    returns={
        "type": "object",
        "properties": {
            "environments": {"type": "array"},
            "conflicts": {"type": "array"},
            "split": {"type": "boolean"},
            "requirement_count": {"type": "integer"},
        },
        "required": ["environments", "conflicts", "split", "requirement_count"],
    },
)


async def requirement_context(session: AsyncSession, project_id: uuid.UUID) -> GraphContext:
    """The project's live requirement nodes as a checker-shaped graph (no edges needed)."""
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == REQUIREMENT_KIND,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.name)
        .limit(MAX_REQUIREMENT_NODES + 1)
    )
    entities = [
        EntityRead(
            id=row.id,
            kind=row.kind,
            domain=str(row.domain),
            name=row.name,
            external_ref=row.external_ref,
            attrs=dict(row.attrs or {}),
        )
        for row in rows.all()
    ]
    truncated = len(entities) > MAX_REQUIREMENT_NODES
    return GraphContext(entities=entities[:MAX_REQUIREMENT_NODES], edges=[], truncated=truncated)


async def resolve_environment(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    context = await requirement_context(session, project_id)
    proposal = propose_environments(context)
    return {**proposal, "requirement_count": len(context.entities), "truncated": context.truncated}


def build_resolve_environment_tool(
    session_factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> Tool:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        async with session_factory() as session:
            return await resolve_environment(session, project_id)

    return InProcessTool(RESOLVE_ENVIRONMENT_DESCRIPTOR, handler)
