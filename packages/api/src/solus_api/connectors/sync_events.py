"""ADR-011 sync-outcome events (`source.sync_succeeded` / `source.sync_failed`).

Emitted from the sync runtime, which has no request user: the actor is the user the
job was created for. A sync with no job (a scheduled sweep) has no actor, so only the
structured log line records it. Payloads carry counts and a stable error code — never
design content or exception text."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Job, Source, Sync, User
from solus_api.services.events import emit_event


async def emit_sync_outcome(
    session: AsyncSession,
    *,
    job_id: uuid.UUID | None,
    source: Source,
    sync: Sync,
    error_code: str | None = None,
) -> None:
    job = await session.get(Job, job_id) if job_id is not None else None
    user = await session.get(User, job.created_by) if job and job.created_by else None
    if job is None or user is None:
        return
    payload: dict[str, object] = {
        "source_id": str(source.id),
        "sync_id": str(sync.id),
        "source_type": source.type.value,
    }
    if error_code is None:
        payload.update(
            entities_created=sync.entities_created,
            entities_updated=sync.entities_updated,
            relations_created=sync.relations_created,
            relations_deleted=sync.relations_deleted,
            error_count=len(sync.errors),
        )
    else:
        payload["error_code"] = error_code
    emit_event(
        session,
        user=user,
        event_type="source.sync_succeeded" if error_code is None else "source.sync_failed",
        team_id=job.team_id,
        project_id=source.project_id,
        payload=payload,
    )
