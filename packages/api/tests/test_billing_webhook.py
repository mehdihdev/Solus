"""Stripe webhook: signature, dedupe, reconciliation of out-of-order events,
credit-pack grant, payment-failed (SOLUSDEV-83 / SOLUS-FND-03)."""

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from conftest import bearer
from httpx import AsyncClient
from solus_api.billing.stripe_events import process_event
from solus_api.models import (
    CreditBalance,
    Notification,
    NotificationType,
    Subscription,
    SubscriptionStatus,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

WEBHOOK_SECRET = "whsec_test"  # noqa: S105 - test-only


async def _provision(client: AsyncClient, email: str = "billing@example.com") -> uuid.UUID:
    resp = await client.get("/api/v1/users/me", headers=bearer(f"sub-{email}", email))
    assert resp.status_code == 200
    return uuid.UUID(resp.json()["data"]["id"])


async def _subscription(session: AsyncSession, user_id: uuid.UUID) -> Subscription:
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    assert sub is not None
    return sub


def _sub_event(
    event_id: str, etype: str, *, sub_id: str, customer: str, status: str, created: int
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": etype,
        "created": created,
        "data": {"object": {"id": sub_id, "customer": customer, "status": status}},
    }


# --- dedupe + subscription reconciliation ---------------------------------


async def test_duplicate_event_is_noop(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _provision(client)
    ev = {
        "id": "evt_dup",
        "type": "checkout.session.completed",
        "created": 100,
        "data": {
            "object": {
                "mode": "payment",
                "payment_status": "paid",
                "client_reference_id": str(user_id),
                "metadata": {"price_id": "price_small"},
            }
        },
    }
    first = await process_event(db, ev, pack_credits={"price_small": 500})
    second = await process_event(db, ev, pack_credits={"price_small": 500})
    assert first is True
    assert second is False  # deduped
    bal = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_id))
    assert bal == 1500  # 1000 trial grant + 500 pack, granted exactly once


async def test_subscription_events_reconcile_out_of_order(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client)
    # Link a Stripe customer to this user via a subscription-mode checkout.
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
    # Newer event: active at T=200.
    await process_event(
        db,
        _sub_event(
            "evt_a",
            "customer.subscription.updated",
            sub_id="sub_1",
            customer="cus_1",
            status="active",
            created=200,
        ),
        pack_credits={},
    )
    # Older, out-of-order event: past_due at T=150 — must NOT override the newer state.
    await process_event(
        db,
        _sub_event(
            "evt_b",
            "customer.subscription.updated",
            sub_id="sub_1",
            customer="cus_1",
            status="past_due",
            created=150,
        ),
        pack_credits={},
    )
    db.expunge_all()
    sub = await _subscription(db, user_id)
    assert sub.status is SubscriptionStatus.ACTIVE
    assert sub.stripe_customer_id == "cus_1"


async def test_subscription_deleted_marks_canceled(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _provision(client)
    await process_event(
        db,
        {
            "id": "evt_link2",
            "type": "checkout.session.completed",
            "created": 100,
            "data": {
                "object": {
                    "mode": "subscription",
                    "client_reference_id": str(user_id),
                    "customer": "cus_2",
                    "subscription": "sub_2",
                }
            },
        },
        pack_credits={},
    )
    await process_event(
        db,
        _sub_event(
            "evt_del",
            "customer.subscription.deleted",
            sub_id="sub_2",
            customer="cus_2",
            status="canceled",
            created=300,
        ),
        pack_credits={},
    )
    db.expunge_all()
    sub = await _subscription(db, user_id)
    assert sub.status is SubscriptionStatus.CANCELED


async def test_credit_pack_grants_configured_credits(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _provision(client)
    await process_event(
        db,
        {
            "id": "evt_pack",
            "type": "checkout.session.completed",
            "created": 100,
            "data": {
                "object": {
                    "mode": "payment",
                    "payment_status": "paid",
                    "client_reference_id": str(user_id),
                    "metadata": {"price_id": "price_big"},
                }
            },
        },
        pack_credits={"price_big": 5000},
    )
    bal = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_id))
    assert bal == 6000  # 1000 trial grant + 5000 pack


