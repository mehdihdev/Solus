"""Stripe webhook: signature, dedupe, reconciliation of out-of-order events,
credit-pack grant, payment-failed (SOLUSDEV-83 / SOLUS-FND-03)."""

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from conftest import bearer
from httpx import AsyncClient
from solus_api.billing import stripe_events
from solus_api.billing.stripe_events import process_event
from solus_api.models import (
    CreditBalance,
    Notification,
    NotificationType,
    ProcessedStripeEvent,
    Subscription,
    SubscriptionStatus,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

WEBHOOK_SECRET = "whsec_test"  # noqa: S105 - test-only

API_DIR = Path(__file__).resolve().parent.parent


def _test_db_url() -> str:
    return str(os.environ["SOLUS_DATABASE_URL"])


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
        db,
        _pack_checkout("evt_unpaid", user_id, payment_status="unpaid"),
        pack_credits={"price_small": 500},
    )
    bal = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_id))
    assert bal == 1000  # trial only; unsettled payment grants nothing


async def test_checkout_for_unknown_user_is_noop(client: AsyncClient, db: AsyncSession) -> None:
    ghost = uuid.uuid4()
    processed = await process_event(
        db,
        _pack_checkout("evt_ghost", ghost, payment_status="paid"),
        pack_credits={"price_small": 500},
    )
    assert processed is True  # recorded, but no crash / no grant
    bal = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == ghost))
    assert bal is None


async def test_webhook_isolation_between_users(client: AsyncClient, db: AsyncSession) -> None:
    user_a = await _provision(client, "a-billing@example.com")
    user_b = await _provision(client, "b-billing@example.com")
    await process_event(
        db,
        _pack_checkout("evt_b_pack", user_b, payment_status="paid"),
        pack_credits={"price_small": 500},
    )
    bal_b = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_b))
    bal_a = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user_a))
    assert bal_b == 1500  # B credited
    assert bal_a == 1000  # A untouched


