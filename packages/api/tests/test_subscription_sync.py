"""SOLUSDEV-236 T3: hourly Stripe subscription reconciliation (API-implementation.md §10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from solus_api.billing import subscription_sync
from solus_api.billing.stripe_events import process_event
from solus_api.billing.stripe_gateway import (
    BillingUnconfiguredError,
    StripeOperationError,
    StripeResourceMissingError,
)
from solus_api.billing.subscription_sync import (
    RECONCILE_EVENT,
    reconcile_stripe_subscriptions,
    reconcile_subscriptions,
)
from solus_api.core.config import Settings
from solus_api.models import (
    DataEvent,
    Notification,
    NotificationType,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
PRICES = {"basic:month": "price_bm", "pro:month": "price_pm", "pro:year": "price_py"}
PERIOD_END = 1_900_000_000
Maker = async_sessionmaker[AsyncSession]


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret="test-only",
        stripe_plan_prices=PRICES,
    )


class _Gateway:
    """Test-local stand-in: per-subscription raw dict, or an Exception to raise."""

    def __init__(self) -> None:
        self.subs: dict[str, dict[str, Any] | Exception] = {}
        self.customers: dict[str, bool | Exception] = {}
        self.configured = True
        self.calls: list[str] = []

    async def ensure_configured(self) -> None:
        if not self.configured:
            raise BillingUnconfiguredError("no key")

    async def retrieve_subscription_raw(self, sub_id: str) -> dict[str, Any]:
        self.calls.append(sub_id)
        out = self.subs.get(sub_id, StripeResourceMissingError("subscription.retrieve"))
        if isinstance(out, Exception):
            raise out
        return out

    async def customer_exists(self, customer_id: str) -> bool:
        out = self.customers.get(customer_id, True)
        if isinstance(out, Exception):
            raise out
        return out


def _raw(
    sub_id: str,
    *,
    status: str = "active",
    price: str = "price_pm",
    period_end: int = PERIOD_END,
    cancel_at: int | None = None,
) -> dict[str, Any]:
    return {
        "id": sub_id,
        "customer": "cus_" + sub_id[4:],
        "status": status,
        "cancel_at": cancel_at,
        "items": {"data": [{"price": {"id": price}, "current_period_end": period_end}]},
    }


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(
    maker: Maker,
    tag: str = "A",
    *,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    plan: PlanType = PlanType.PRO,
    interval: str | None = "month",
    period_end: int = PERIOD_END,
    linked: bool = True,
    deleted: bool = False,
    consent: bool = True,
    updated_at: datetime | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    async with maker() as s:
        s.add(
            User(
                id=uid,
                supabase_user_id=f"x-{uid}",
                email=f"{uid}@example.com",
                data_collection_consent=consent,
            )
        )
        await s.flush()
        s.add(
            Subscription(
                user_id=uid,
                plan=plan,
                status=status,
                limits=default_limits(plan),
                billing_interval=interval,
                current_period_end=datetime.fromtimestamp(period_end, tz=UTC),
                expires_at=datetime.fromtimestamp(period_end, tz=UTC),
                stripe_customer_id=f"cus_{tag}" if linked else None,
                stripe_subscription_id=f"sub_{tag}" if linked else None,
                deleted_at=NOW if deleted else None,
            )
        )
        await s.commit()
    return uid


async def _sub(maker: Maker, uid: uuid.UUID) -> Subscription:
    async with maker() as s:
        row = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert row is not None
    return row


async def _events(maker: Maker) -> list[DataEvent]:
    async with maker() as s:
        return list(
            await s.scalars(select(DataEvent).where(DataEvent.event_type == RECONCILE_EVENT))
        )


async def _notes(maker: Maker, uid: uuid.UUID) -> list[Notification]:
    async with maker() as s:
        return list(await s.scalars(select(Notification).where(Notification.user_id == uid)))


async def _run(maker: Maker, gw: _Gateway) -> int:
    return await reconcile_subscriptions(maker, gw, _settings(), NOW)


async def test_no_drift_writes_nothing_and_emits_nothing(maker: Maker) -> None:
    uid = await _seed(maker)
    before = await _sub(maker, uid)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A")
    assert await _run(maker, gw) == 0
    after = await _sub(maker, uid)
    assert after.updated_at == before.updated_at and after.stripe_event_at is None
    assert await _events(maker) == []


async def test_status_drift_converges_and_emits_event(maker: Maker) -> None:
    uid = await _seed(maker, status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A")
    assert await _run(maker, gw) == 1
    row = await _sub(maker, uid)
    assert row.status is SubscriptionStatus.ACTIVE
    assert row.stripe_event_at == NOW
    (event,) = await _events(maker)
    assert event.user_id == uid
    assert event.payload == {
        "changed_fields": ["status"],
        "from_status": "trialing",
        "to_status": "active",
        "cause": "drift",
    }


async def test_interval_and_period_drift_converge(maker: Maker) -> None:
    uid = await _seed(maker, interval="month", period_end=PERIOD_END)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A", price="price_py", period_end=PERIOD_END + 86_400)
    assert await _run(maker, gw) == 1
    row = await _sub(maker, uid)
    assert row.billing_interval == "year"
    assert row.current_period_end == datetime.fromtimestamp(PERIOD_END + 86_400, tz=UTC)
    assert row.expires_at == row.current_period_end
    (event,) = await _events(maker)
    assert set(event.payload["changed_fields"]) == {
        "billing_interval",
        "current_period_end",
        "expires_at",
    }


async def test_plan_change_via_price_converges_limits(maker: Maker) -> None:
    uid = await _seed(maker, plan=PlanType.PRO)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A", price="price_bm")
    assert await _run(maker, gw) == 1
    row = await _sub(maker, uid)
    assert row.plan is PlanType.BASIC
    assert row.limits == default_limits(PlanType.BASIC)
    (event,) = await _events(maker)
    assert {"plan", "limits"} <= set(event.payload["changed_fields"])


async def test_missing_subscription_with_customer_present_cancels_once(maker: Maker) -> None:
    uid = await _seed(maker)
    gw = _Gateway()
    gw.customers["cus_A"] = True
    assert await _run(maker, gw) == 1
    row = await _sub(maker, uid)
    assert row.status is SubscriptionStatus.CANCELED
    assert row.limits == default_limits(PlanType.BASIC)
    notes = [n for n in await _notes(maker, uid) if n.type is NotificationType.SUBSCRIPTION_ENDED]
    assert len(notes) == 1
    (event,) = await _events(maker)
    assert event.payload["cause"] == "resource_missing"
    assert event.payload["to_status"] == "canceled"
    # Idempotent: the canceled row is no longer selected.
    assert await _run(maker, gw) == 0
    assert len([n for n in await _notes(maker, uid)]) == 1


async def test_missing_subscription_and_customer_does_not_cancel(maker: Maker) -> None:
    uid = await _seed(maker)
    gw = _Gateway()
    gw.customers["cus_A"] = False
    assert await _run(maker, gw) == 0
    assert (await _sub(maker, uid)).status is SubscriptionStatus.ACTIVE
    assert await _events(maker) == []


async def test_breaker_trips_on_mass_missing_and_writes_nothing(
    maker: Maker, caplog: pytest.LogCaptureFixture
) -> None:
    uids = [await _seed(maker, f"{i:02d}") for i in range(12)]
    gw = _Gateway()  # every subscription is resource_missing, customers present
    with caplog.at_level("INFO"):
        assert await _run(maker, gw) == 0
    for uid in uids:
        row = await _sub(maker, uid)
        assert row.status is SubscriptionStatus.ACTIVE and row.stripe_event_at is None
    assert await _events(maker) == []
    assert "billing.reconcile.aborted" in caplog.text


async def test_breaker_abort_also_withholds_drift_fixes(maker: Maker) -> None:
    drift = await _seed(maker, "zz", status=SubscriptionStatus.TRIALING)
    for i in range(12):
        await _seed(maker, f"{i:02d}")
    gw = _Gateway()
    gw.subs["sub_zz"] = _raw("sub_zz")
    assert await _run(maker, gw) == 0
    assert (await _sub(maker, drift)).status is SubscriptionStatus.TRIALING


async def test_small_number_of_missing_stays_below_breaker_floor(maker: Maker) -> None:
    uids = [await _seed(maker, f"{i:02d}") for i in range(3)]
    assert await _run(maker, _Gateway()) == 3
    for uid in uids:
        assert (await _sub(maker, uid)).status is SubscriptionStatus.CANCELED


async def test_one_row_error_does_not_stop_the_others(
    maker: Maker, caplog: pytest.LogCaptureFixture
) -> None:
    bad = await _seed(maker, "bad", status=SubscriptionStatus.TRIALING)
    good = await _seed(maker, "ok", status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.subs["sub_bad"] = StripeOperationError("subscription.retrieve", code="timeout")
    gw.subs["sub_ok"] = _raw("sub_ok")
    with caplog.at_level("INFO"):
        assert await _run(maker, gw) == 1
    assert (await _sub(maker, bad)).status is SubscriptionStatus.TRIALING
    assert (await _sub(maker, good)).status is SubscriptionStatus.ACTIVE
    assert "StripeOperationError" in caplog.text


async def test_customer_lookup_error_skips_the_row(maker: Maker) -> None:
    uid = await _seed(maker)
    gw = _Gateway()
    gw.customers["cus_A"] = StripeOperationError("customer.retrieve", code="timeout")
    assert await _run(maker, gw) == 0
    assert (await _sub(maker, uid)).status is SubscriptionStatus.ACTIVE


async def test_unconfigured_stripe_is_a_noop(maker: Maker) -> None:
    await _seed(maker, status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.configured = False
    assert await _run(maker, gw) == 0
    assert gw.calls == []


async def test_skips_deleted_local_only_and_canceled_rows(maker: Maker) -> None:
    await _seed(maker, "d", deleted=True)
    await _seed(maker, "l", linked=False)
    await _seed(maker, "c", status=SubscriptionStatus.CANCELED)
    gw = _Gateway()
    assert await _run(maker, gw) == 0
    assert gw.calls == []


async def test_batch_is_bounded_oldest_first(maker: Maker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subscription_sync, "RECONCILE_BATCH_SIZE", 2)
    for tag in ("a", "b", "c"):
        await _seed(maker, tag)
    gw = _Gateway()
    for tag in ("a", "b", "c"):
        gw.subs[f"sub_{tag}"] = _raw(f"sub_{tag}")
    await _run(maker, gw)
    assert sorted(gw.calls) == ["sub_a", "sub_b"]


def _webhook(event_id: str, created: datetime, status: str) -> dict[str, Any]:
    obj = _raw("sub_A", status=status)
    return {
        "id": event_id,
        "type": "customer.subscription.updated",
        "created": int(created.timestamp()),
        "data": {"object": obj},
    }


async def test_later_webhook_applies_but_older_replay_does_not(maker: Maker) -> None:
    uid = await _seed(maker, status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A")
    assert await _run(maker, gw) == 1
    async with maker() as s:
        await process_event(
            s,
            _webhook("evt_old", NOW - timedelta(hours=1), "past_due"),
            pack_credits={},
            plan_prices=PRICES,
        )
    assert (await _sub(maker, uid)).status is SubscriptionStatus.ACTIVE
    async with maker() as s:
        await process_event(
            s,
            _webhook("evt_new", NOW + timedelta(minutes=1), "past_due"),
            pack_credits={},
            plan_prices=PRICES,
        )
    assert (await _sub(maker, uid)).status is SubscriptionStatus.PAST_DUE


async def test_cross_user_isolation(maker: Maker) -> None:
    a = await _seed(maker, "A", status=SubscriptionStatus.TRIALING)
    b = await _seed(maker, "B", status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A")
    gw.subs["sub_B"] = _raw("sub_B", status="past_due")
    assert await _run(maker, gw) == 2
    assert (await _sub(maker, a)).status is SubscriptionStatus.ACTIVE
    assert (await _sub(maker, b)).status is SubscriptionStatus.PAST_DUE
    assert {e.user_id for e in await _events(maker)} == {a, b}


async def test_logs_and_events_contain_no_stripe_ids_or_emails(
    maker: Maker, caplog: pytest.LogCaptureFixture
) -> None:
    for i in range(12):
        await _seed(maker, f"{i:02d}")
    uid = await _seed(maker, "zz", status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.subs["sub_zz"] = StripeOperationError("subscription.retrieve", code="timeout")
    with caplog.at_level("DEBUG"):
        await _run(maker, gw)
    gw.subs["sub_zz"] = _raw("sub_zz")
    for i in range(12):
        gw.subs[f"sub_{i:02d}"] = _raw(f"sub_{i:02d}")
    with caplog.at_level("DEBUG"):
        await _run(maker, gw)
    assert (await _sub(maker, uid)).status is SubscriptionStatus.ACTIVE
    sync_logs = " ".join(r.getMessage() for r in caplog.records if "reconcile" in r.name)
    assert "sub_" not in sync_logs and "cus_" not in sync_logs and "@" not in sync_logs
    for event in await _events(maker):
        text = str(event.payload)
        assert "sub_" not in text and "cus_" not in text and "@" not in text


async def test_unconsented_user_row_still_converges_without_event(maker: Maker) -> None:
    uid = await _seed(maker, status=SubscriptionStatus.TRIALING, consent=False)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A")
    assert await _run(maker, gw) == 1
    assert (await _sub(maker, uid)).status is SubscriptionStatus.ACTIVE
    assert await _events(maker) == []


async def test_cron_entrypoint_builds_gateway_and_returns_changed_count(maker: Maker) -> None:
    await _seed(maker, status=SubscriptionStatus.TRIALING)
    gw = _Gateway()
    gw.subs["sub_A"] = _raw("sub_A")
    ctx = {"sessionmaker": maker, "stripe_gateway": gw, "settings": _settings()}
    assert await reconcile_stripe_subscriptions(ctx) == 1


async def test_cron_entrypoint_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> Any:
        raise RuntimeError("db down sub_SECRET")

    ctx = {"sessionmaker": broken, "stripe_gateway": _Gateway(), "settings": _settings()}
    assert await reconcile_stripe_subscriptions(ctx) == 0
    assert "SECRET" not in caplog.text and "RuntimeError" in caplog.text
