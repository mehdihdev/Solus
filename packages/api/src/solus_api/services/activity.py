"""Team activity feed recording (§2.2). Callers own the commit."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Activity


def record_activity(
    session: AsyncSession,
    *,
    team_id: uuid.UUID,
    activity_type: str,
    actor_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    domain: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Activity:
    activity = Activity(
        team_id=team_id,
        type=activity_type,
        actor_id=actor_id,
        project_id=project_id,
        domain=domain,
        payload=payload or {},
    )
    session.add(activity)
    return activity
