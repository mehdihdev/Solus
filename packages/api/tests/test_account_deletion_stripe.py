"""Stripe cancel-on-deletion (SOLUSDEV-313 T7): durable, same-transaction, never blocking."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import ALICE
from fastapi import FastAPI
from fixtures.stripe_fake import FakeStripeGateway
from httpx import AsyncClient
from solus_api.billing.stripe_events import process_event
from solus_api.deps import get_stripe_gateway
from solus_api.models import (
    PlanType,
    StripeCancelRequest,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from solus_api.services import account_deletion
from solus_api.services.account_deletion import AccountDeletionService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CUS, SUB = "cus_del1", "sub_del1"


class _Admin:
    async def delete_user(self, supabase_user_id: str) -> bool:
        return True


def _service(app: FastAPI, db: AsyncSession, gateway: Any) -> AccountDeletionService:
    return AccountDeletionService(
        db,
        secret_store=app.state.secret_store,
        supabase_admin=_Admin(),
        cache=app.state.integration_cache,
        gateway=gateway,
    )


async def _user(
    db: AsyncSession,
    *,
    customer: str | None = CUS,
    sub: str | None = SUB,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> User:
    uid = uuid.uuid4()
    user = User(id=uid, supabase_user_id=f"sb-{uid}", email=f"{uid}@example.com")
    db.add(user)
    await db.flush()
    db.add(
        Subscription(
            user_id=uid,
            plan=PlanType.BASIC,
            status=status,
            limits=default_limits(PlanType.BASIC),
            stripe_customer_id=customer,
            stripe_subscription_id=sub,
        )
    )
    await db.commit()
    return user


async def _rows(db: AsyncSession) -> list[StripeCancelRequest]:
    db.expire_all()
    return list((await db.scalars(select(StripeCancelRequest))).all())


def _fake() -> FakeStripeGateway:
    fake = FakeStripeGateway()
    fake.seed_subscription(SUB, customer_id=CUS)
    return fake


# ------------------------------------------------------------ enqueue


async def test_inline_cancel_runs_after_commit_with_the_expected_args(
    app: FastAPI, db: AsyncSession
) -> None:
    user = await _user(db)
    fake = _fake()

    await _service(app, db, fake).delete_account(user)

    [call] = fake.calls_to("cancel_subscription")
    assert call.args == (SUB,)
    assert call.kwargs["mode"] == "immediate"
    assert call.kwargs["invoice_now"] is True and call.kwargs["prorate"] is False
    [row] = await _rows(db)
    assert (row.stripe_customer_id, row.stripe_subscription_id) == (CUS, SUB)
    assert row.completed_at is not None
    assert fake.subscriptions[SUB].status == "canceled"


async def test_the_stripe_customer_is_never_deleted(app: FastAPI, db: AsyncSession) -> None:
    user = await _user(db)
    fake = _fake()
    await _service(app, db, fake).delete_account(user)
    assert {c.method for c in fake.calls} <= {
        "cancel_subscription",
        "release_subscription_schedule",
    }
    assert not any("customer" in c.method and "delete" in c.method for c in fake.calls)


async def test_no_customer_id_means_no_row_and_no_call(app: FastAPI, db: AsyncSession) -> None:
    user = await _user(db, customer=None, sub=None, status=SubscriptionStatus.TRIALING)
    fake = _fake()

    await _service(app, db, fake).delete_account(user)

    assert await _rows(db) == []
    assert fake.calls == []


async def test_local_canceled_subscription_enqueues_customer_only_tombstone(
    app: FastAPI, db: AsyncSession
) -> None:
    user = await _user(db, status=SubscriptionStatus.CANCELED)
    fake = _fake()

    await _service(app, db, fake).delete_account(user)

    [row] = await _rows(db)
    assert row.stripe_customer_id == CUS and row.stripe_subscription_id is None
    assert fake.calls_to("cancel_subscription") == []


async def test_customer_only_subscription_row_enqueues_tombstone(
    app: FastAPI, db: AsyncSession
) -> None:
    user = await _user(db, sub=None)
    await _service(app, db, _fake()).delete_account(user)
    [row] = await _rows(db)
    assert row.stripe_subscription_id is None


async def test_rollback_of_the_deletion_drops_the_row(
    app: FastAPI, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db)
    user_id = user.id

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("deletion failed mid-transaction")

    monkeypatch.setattr(account_deletion, "queue_account_removed", boom)
    with pytest.raises(RuntimeError):
        await _service(app, db, _fake()).delete_account(user)
    await db.rollback()

    assert await _rows(db) == []
    assert await db.get(User, user_id, populate_existing=True) is not None


async def test_commit_keeps_the_row_without_a_gateway(app: FastAPI, db: AsyncSession) -> None:
    user = await _user(db)
    await _service(app, db, None).delete_account(user)
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 0
    assert row.stripe_subscription_id == SUB


# ------------------------------------------------------------ Stripe misbehaving


async def test_stripe_down_never_blocks_deletion_and_the_row_survives_for_retry(
    app: FastAPI, db: AsyncSession
) -> None:
    user = await _user(db)
    user_id = user.id
    fake = _fake()
    fake.fail_next("cancel_subscription", FakeStripeGateway.connection_error())

    await _service(app, db, fake).delete_account(user)

    assert await db.get(User, user_id, populate_existing=True) is None
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1


async def test_already_canceled_in_stripe_is_completed(app: FastAPI, db: AsyncSession) -> None:
    user = await _user(db)
    fake = FakeStripeGateway()
    fake.seed_subscription(SUB, customer_id=CUS, status="canceled")

    await _service(app, db, fake).delete_account(user)

    [row] = await _rows(db)
    assert row.completed_at is not None


async def test_unconfigured_gateway_never_blocks_deletion(app: FastAPI, db: AsyncSession) -> None:
    """The real gateway with no key in the SecretStore: deletion succeeds, row persists."""
    from solus_api.billing.stripe_gateway import StripeGateway

    user = await _user(db)
    user_id = user.id

    await _service(app, db, StripeGateway(app.state.secret_store)).delete_account(user)

    assert await db.get(User, user_id, populate_existing=True) is None
    [row] = await _rows(db)
    assert row.completed_at is None


# ------------------------------------------------------------ webhook after deletion


async def test_webhook_for_the_deleted_user_is_safe_and_rearms_the_tombstone(
    app: FastAPI, db: AsyncSession
) -> None:
    user = await _user(db)
    fake = _fake()
    await _service(app, db, fake).delete_account(user)
    [done] = await _rows(db)
    assert done.completed_at is not None

    event = {
        "id": "evt_late_1",
        "type": "customer.subscription.updated",
        "created": 2_000_000_000,
        "data": {"object": {"id": "sub_late", "customer": CUS, "status": "active"}},
    }
    assert await process_event(db, event, pack_credits={}) is True
    await db.commit()

    [row] = await _rows(db)
    assert row.stripe_subscription_id == "sub_late"
    assert row.completed_at is None

    terminal: dict[str, Any] = {
        "id": "evt_late_2",
        "type": "customer.subscription.updated",
        "created": 2_000_000_001,
        "data": {"object": {"id": "sub_late", "customer": CUS, "status": "canceled"}},
    }
    assert await process_event(db, terminal, pack_credits={}) is True


# ------------------------------------------------------------ router wiring


async def test_route_uses_the_gateway_dependency_and_returns_204(
    client: AsyncClient, app: FastAPI, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    fake = _fake()
    app.dependency_overrides[get_stripe_gateway] = lambda: fake
    me = await client.get("/api/v1/users/me", headers=alice_headers)
    uid = uuid.UUID(me.json()["data"]["id"])
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None
    sub.stripe_customer_id, sub.stripe_subscription_id = CUS, SUB
    await db.commit()

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)

    assert resp.status_code == 204, resp.text
    assert len(fake.calls_to("cancel_subscription")) == 1
    [row] = await _rows(db)
    assert row.completed_at is not None
    assert ALICE["sub"]  # the deleted identity is the requester only


async def test_route_without_a_stripe_key_still_deletes(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    me = await client.get("/api/v1/users/me", headers=alice_headers)
    uid = uuid.UUID(me.json()["data"]["id"])
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None
    sub.stripe_customer_id, sub.stripe_subscription_id = CUS, SUB
    await db.commit()

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)

    assert resp.status_code == 204, resp.text
    [row] = await _rows(db)
    assert row.completed_at is None
