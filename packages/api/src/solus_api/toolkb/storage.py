"""SOLUS-TU-04 — read side of the tool-knowledge store.

Read-only by design: the ONLY write path into `tool_knowledge` is the TU-06
guard (`toolkb.guard`). This module serves published, live rows to every
tenant — the store is cross-tenant on purpose; the boundary is what the rows
cannot contain, not who may read them (docs/contracts/tool-knowledge.md).
"""

from typing import Any, Final

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.contracts.tool_knowledge import ControlEffect, ToolFamily, UiSurface
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry, version_key

MAX_QUERY_LIMIT: Final = 100


async def query_entries(
    session: AsyncSession,
    *,
    tool: ToolFamily,
    version: str | None = None,
    surface: UiSurface | None = None,
    effect: ControlEffect | None = None,
    control_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[ToolKnowledgeEntry], dict[str, Any]]:
    """Published, live entries for one tool, §1.4 cursor-paginated.

    ``version`` (e.g. ``"8.0.6"``) narrows to entries whose version window
    contains it — a pure btree range test on the derived keys. Raises
    ``ValueError`` on an unparseable version or an out-of-range limit; the
    router maps both to 422.
    """
    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise ValueError(f"limit must be 1..{MAX_QUERY_LIMIT}")
    stmt = (
        select(ToolKnowledgeEntry)
        .where(
            ToolKnowledgeEntry.deleted_at.is_(None),
            ToolKnowledgeEntry.status == KnowledgeStatus.PUBLISHED,
            ToolKnowledgeEntry.tool == tool,
        )
        .order_by(ToolKnowledgeEntry.created_at.desc(), ToolKnowledgeEntry.id.desc())
        .limit(limit + 1)
    )
    if version is not None:
        vkey = version_key(version)
        stmt = stmt.where(
            ToolKnowledgeEntry.version_min_key <= vkey,
            or_(
                ToolKnowledgeEntry.version_max_key.is_(None),
                ToolKnowledgeEntry.version_max_key > vkey,
            ),
        )
    if surface is not None:
        stmt = stmt.where(ToolKnowledgeEntry.surface == surface)
    if effect is not None:
        stmt = stmt.where(ToolKnowledgeEntry.effect == effect)
    if control_id is not None:
        stmt = stmt.where(ToolKnowledgeEntry.control_id == control_id)
    if cursor is not None:
        stmt = stmt.where(
            cursor_filter(ToolKnowledgeEntry.created_at, ToolKnowledgeEntry.id, cursor)
        )
    rows = list((await session.execute(stmt)).scalars())
    return page_meta(rows, limit)
