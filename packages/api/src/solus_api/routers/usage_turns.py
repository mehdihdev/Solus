"""SOLUSDEV-321 P8: `GET /api/v1/projects/{project_id}/usage/turns` — the caller's own model and web
calls in this project, one credit-ledger row each, newest first: why each ran (`purpose`), the tier
it was routed at, the turn it belonged to and what it cost.

The read filters `CreditLedger.user_id == ctx.user.id` first (the indexed column: this person's rows
and never a teammate's; `ix_credit_ledger_user_created` serves the order), then the project the
row's attrs name, USAGE rows only. It never returns `balance_after` or any other balance. Paged like
the outcomes (at most 200 a page, no further back than `core/pagination.READ_WINDOW`); reads draw on
the app-wide read budget (`core/ratelimit.RateLimitMiddleware`). Scoped through `ProjectCtx`:
another team's project is a 404.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from solus_api.core.pagination import PageMeta, cursor_filter, page_meta, since_floor
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import CreditLedger, CreditTxnType

router = APIRouter(prefix="/api/v1/projects/{project_id}/usage/turns")

MAX_LIMIT: Final = 200


class UsageTurnOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    turn_id: str | None
    purpose: str | None
    #: The routed model's tier; None for a web call, which no model answered.
    tier: str | None
    #: Credits spent; 0 for a call that cost nothing.
    credits: int
    tokens_in: int | None
    tokens_out: int | None


class UsageTurnListOut(BaseModel):
    data: list[UsageTurnOut]
    meta: PageMeta


def _usage_item(row: Any) -> UsageTurnOut:
    """A ledger row as the route shows it: the attrs it names, each only when it has its type."""
    attrs = row.attrs if isinstance(row.attrs, dict) else {}
    texts = {
        key: value if isinstance(value := attrs.get(key), str) else None
        for key in ("turn_id", "purpose", "tier")
    }
    counts = {
        key: value if isinstance(value := attrs.get(key), int) else None
        for key in ("tokens_in", "tokens_out")
    }
    fields = {"id": row.id, "created_at": row.created_at, "credits": -row.amount}
    return UsageTurnOut.model_validate({**fields, **texts, **counts})


@router.get("", response_model=UsageTurnListOut)
async def list_usage_turns(
    ctx: ProjectCtx,
    session: SessionDep,
    since: Annotated[datetime | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> UsageTurnListOut:
    stmt = (
        select(CreditLedger.id, CreditLedger.created_at, CreditLedger.amount, CreditLedger.attrs)
        .where(
            CreditLedger.user_id == ctx.user.id,
            CreditLedger.attrs["project_id"].astext == str(ctx.project.id),
            CreditLedger.type == CreditTxnType.USAGE,
            CreditLedger.created_at >= since_floor(since),
        )
        .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(CreditLedger.created_at, CreditLedger.id, cursor))
    rows, meta = page_meta(list(await session.execute(stmt)), limit)
    return UsageTurnListOut(data=[_usage_item(row) for row in rows], meta=PageMeta(**meta))
