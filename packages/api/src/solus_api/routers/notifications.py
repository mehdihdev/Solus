"""§2.1 Notifications — cursor-paginated list, mark read, read-all."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep
from solus_api.models import Notification, utcnow
from solus_api.schemas import serialize_notification

router = APIRouter(prefix="/api/v1/users/me/notifications")


@router.get("")
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(Notification.created_at, Notification.id, cursor))
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_notification(n) for n in visible], meta=meta)


@router.post("/read-all")
async def read_all(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    unread = (
        await session.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
    ).all()
    now = utcnow()
    for notification in unread:
        notification.read_at = now
    await session.commit()
    return envelope({"updated": len(unread)})


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    notification = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if notification is None:
        raise APIError(404, "not_found", "Notification not found")
    if notification.read_at is None:
        notification.read_at = utcnow()
        await session.commit()
        await session.refresh(notification)
    return envelope(serialize_notification(notification))
