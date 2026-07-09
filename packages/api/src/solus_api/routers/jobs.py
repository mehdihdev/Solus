"""§2.16 Jobs — shared job infrastructure (ADR-005). Status, list, cancel.

Phase 1 ships the resource surface; job-producing endpoints (sync, checks,
proving) arrive in Phases 3–4 and resolve here.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, ProjectCtx, SessionDep, live_membership
from solus_api.models import Job, JobKind, JobStatus, utcnow
from solus_api.schemas import serialize_job
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1")

CANCELLABLE = (JobStatus.QUEUED, JobStatus.RUNNING)


async def _get_scoped_job(session: SessionDep, user: CurrentUser, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    membership = await live_membership(session, job.team_id, user.id) if job else None
    if job is None or membership is None:
        raise APIError(404, "not_found", "Job not found")
    return job


@router.get("/jobs/{job_id}")
async def get_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    job = await _get_scoped_job(session, user, job_id)
    return envelope(serialize_job(job))


@router.get("/projects/{project_id}/jobs")
async def list_project_jobs(
    ctx: ProjectCtx,
    session: SessionDep,
    kind: Annotated[JobKind | None, Query()] = None,
    status: Annotated[JobStatus | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    stmt = (
        select(Job)
        .where(Job.project_id == ctx.project.id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit + 1)
    )
    if kind is not None:
        stmt = stmt.where(Job.kind == kind)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    if cursor:
        stmt = stmt.where(cursor_filter(Job.created_at, Job.id, cursor))
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_job(j) for j in visible], meta=meta)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    job = await _get_scoped_job(session, user, job_id)
    if job.status not in CANCELLABLE:
        raise APIError(
            409,
            "job_not_cancellable",
            f"Job is already {job.status.value}",
        )
    job.status = JobStatus.CANCELLED
    job.finished_at = utcnow()
    record_activity(
        session,
        team_id=job.team_id,
        activity_type="job.cancelled",
        actor_id=user.id,
        project_id=job.project_id,
        payload={"kind": job.kind.value},
    )
    emit_event(
        session,
        user=user,
        event_type="job.cancelled",
        team_id=job.team_id,
        project_id=job.project_id,
    )
    await session.commit()
    await session.refresh(job)
    return envelope(serialize_job(job))
