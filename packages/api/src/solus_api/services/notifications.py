"""In-app notification creation (FND-05 seam). This is "the existing
notification path" other features wire into: rows land in the notifications
table and surface through /users/me/notifications. Email delivery, when it
arrives, hangs off the same rows — callers don't change."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Membership, Notification, NotificationType


def notify_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    notification_type: NotificationType | str,
    title: str,
    body: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> None:
    session.add(
        Notification(
            user_id=user_id,
            # Validate at the seam: an unknown type string fails loudly here,
            # not as an unreadable row at query time.
            type=NotificationType(notification_type),
            title=title,
            body=body,
            attrs=attrs or {},
        )
    )


async def notify_team(
    session: AsyncSession,
    *,
    team_id: uuid.UUID,
    notification_type: NotificationType | str,
    title: str,
    exclude_user_id: uuid.UUID | None = None,
    body: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> int:
    """Notify every member of a team (minus the actor). Returns the count."""
    member_ids = (
        await session.scalars(
            select(Membership.user_id).where(
                Membership.team_id == team_id,
                # Live members only — a removed/soft-deleted member must not keep
                # receiving the team's notifications (matches deps.live_membership).
                Membership.deleted_at.is_(None),
            )
        )
    ).all()
    recipients = [uid for uid in member_ids if uid != exclude_user_id]
    for uid in recipients:
        notify_user(
            session,
            user_id=uid,
            notification_type=notification_type,
            title=title,
            body=body,
            attrs=attrs,
        )
    return len(recipients)
