"""Candidate edges (docs/api/relations.md §3, SOLUSDEV-320): list, confirm, decline."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.edges import candidates, confirm_edge, decline_edge
from solus_api.graph.live import graph_changed_frame
from solus_api.graph.read_scope import current_scope
from solus_api.models import GraphEdge, Role, utcnow
from solus_api.schemas import serialize_relation
from solus_api.services.activity import record_activity
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_config import MAX_TEXT_CHARS

router = APIRouter(prefix="/api/v1/projects/{project_id}/edges")

MAX_CANDIDATES = 500


class DeclineBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


async def _decided(
    request: Request,
    session: SessionDep,
    ctx: ProjectCtx,
    edge: GraphEdge,
    decision: str,
    reason: str | None = None,
) -> dict[str, Any]:
    # SOLUSDEV-320 P5-T7 (solus.md §9): one history row naming both endpoints.
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type=f"edge.{decision}",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        payload={"edge_id": str(edge.id), "relation_type": edge.relation_type, "reason": reason},
        entity_ids=[edge.src_id, edge.dst_id],
    )
    await session.commit()
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(relations_created=1),
            at=utcnow().isoformat(),
        ),
    )
    return envelope(serialize_relation(edge))


@router.get("/candidates")
async def list_edge_candidates(
    ctx: ProjectCtx,
    session: SessionDep,
    relation_type: Annotated[str | None, Query(max_length=64)] = None,
    subject: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_CANDIDATES)] = 200,
) -> dict[str, Any]:
    rows = await candidates(
        session, ctx.project.id, relation_type=relation_type, subject=subject, limit=limit
    )
    scope = current_scope(ctx.project.id)
    return envelope([serialize_relation(scope.project_edge(row)) for row in rows])


@router.post("/{edge_id}/confirm")
async def confirm_edge_route(
    edge_id: uuid.UUID, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    edge = await confirm_edge(session, ctx.project.id, edge_id, ctx.user.id)
    return await _decided(request, session, ctx, edge, "confirmed")


@router.post("/{edge_id}/decline")
async def decline_edge_route(
    edge_id: uuid.UUID,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    body: DeclineBody | None = None,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    reason = body.reason if body is not None else None
    edge = await decline_edge(session, ctx.project.id, edge_id, ctx.user.id, reason)
    return await _decided(request, session, ctx, edge, "declined", reason)
