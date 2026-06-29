"""ADR-011 data-collection events.

Server-originated events are emitted here on meaningful interactions.
Collection is consent-gated: without the user's consent flag nothing is
stored. A structured log line is always written for operability ("why did
this user's action fail?" — CLAUDE.md §6), payloads excluded.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import DataEvent, User

logger = logging.getLogger("solus.events")


def emit_event(
    session: AsyncSession,
    *,
    user: User,
    event_type: str,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "event=%s user=%s team=%s project=%s consented=%s",
        event_type,
        user.id,
        team_id,
        project_id,
        user.data_collection_consent,
    )
    if not user.data_collection_consent:
        return
    session.add(
        DataEvent(
            event_type=event_type,
            user_id=user.id,
            team_id=team_id,
            project_id=project_id,
            payload=payload or {},
        )
    )
