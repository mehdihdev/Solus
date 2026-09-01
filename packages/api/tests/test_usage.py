"""GET /users/me/usage — cycle-windowed credit usage (SOLUSDEV-233, API.md §2.14).

The meter is credit-denominated (ADR-018 rejected raw token metering): `used` is
the sum of USAGE debits inside the current cycle, `allowance` is the plan's
credit grant, `balance` is the cached balance. The cycle is the monthly
anniversary window anchored at the subscription's creation; without a
subscription it falls back to the UTC calendar month.
"""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.billing import credits
from solus_api.billing.usage import cycle_window
from solus_api.models import CreditLedger, CreditTxnType

# ------------------------------------------------------------ pure window math


def test_cycle_window_same_month() -> None:
    anchor = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    now = datetime(2026, 3, 25, tzinfo=UTC)
    start, end = cycle_window(anchor, now)
    assert start == anchor
    assert end == datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


def test_cycle_window_rolls_to_the_latest_anniversary() -> None:
    anchor = datetime(2026, 1, 10, tzinfo=UTC)
    now = datetime(2026, 8, 31, tzinfo=UTC)
    start, end = cycle_window(anchor, now)
    assert start == datetime(2026, 8, 10, tzinfo=UTC)
    assert end == datetime(2026, 9, 10, tzinfo=UTC)


def test_cycle_window_before_this_months_anniversary_uses_last_month() -> None:
    anchor = datetime(2026, 1, 20, tzinfo=UTC)
    now = datetime(2026, 8, 5, tzinfo=UTC)
    start, end = cycle_window(anchor, now)
    assert start == datetime(2026, 7, 20, tzinfo=UTC)
    assert end == datetime(2026, 8, 20, tzinfo=UTC)


def test_cycle_window_clamps_short_months() -> None:
    """A Jan-31 anchor bills on the clamped Feb 28 (Stripe-style convention)."""
    anchor = datetime(2026, 1, 31, tzinfo=UTC)
    # The day before the clamped anniversary: still the January cycle.
    start, end = cycle_window(anchor, datetime(2026, 2, 27, tzinfo=UTC))
    assert start == datetime(2026, 1, 31, tzinfo=UTC)
    assert end == datetime(2026, 2, 28, tzinfo=UTC)  # Feb 31 clamps to Feb 28
    # On the clamped anniversary the new cycle has begun.
    start, end = cycle_window(anchor, datetime(2026, 2, 28, 12, 0, tzinfo=UTC))
    assert start == datetime(2026, 2, 28, tzinfo=UTC)
    assert end == datetime(2026, 3, 31, tzinfo=UTC)


# ------------------------------------------------------------------ the route


async def test_usage_zero_before_any_spend(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/users/me/usage", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["used"] == 0
    assert data["balance"] >= 0
    assert data["cycle_start"] is not None


async def test_usage_counts_only_cycle_usage_debits(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    my = await me(client, alice_headers)
    user_id = uuid.UUID(my["id"])
    async with app.state.sessionmaker() as db:
        await credits.add_credits(
            db, user_id, 1000, CreditTxnType.PURCHASE, idempotency_key="u-buy-1"
        )
        await credits.debit_credits(db, user_id, 40, idempotency_key="u-call-1")
        await credits.debit_credits(db, user_id, 2, idempotency_key="u-call-2")

    resp = await client.get("/api/v1/users/me/usage", headers=alice_headers)
    data = resp.json()["data"]
    # Purchases/grants never count as usage; the two debits do.
    assert data["used"] == 42
    assert isinstance(data["balance"], int)


async def test_usage_excludes_spend_before_the_cycle(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    my = await me(client, alice_headers)
    user_id = uuid.UUID(my["id"])
    async with app.state.sessionmaker() as db:
        await credits.add_credits(
            db, user_id, 100, CreditTxnType.PURCHASE, idempotency_key="u-buy-2"
        )
        await credits.debit_credits(db, user_id, 10, idempotency_key="u-call-3")
        # An old usage row from a prior cycle, written directly.
        db.add(
            CreditLedger(
                user_id=user_id,
                amount=-77,
                type=CreditTxnType.USAGE,
                balance_after=0,
                idempotency_key="u-old-1",
                created_at=datetime.now(UTC) - timedelta(days=90),
            )
        )
        await db.commit()

    resp = await client.get("/api/v1/users/me/usage", headers=alice_headers)
    assert resp.json()["data"]["used"] == 10


async def test_usage_allowance_follows_the_plan(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/subscription", json={"plan": "pro"}, headers=alice_headers
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/users/me/usage", headers=alice_headers)
    data = resp.json()["data"]
    assert data["allowance"] == 10000  # settings.plan_credit_grants["pro"]


async def test_usage_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me/usage")
    assert resp.status_code == 401


async def test_usage_is_user_scoped(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
) -> None:
    """Cross-tenant isolation (§7): bob's ledger never leaks into alice's meter."""
    bob = await me(client, bob_headers)
    bob_id = uuid.UUID(bob["id"])
    async with app.state.sessionmaker() as db:
        await credits.add_credits(
            db, bob_id, 500, CreditTxnType.PURCHASE, idempotency_key="bob-buy-1"
        )
        await credits.debit_credits(db, bob_id, 123, idempotency_key="bob-call-1")

    resp = await client.get("/api/v1/users/me/usage", headers=alice_headers)
    data = resp.json()["data"]
    assert data["used"] == 0  # none of bob's 123 usage credits count for alice
    # Alice's balance is her own — exactly what her /credits route reports.
    own = await client.get("/api/v1/users/me/credits", headers=alice_headers)
    assert data["balance"] == own.json()["data"]["balance"]

    # And bob's own meter sees his spend, proving the seed took effect.
    resp = await client.get("/api/v1/users/me/usage", headers=bob_headers)
    assert resp.json()["data"]["used"] == 123
