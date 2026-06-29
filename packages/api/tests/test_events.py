"""ADR-011 data-collection events — consent-gated, emitted on meaningful actions."""

from conftest import create_team, me
from httpx import AsyncClient
from solus_api.models import DataEvent, User
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def count_events(db: AsyncSession) -> int:
    return (await db.scalar(select(func.count()).select_from(DataEvent))) or 0


async def test_no_events_without_consent(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    await create_team(client, alice_headers)
    assert await count_events(db) == 0


async def test_events_emitted_with_consent(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user = await me(client, alice_headers)
    import uuid

    await db.execute(
        update(User).where(User.id == uuid.UUID(user["id"])).values(data_collection_consent=True)
    )
    await db.commit()

    await create_team(client, alice_headers)
    assert await count_events(db) >= 1

    event = await db.scalar(select(DataEvent).limit(1))
    assert event is not None
    assert event.event_type == "team.created"
    assert event.user_id is not None
