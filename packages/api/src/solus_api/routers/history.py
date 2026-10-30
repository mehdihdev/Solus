"""docs/api/solus.md §9 (SOLUSDEV-320): the project history. The `history` section of the
`.solus` owns no rows; its node renders this route — the project's `activities` with
`entity_ids` and `why_ref`, newest first, cursor-paginated. Scoped through `ProjectCtx`
(§7 tenant isolation; non-member → 404) and then by `project_id`, so every filter below
narrows within one project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, select

from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import Activity
from solus_api.schemas import serialize_activity

router = APIRouter(prefix="/api/v1/projects/{project_id}/history")

MAX_LIMIT = 200


@router.get("")
async def list_history(
    ctx: ProjectCtx,
    session: SessionDep,
    since: Annotated[datetime | None, Query()] = None,
    entity: Annotated[uuid.UUID | None, Query()] = None,
    domain: Annotated[str | None, Query(max_length=32)] = None,
    actor: Annotated[uuid.UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> dict[str, Any]:
    conditions: list[ColumnElement[bool]] = [Activity.project_id == ctx.project.id]
    if since is not None:
        # A naive timestamp is read as UTC; `created_at` is timezone-aware.
        conditions.append(Activity.created_at >= since.replace(tzinfo=since.tzinfo or UTC))
    if entity is not None:
        conditions.append(Activity.entity_ids.contains([str(entity)]))  # jsonb @>
    if domain is not None:
        conditions.append(Activity.domain == domain)
    if actor is not None:
        conditions.append(Activity.actor_id == actor)
    stmt = (
        select(Activity)
        .where(*conditions)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(Activity.created_at, Activity.id, cursor))
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_activity(row) for row in visible], meta=meta)
