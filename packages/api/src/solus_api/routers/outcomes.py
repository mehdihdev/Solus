"""SOLUSDEV-321 P8: `GET /api/v1/projects/{project_id}/outcomes` — the project's proposal outcomes
(`services/outcomes.py`; the table: `docs/schemas/proposal-outcomes.md`), newest first,
cursor-paginated: at most 200 a page, no further back than `core/pagination.READ_WINDOW`. Scoped
through `ProjectCtx` (§7 tenant isolation; a non-member gets 404) and then by `project_id`. The
outcomes are team data, so every member lists them; a row's `machine_id`, `conversation_turn_id` and
unkeyed `proposal_digest` are the decider's own and reach only them (R146, M6 — the owner rule
conversations and confirmations keep). A row names no arguments. Reads draw on the app-wide read
budget (`core/ratelimit.RateLimitMiddleware`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from solus_api.core.pagination import PageMeta, cursor_filter, page_meta, since_floor
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import ProposalOutcome
from solus_api.services.outcomes import OutcomeDecision, StaleReason

router = APIRouter(prefix="/api/v1/projects/{project_id}/outcomes")

MAX_LIMIT: Final = 200
#: The fields only the decider reads: a teammate lists the row with them null.
DECIDER_ONLY: Final = ("machine_id", "conversation_turn_id", "proposal_digest")


class OutcomeOut(BaseModel):
    id: uuid.UUID
    #: The decision's tool turn — null unless the caller made the decision.
    conversation_turn_id: uuid.UUID | None
    tool: str
    #: Null unless the caller made the decision: it is unkeyed until a digest key exists (M6).
    proposal_digest: str | None
    decision: OutcomeDecision
    #: Why a `stale` card was refused (M190); null for every other decision, and when unknown.
    stale_reason: StaleReason | None = None
    #: Every id the call named that is this project's own (M191).
    entity_ids: list[str]
    design_signals: dict[str, str]
    #: The decider's machine — null unless the caller made the decision.
    machine_id: uuid.UUID | None
    created_at: datetime


class OutcomeListOut(BaseModel):
    data: list[OutcomeOut]
    meta: PageMeta


def _seen_by(row: ProposalOutcome, viewer: uuid.UUID) -> OutcomeOut:
    """`row` as `viewer` reads it: a teammate's decision without its machine, turn or digest."""
    shown = OutcomeOut.model_validate(row, from_attributes=True)
    if row.user_id == viewer:
        return shown
    return shown.model_copy(update=dict.fromkeys(DECIDER_ONLY))


@router.get("", response_model=OutcomeListOut)
async def list_outcomes(
    ctx: ProjectCtx,
    session: SessionDep,
    since: Annotated[datetime | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> OutcomeListOut:
    stmt = (
        select(ProposalOutcome)
        .where(
            ProposalOutcome.project_id == ctx.project.id,
            ProposalOutcome.created_at >= since_floor(since),
        )
        .order_by(ProposalOutcome.created_at.desc(), ProposalOutcome.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(ProposalOutcome.created_at, ProposalOutcome.id, cursor))
    rows, meta = page_meta(list(await session.scalars(stmt)), limit)
    return OutcomeListOut(data=[_seen_by(row, ctx.user.id) for row in rows], meta=PageMeta(**meta))