async def test_invoice_payment_failed_marks_past_due_and_notifies(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client)
    await process_event(
        db,
        {
            "id": "evt_link3",
            "type": "checkout.session.completed",
            "created": 100,
            "data": {
                "object": {
                    "mode": "subscription",
                    "client_reference_id": str(user_id),
                    "customer": "cus_3",
                    "subscription": "sub_3",
                }
            },
        },
        pack_credits={},
    )
    await process_event(
        db,
        {
            "id": "evt_fail",
            "type": "invoice.payment_failed",
            "created": 400,
            "data": {"object": {"id": "in_1", "customer": "cus_3"}},
        },
        pack_credits={},
    )
    db.expunge_all()
    sub = await _subscription(db, user_id)
    assert sub.status is SubscriptionStatus.PAST_DUE
    note = await db.scalar(
        select(Notification).where(
            Notification.user_id == user_id, Notification.type == NotificationType.PAYMENT_FAILED
        )
    )
    assert note is not None


# --- endpoint signature handling ------------------------------------------


def _sign(payload: bytes, secret: str, ts: int) -> str:
    signed = f"{ts}.{payload.decode()}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


async def test_webhook_rejects_bad_signature(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt","type":"x"}',
        headers={"stripe-signature": "t=1,v1=deadbeef", "content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_signature"


async def test_webhook_accepts_valid_signature(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _provision(client)
    payload = json.dumps(
        {
            "id": "evt_http",
            "object": "event",
            "type": "checkout.session.completed",
            "created": 100,
            "data": {
                "object": {
                    "mode": "payment",
                    "payment_status": "paid",
                    "client_reference_id": str(user_id),
                    "metadata": {"price_id": "price_small"},
                }
            },
        }
    ).encode()
    ts = int(time.time())
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=payload,
        headers={
            "stripe-signature": _sign(payload, WEBHOOK_SECRET, ts),
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["processed"] is True


# --- security-review coverage (H1 payment gating, H2 isolation, M1 size) ----


def _pack_checkout(event_id: str, user_id: uuid.UUID, *, payment_status: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "created": 100,
        "data": {
            "object": {
                "mode": "payment",
                "payment_status": payment_status,
                "client_reference_id": str(user_id),
                "metadata": {"price_id": "price_small"},
            }
        },
    }


async def test_unpaid_checkout_does_not_grant(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _provision(client)
    await process_event(
        db, _pack_checkout("evt_unpaid", user_id, payment_status="unpaid"),
        pack_credits={"price_small": 500},
    )
    bal = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_id))
    assert bal == 1000  # trial only; unsettled payment grants nothing


async def test_checkout_for_unknown_user_is_noop(client: AsyncClient, db: AsyncSession) -> None:
    ghost = uuid.uuid4()
    processed = await process_event(
        db, _pack_checkout("evt_ghost", ghost, payment_status="paid"),
        pack_credits={"price_small": 500},
    )
    assert processed is True  # recorded, but no crash / no grant
    bal = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == ghost))
    assert bal is None


async def test_webhook_isolation_between_users(client: AsyncClient, db: AsyncSession) -> None:
    user_a = await _provision(client, "a-billing@example.com")
    user_b = await _provision(client, "b-billing@example.com")
    await process_event(
        db, _pack_checkout("evt_b_pack", user_b, payment_status="paid"),
        pack_credits={"price_small": 500},
    )
    bal_b = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_b))
    bal_a = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_a))
    assert bal_b == 1500  # B credited
    assert bal_a == 1000  # A untouched


async def test_oversized_body_rejected(client: AsyncClient) -> None:
    # 300 KB exceeds the default 256 KB cap; rejected before signature checks.
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=b"x" * 300_000,
        headers={"stripe-signature": "t=1,v1=x", "content-type": "application/json"},
    )
    assert resp.status_code == 413