async def test_subscription_event_derives_plan_and_limits_from_price(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Entitlement follows what was purchased: a subscription event carrying a
    Stripe Price that maps to PRO sets the local plan + limits from that price,
    never from any client-supplied plan name (SOLUSDEV-83 follow-up)."""
    user_id = await _provision(client, "plan-derive@example.com")
    sub = await _subscription(db, user_id)
    sub.stripe_customer_id = "cus_derive"  # let the webhook match this local sub
    await db.commit()

    event = {
        "id": "evt_plan_derive",
        "type": "customer.subscription.updated",
        "created": 5000,
        "data": {
            "object": {
                "id": "sub_derive",
                "customer": "cus_derive",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_pro_year"}}]},
            }
        },
    }
    processed = await process_event(
        db, event, pack_credits={}, plan_prices={"pro:year": "price_pro_year"}
    )
    assert processed is True
    await db.refresh(sub)
    assert sub.plan.value == "pro"
    assert sub.status is SubscriptionStatus.ACTIVE
    # PRO is unlimited — its limits map to None (ADR-023).
    assert sub.limits.get("max_projects") is None


async def test_subscription_event_with_unknown_price_leaves_plan(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client, "plan-unknown@example.com")
    sub = await _subscription(db, user_id)
    original_plan = sub.plan.value
    sub.stripe_customer_id = "cus_unknown"
    await db.commit()

    event = {
        "id": "evt_plan_unknown",
        "type": "customer.subscription.updated",
        "created": 5000,
        "data": {
            "object": {
                "id": "sub_unknown",
                "customer": "cus_unknown",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_not_mapped"}}]},
            }
        },
    }
    await process_event(db, event, pack_credits={}, plan_prices={"pro:year": "price_pro_year"})
    await db.refresh(sub)
    assert sub.plan.value == original_plan  # unchanged when the price isn't ours


# --- success notifications (in-app confirmation via the existing notif system) ----


async def _payment_succeeded_notes(db: AsyncSession, user_id: uuid.UUID) -> list[Notification]:
    rows = await db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == NotificationType.PAYMENT_SUCCEEDED,
        )
    )
    return list(rows)


def _pro_sub_event(
    event_id: str, *, customer: str, created: int, status: str = "active"
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "customer.subscription.updated",
        "created": created,
        "data": {
            "object": {
                "id": "sub_notify",
                "customer": customer,
                "status": status,
                "items": {"data": [{"price": {"id": "price_pro_month"}}]},
            }
        },
    }


PRO_PRICES = {"pro:month": "price_pro_month"}


async def test_subscription_activation_notifies_payment_succeeded(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client, "notify-activate@example.com")
    sub = await _subscription(db, user_id)
    sub.stripe_customer_id = "cus_notify"
    await db.commit()

    await process_event(
        db,
        _pro_sub_event("evt_n1", customer="cus_notify", created=100),
        pack_credits={},
        plan_prices=PRO_PRICES,
    )
    notes = await _payment_succeeded_notes(db, user_id)
    assert len(notes) == 1
    assert "Pro" in (notes[0].body or "")
    assert notes[0].attrs.get("plan") == "pro"


async def test_renewal_without_change_does_not_notify_again(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client, "notify-renewal@example.com")
    sub = await _subscription(db, user_id)
    sub.stripe_customer_id = "cus_renewal"
    await db.commit()

    await process_event(
        db,
        _pro_sub_event("evt_r1", customer="cus_renewal", created=100),
        pack_credits={},
        plan_prices=PRO_PRICES,
    )
    # Same plan, same status, later event — a routine renewal must stay silent.
    await process_event(
        db,
        _pro_sub_event("evt_r2", customer="cus_renewal", created=200),
        pack_credits={},
        plan_prices=PRO_PRICES,
    )
    notes = await _payment_succeeded_notes(db, user_id)
    assert len(notes) == 1  # only the original activation


async def test_credit_pack_grant_notifies_with_amount(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client, "notify-pack@example.com")
    await process_event(
        db,
        _pack_checkout("evt_n_pack", user_id, payment_status="paid"),
        pack_credits={"price_small": 500},
    )
    notes = await _payment_succeeded_notes(db, user_id)
    assert len(notes) == 1
    assert notes[0].attrs.get("credits") == 500
    assert "500" in (notes[0].body or "")


async def test_unpaid_checkout_does_not_notify(client: AsyncClient, db: AsyncSession) -> None:
    user_id = await _provision(client, "notify-unpaid@example.com")
    await process_event(
        db,
        _pack_checkout("evt_n_unpaid", user_id, payment_status="unpaid"),
        pack_credits={"price_small": 500},
    )
    assert await _payment_succeeded_notes(db, user_id) == []


async def test_cancellation_does_not_notify_payment_succeeded(
    client: AsyncClient, db: AsyncSession
) -> None:
    user_id = await _provision(client, "notify-cancel@example.com")
    sub = await _subscription(db, user_id)
    sub.stripe_customer_id = "cus_cancel_n"
    await db.commit()
    await process_event(
        db,
        _sub_event(
            "evt_n_del",
            "customer.subscription.deleted",
            sub_id="sub_cn",
            customer="cus_cancel_n",
            status="canceled",
            created=300,
        ),
        pack_credits={},
    )
    assert await _payment_succeeded_notes(db, user_id) == []


async def test_oversized_body_rejected(client: AsyncClient) -> None:
    # 300 KB exceeds the default 256 KB cap; rejected before signature checks.
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=b"x" * 300_000,
        headers={"stripe-signature": "t=1,v1=x", "content-type": "application/json"},
    )
    assert resp.status_code == 413


# --- IntegrityError handling: only the dedupe race is swallowed (sec review H1) ----


def _integrity_error(
    *, sqlstate: str | None, constraint: str | None, message: str = "boom"
) -> IntegrityError:
    orig = SimpleNamespace(sqlstate=sqlstate, constraint_name=constraint)
    return IntegrityError(message, params=None, orig=orig)  # type: ignore[arg-type]


def test_duplicate_race_detector_accepts_only_the_event_id_unique_violation() -> None:
    race = _integrity_error(
        sqlstate="23505", constraint="ix_processed_stripe_events_stripe_event_id"
    )
    assert stripe_events._is_duplicate_event_race(race)
    check_violation = _integrity_error(sqlstate="23514", constraint="notificationtype")
    assert not stripe_events._is_duplicate_event_race(check_violation)
    other_unique = _integrity_error(sqlstate="23505", constraint="uq_something_else")
    assert not stripe_events._is_duplicate_event_race(other_unique)
    # Fallback when the driver exposes no fields: match on the rendered message.
    by_message = _integrity_error(
        sqlstate=None,
        constraint=None,
        message="duplicate key value violates unique constraint "
        '"ix_processed_stripe_events_stripe_event_id"',
    )
    assert stripe_events._is_duplicate_event_race(by_message)


def _no_match_sub_event(event_id: str) -> dict[str, Any]:
    """A subscription event with no local match: the handler is a no-op, so the
    only commit is process_event's final one — the exact seam under test."""
    return _sub_event(
        event_id,
        "customer.subscription.updated",
        sub_id="sub_ghost",
        customer="cus_ghost",
        status="active",
        created=100,
    )


async def test_unexpected_integrity_error_at_commit_propagates_so_stripe_retries(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A schema running behind the code (e.g. an unapplied CHECK migration) must
    surface as an error — never be reported as a duplicate delivery — so the
    webhook 5xxs and Stripe redelivers the event."""

    async def check_violation_commit() -> None:
        raise _integrity_error(sqlstate="23514", constraint="notificationtype")

    monkeypatch.setattr(db, "commit", check_violation_commit)
    with pytest.raises(IntegrityError):
        await process_event(db, _no_match_sub_event("evt_check_violation"), pack_credits={})
    monkeypatch.undo()
    await db.rollback()
    # Not recorded as processed — a redelivery will be attempted, not deduped.
    seen = await db.scalar(
        select(ProcessedStripeEvent.id).where(
            ProcessedStripeEvent.stripe_event_id == "evt_check_violation"
        )
    )
    assert seen is None


async def test_duplicate_event_race_at_commit_still_reports_duplicate(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def racing_commit() -> None:
        raise _integrity_error(
            sqlstate="23505", constraint="ix_processed_stripe_events_stripe_event_id"
        )

    monkeypatch.setattr(db, "commit", racing_commit)
    processed = await process_event(db, _no_match_sub_event("evt_commit_race"), pack_credits={})
    assert processed is False  # benign concurrent delivery, no raise


# --- migration 1827bb0b37b6 reverses and reapplies cleanly --------------------------


def _notification_check_values() -> str:
    async def check() -> str:
        conn = await asyncpg.connect(_test_db_url().replace("+asyncpg", ""))
        try:
            return str(
                await conn.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'notificationtype'"
                )
            )
        finally:
            await conn.close()

    return asyncio.run(check())


def test_payment_succeeded_migration_downgrade_and_reupgrade() -> None:
    """1827bb0b37b6 reverses cleanly (removing payment.succeeded rows + narrowing
    the CHECK) and reapplies. Restores head in finally so a mid-test failure
    cannot poison the rest of the session."""
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    try:
        # Direct parent (SOLUSDEV-136's HNSW migration) — reverses only ours.
        command.downgrade(cfg, "e3a1c8f27b54")
        assert "payment.succeeded" not in _notification_check_values()
    finally:
        command.upgrade(cfg, "head")
    assert "payment.succeeded" in _notification_check_values()
