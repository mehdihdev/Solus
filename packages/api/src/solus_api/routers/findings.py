"""Findings routes (docs/api/findings.md §3, SOLUSDEV-320)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.findings import (
    MAX_LIMIT,
    FindingSource,
    FindingStatus,
    SeverityName,
    acknowledge_finding,
    dismiss_finding,
    list_findings,
    load_finding,
    resolve_finding,
    serialize_finding,
    subject_rows,
)
from solus_api.graph.live import graph_changed_frame
from solus_api.models import GraphEntity, Role, utcnow
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_config import MAX_TEXT_CHARS

router = APIRouter(prefix="/api/v1/projects/{project_id}/findings")


class SubjectOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str


class FindingOut(BaseModel):
    """Headline, evidence and explanation are UNTRUSTED text (CLAUDE.md §7)."""

    id: uuid.UUID
    rule_id: str
    severity: SeverityName
    source: FindingSource
    status: FindingStatus
    headline: str
    explanation: str
    detail: str
    subjects: list[uuid.UUID]
    evidence: dict[str, Any]
    count: int
    first_seen: str
    last_seen: str
    matrix_cell: str | None
    domain: str
    dismissed_until: str | None
    created_at: datetime
    updated_at: datetime
    subject_entities: list[SubjectOut] | None = None


class ResolveOut(FindingOut):
    entry_id: uuid.UUID
    fixed_by_edge_id: uuid.UUID | None


class FindingPageMeta(BaseModel):
    limit: int
    has_next: bool
    next_cursor: str | None


class FindingListOut(BaseModel):
    data: list[FindingOut]
    meta: FindingPageMeta


class FindingOneOut(BaseModel):
    data: FindingOut


class ResolveEnvelope(BaseModel):
    data: ResolveOut


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    fix_ref: uuid.UUID | None = None


class DismissBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cooldown_hours: int = Field(default=24, ge=1, le=720)


async def _publish_graph_changed(
    request: Request, project_id: uuid.UUID, counts: GraphChangeCounts
) -> None:
    await request.app.state.graph_hub.publish(
        project_id,
        graph_changed_frame(
            project_id=project_id,
            source_id=None,
            sync_id=None,
            counts=counts,
            at=utcnow().isoformat(),
        ),
    )


@router.get("", response_model=FindingListOut)
async def list_project_findings(
    ctx: ProjectCtx,
    session: SessionDep,
    status: Annotated[FindingStatus, Query()] = "open",
    severity: Annotated[SeverityName | None, Query()] = None,
    subject: Annotated[uuid.UUID | None, Query()] = None,
    robot: Annotated[uuid.UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
) -> FindingListOut:
    rows, meta = await list_findings(
        session,
        ctx.project.id,
        status=status,
        severity=severity,
        subject=subject,
        robot=robot,
        cursor=cursor,
        limit=limit,
    )
    return FindingListOut(
        data=[FindingOut(**serialize_finding(r)) for r in rows], meta=FindingPageMeta(**meta)
    )


@router.get("/{finding_id}", response_model=FindingOneOut)
async def get_finding(finding_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> FindingOneOut:
    row = await load_finding(session, ctx.project.id, finding_id)
    subjects = await subject_rows(session, row)
    return FindingOneOut(data=FindingOut(**serialize_finding(row, subjects)))


@router.post("/{finding_id}/resolve", response_model=ResolveEnvelope)
async def resolve_finding_route(
    finding_id: uuid.UUID,
    body: ResolveBody,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
) -> ResolveEnvelope:
    require_role(ctx, Role.MEMBER)
    entry, edge = await resolve_finding(
        session, ctx.project.id, finding_id, ctx.user.id, note=body.note, fix_ref=body.fix_ref
    )
    row = await load_finding(session, ctx.project.id, finding_id)
    out = ResolveOut(
        **serialize_finding(row), entry_id=entry.id, fixed_by_edge_id=edge.id if edge else None
    )
    await session.commit()
    await _publish_graph_changed(
        request,
        ctx.project.id,
        GraphChangeCounts(entities_updated=1, relations_created=1 if edge else 0),
    )
    return ResolveEnvelope(data=out)


async def _status_change(
    request: Request, ctx: ProjectCtx, session: SessionDep, row: GraphEntity
) -> FindingOneOut:
    out = FindingOut(**serialize_finding(row))
    await session.commit()
    await _publish_graph_changed(request, ctx.project.id, GraphChangeCounts(entities_updated=1))
    return FindingOneOut(data=out)


@router.post("/{finding_id}/dismiss", response_model=FindingOneOut)
async def dismiss_finding_route(
    finding_id: uuid.UUID,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    body: DismissBody | None = None,
) -> FindingOneOut:
    require_role(ctx, Role.MEMBER)
    hours = (body or DismissBody()).cooldown_hours
    row = await dismiss_finding(session, ctx.project.id, finding_id, ctx.user.id, hours)
    return await _status_change(request, ctx, session, row)


@router.post("/{finding_id}/acknowledge", response_model=FindingOneOut)
async def acknowledge_finding_route(
    finding_id: uuid.UUID, request: Request, ctx: ProjectCtx, session: SessionDep
) -> FindingOneOut:
    require_role(ctx, Role.MEMBER)
    row = await acknowledge_finding(session, ctx.project.id, finding_id, ctx.user.id)
    return await _status_change(request, ctx, session, row)
