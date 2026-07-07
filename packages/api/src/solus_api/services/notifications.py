"""In-app notification creation (FND-05 seam). This is "the existing
notification path" other features wire into: rows land in the notifications
table and surface through /users/me/notifications. Email delivery, when it
arrives, hangs off the same rows — callers don't change."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Membership, Notification


def notify_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            body=body,
            payload=payload or {},
        )
    )


async def notify_team(
    session: AsyncSession,
    *,
    team_id: uuid.UUID,
    notification_type: str,
    title: str,
    exclude_user_id: uuid.UUID | None = None,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Notify every member of a team (minus the actor). Returns the count."""
    member_ids = (
        await session.scalars(select(Membership.user_id).where(Membership.team_id == team_id))
    ).all()
    recipients = [uid for uid in member_ids if uid != exclude_user_id]
    for uid in recipients:
        notify_user(
            session,
            user_id=uid,
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
        )
    return len(recipients)
