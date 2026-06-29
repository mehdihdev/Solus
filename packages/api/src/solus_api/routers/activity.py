"""§2.2 Team activity feed — cursor-paginated, filterable."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import SessionDep, TeamCtx
from solus_api.models import Activity
from solus_api.schemas import serialize_activity

router = APIRouter(prefix="/api/v1/teams/{team_id}/activity")


@router.get("")
async def list_activity(
    ctx: TeamCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    type: Annotated[str | None, Query()] = None,  # noqa: A002 - API.md filter name
    domain: Annotated[str | None, Query()] = None,
    actor: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    stmt = (
        select(Activity)
        .where(Activity.team_id == ctx.team.id)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(limit + 1)
    )
    if type is not None:
        stmt = stmt.where(Activity.type == type)
    if domain is not None:
        stmt = stmt.where(Activity.domain == domain)
    if actor is not None:
        stmt = stmt.where(Activity.actor_id == actor)
    if cursor:
        stmt = stmt.where(cursor_filter(Activity.created_at, Activity.id, cursor))
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_activity(a) for a in visible], meta=meta)
