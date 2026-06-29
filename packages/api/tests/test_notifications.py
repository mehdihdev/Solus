"""§2.1 Notifications — list (cursor-paginated), mark read, read-all."""

import uuid

from conftest import me
from httpx import AsyncClient
from solus_api.models import Notification
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_notifications(db: AsyncSession, user_id: str, count: int) -> list[Notification]:
    rows = [
        Notification(
            user_id=uuid.UUID(user_id),
            type="cross_domain_change",
            title=f"Change {i}",
            payload={"index": i},
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
