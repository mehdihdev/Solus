"""§2.2 Team activity feed — cursor-paginated, filterable."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, select

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
    conditions: list[ColumnElement[bool]] = [Activity.team_id == ctx.team.id]
    if type is not None:
        conditions.append(Activity.type == type)
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

    # Total matching the filters across the whole feed (cursor-independent),
    # so clients can render an accurate "view all activity (N)" count.
    total = await session.scalar(select(func.count()).select_from(Activity).where(*conditions))

    visible, meta = page_meta(rows, limit)
    return envelope([serialize_activity(a) for a in visible], meta={**meta, "total": total})
