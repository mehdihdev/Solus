"""§2.1 Notifications — list (cursor-paginated), mark read, read-all."""

import uuid
from datetime import UTC, datetime

from conftest import BOB, add_member, create_team, me
from httpx import AsyncClient
from solus_api.models import Membership, Notification, NotificationType
from solus_api.services.notifications import notify_team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_notifications(db: AsyncSession, user_id: str, count: int) -> list[Notification]:
    rows = [
        Notification(
            user_id=uuid.UUID(user_id),
            type=NotificationType.PROJECT_SHARED,
            title=f"Change {i}",
            attrs={"index": i},
        )
        for i in range(count)
    ]
    db.add_all(rows)
    await db.commit()
    return rows


async def test_list_notifications_cursor_pagination(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    await seed_notifications(db, user["id"], 3)

    resp = await client.get("/api/v1/users/me/notifications?limit=2", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["meta"]["has_next"] is True
    cursor = body["meta"]["next_cursor"]

    resp2 = await client.get(
        f"/api/v1/users/me/notifications?limit=2&cursor={cursor}", headers=alice_headers
    )
    body2 = resp2.json()
    assert len(body2["data"]) == 1
    assert body2["meta"]["has_next"] is False
    ids = {n["id"] for n in body["data"]} | {n["id"] for n in body2["data"]}
    assert len(ids) == 3


async def test_mark_notification_read(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    rows = await seed_notifications(db, user["id"], 1)

    resp = await client.post(
        f"/api/v1/users/me/notifications/{rows[0].id}/read", headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["read_at"] is not None


async def test_mark_read_is_user_scoped(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    alice = await me(client, alice_headers)
    await me(client, bob_headers)
    rows = await seed_notifications(db, alice["id"], 1)

    resp = await client.post(
        f"/api/v1/users/me/notifications/{rows[0].id}/read", headers=bob_headers
    )
    assert resp.status_code == 404


async def test_read_all(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    await seed_notifications(db, user["id"], 3)

    resp = await client.post("/api/v1/users/me/notifications/read-all", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["updated"] == 3

    listing = await client.get("/api/v1/users/me/notifications", headers=alice_headers)
    assert all(n["read_at"] is not None for n in listing.json()["data"])


async def test_invalid_cursor_rejected(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.get("/api/v1/users/me/notifications?cursor=%%%bogus", headers=alice_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_cursor"


async def test_notify_team_skips_soft_deleted_members(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """notify_team must not deliver to a removed (soft-deleted) member."""
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    team = await create_team(client, alice_headers, name="Notify Co")
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")

    # Bob is removed from the team — soft-delete his membership row.
    membership = await db.scalar(
        select(Membership).where(
            Membership.team_id == uuid.UUID(team["id"]),
            Membership.user_id == uuid.UUID(bob["id"]),
        )
    )
    assert membership is not None
    membership.deleted_at = datetime.now(UTC)
    await db.commit()

    count = await notify_team(
        db,
        team_id=uuid.UUID(team["id"]),
        notification_type=NotificationType.PROJECT_SHARED,
        title="Ping",
    )
    await db.commit()

    # Only alice (live owner) received the "Ping"; bob (soft-deleted) is skipped.
    # Filter by the unique title so the invite-accept notifications don't count.
    assert count == 1
    pings = (await db.scalars(select(Notification).where(Notification.title == "Ping"))).all()
    assert [n.user_id for n in pings] == [uuid.UUID(alice["id"])]
