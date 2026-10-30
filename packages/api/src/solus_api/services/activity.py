"""Team activity feed recording (§2.2) — and, since SOLUSDEV-320, the project history
(docs/api/solus.md §9): every row may name the graph entities it touches (`entity_ids`) and
the reason it happened (`why_ref`). Callers own the commit."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Activity, Project

logger = logging.getLogger("solus.services.activity")

WHY_REF_CHARS = 128


def record_activity(
    session: AsyncSession,
    *,
    team_id: uuid.UUID,
    activity_type: str,
    actor_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    domain: str | None = None,
    payload: dict[str, Any] | None = None,
    entity_ids: list[uuid.UUID] | None = None,
    why_ref: str | None = None,
) -> Activity:
    activity = Activity(
        team_id=team_id,
        type=activity_type,
        actor_id=actor_id,
        project_id=project_id,
        domain=domain,
        payload=payload or {},
        entity_ids=[str(entity_id) for entity_id in entity_ids or []],
        why_ref=why_ref[:WHY_REF_CHARS] if why_ref else None,
    )
    session.add(activity)
    return activity


async def record_project_activity(
    session: AsyncSession,
    project_id: uuid.UUID,
    activity_type: str,
    *,
    actor_id: uuid.UUID | None = None,
    domain: str | None = None,
    payload: dict[str, Any] | None = None,
    entity_ids: list[uuid.UUID] | None = None,
    why_ref: str | None = None,
) -> Activity | None:
    """`record_activity` for a writer that holds a project but not its team (services and
    hooks); a vanished project is logged and skipped, never a failed write."""
    team_id = await session.scalar(select(Project.team_id).where(Project.id == project_id))
    if team_id is None:
        logger.warning(
            "history row skipped: project=%s not found type=%s", project_id, activity_type
        )
        return None
    return record_activity(
        session,
        team_id=team_id,
        activity_type=activity_type,
        actor_id=actor_id,
        project_id=project_id,
        domain=domain,
        payload=payload,
        entity_ids=entity_ids,
        why_ref=why_ref,
    )
