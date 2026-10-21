"""Webhook writes billing_interval / current_period_end / expires_at (SOLUSDEV-236)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from solus_api.billing.stripe_events import process_event
from solus_api.models import Subscription, SubscriptionStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_billing_webhook import _provision, _subscription

PRICES = {"pro:month": "price_pm", "pro:year": "price_py"}


def _dt(secs: int) -> datetime:
    return datetime.fromtimestamp(secs, tz=UTC)


def _event(
    event_id: str,
    created: int,
    *,
    etype: str = "customer.subscription.updated",
    status: str = "active",
    price: str = "price_pm",
    period_end: int | None = 1_900_000_000,
    trial_end: int | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"price": {"id": price}}
    if period_end is not None:
        item["current_period_end"] = period_end
    obj: dict[str, Any] = {
        "id": "sub_1",
        "customer": "cus_1",
        "status": status,
        "items": {"data": [item]},
    }
    if trial_end is not None:
        obj["trial_end"] = trial_end
    return {
        "id": event_id,
        "type": etype,
        "created": created,
        "data": {"object": obj},
    }


async def _linked(client: AsyncClient, db: AsyncSession) -> uuid.UUID:
    user_id = await _provision(client, "period@example.com")
    await process_event(
        db,
        {
            "id": "evt_link",
            "type": "checkout.session.completed",
            "created": 100,
            "data": {
                "object": {
                    "mode": "subscription",
                    "client_reference_id": str(user_id),
                    "customer": "cus_1",
                    "subscription": "sub_1",
                }
            },
        },
        pack_credits={},
    )
    return user_id


async def _apply(db: AsyncSession, event: dict[str, Any]) -> None:
    await process_event(db, event, pack_credits={}, plan_prices=PRICES)


async def _fresh(db: AsyncSession, user_id: uuid.UUID) -> Subscription:
    db.expire_all()
    return await _subscription(db, user_id)


async def test_trialing_event_writes_trial_end_interval_and_period_end(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _linked(client, db)
    await _apply(
        db,
        _event("e1", 200, status="trialing", trial_end=1_700_000_000, period_end=1_900_000_000),
    )
    sub = await _fresh(db, user_id)
    assert sub.status is SubscriptionStatus.TRIALING
    assert sub.expires_at == _dt(1_700_000_000)
    assert sub.billing_interval == "month"
    assert sub.current_period_end == _dt(1_900_000_000)


async def test_active_update_monthly_to_yearly_changes_interval(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _linked(client, db)
    await _apply(db, _event("e1", 200))
    assert (await _fresh(db, user_id)).billing_interval == "month"
    await _apply(db, _event("e2", 300, price="price_py", period_end=1_950_000_000))
    sub = await _fresh(db, user_id)
    assert sub.billing_interval == "year"
    assert sub.current_period_end == _dt(1_950_000_000)
    assert sub.expires_at == _dt(1_950_000_000)


async def test_out_of_order_older_event_is_ignored(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _linked(client, db)
    await _apply(db, _event("e1", 300, price="price_py", period_end=1_950_000_000))
    await _apply(db, _event("e0", 200, price="price_pm", period_end=1_800_000_000))
    sub = await _fresh(db, user_id)
    assert sub.billing_interval == "year"
    assert sub.current_period_end == _dt(1_950_000_000)


async def test_deleted_event_leaves_interval_period_and_expires_unchanged(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _linked(client, db)
    await _apply(db, _event("e1", 200))
    await _apply(
        db,
        _event(
            "e2",
            300,
            etype="customer.subscription.deleted",
            status="canceled",
            price="price_py",
            period_end=2_000_000_000,
        ),
    )
    sub = await _fresh(db, user_id)
    assert sub.status is SubscriptionStatus.CANCELED
    assert sub.billing_interval == "month"
    assert sub.current_period_end == _dt(1_900_000_000)
    assert sub.expires_at == _dt(1_900_000_000)


async def test_existing_expires_at_kept_when_stripe_gives_none(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _linked(client, db)
    local = await _subscription(db, user_id)
    local.expires_at = _dt(1_600_000_000)
    await db.commit()
    await _apply(db, _event("e1", 200, period_end=None))
    sub = await _fresh(db, user_id)
    assert sub.expires_at == _dt(1_600_000_000)
    assert sub.current_period_end is None
    assert sub.billing_interval == "month"


async def test_subscription_row_still_unique_after_events(
    client: AsyncClient, db: AsyncSession
) -> None:
    await _linked(client, db)
    await _apply(db, _event("e1", 200))
    rows = (await db.scalars(select(Subscription))).all()
    assert len(rows) == 1
