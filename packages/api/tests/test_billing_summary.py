"""BillingSummaryService (SOLUSDEV-236 T5): assembly, degraded modes, caches, id hygiene.

Fake gateway, injected clock; no network, no database.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import TEST_AUDIENCE, TEST_DATABASE_URL, TEST_JWT_SECRET
from solus_api.billing.stripe_gateway import (
    BillingUnconfiguredError,
    CardSummary,
    InvoicePreview,
    PriceAmount,
    StripeOperationError,
)
from solus_api.billing.summary import BillingSummaryService, SummaryCaches
from solus_api.core.config import Settings
from solus_api.models import PlanType, Subscription, SubscriptionStatus

NOW = datetime(2026, 10, 21, tzinfo=UTC)
PRICES = {
    "basic:month": "price_bm",
    "basic:year": "price_by",
    "pro:month": "price_pm",
    "pro:year": "price_py",
}
AMOUNTS = {
    "price_bm": PriceAmount(2500, "usd", "month"),
    "price_by": PriceAmount(20000, "usd", "year"),
    "price_pm": PriceAmount(3500, "usd", "month"),
    "price_py": PriceAmount(30000, "usd", "year"),
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeGateway:
    def __init__(self) -> None:
        self.unconfigured = False
        self.invoice: InvoicePreview | None = InvoicePreview(2500, "usd", NOW + timedelta(days=30))
        self.card: CardSummary | None = CardSummary("visa", "4242")
        self.invoice_error: Exception | None = None
        self.price_error: Exception | None = None
        self.price_delay = 0.0
        self.calls: list[str] = []

    async def ensure_configured(self) -> None:
        if self.unconfigured:
            raise BillingUnconfiguredError("no key")

    async def upcoming_invoice(
        self, customer_id: str, subscription_id: str
    ) -> InvoicePreview | None:
        self.calls.append("invoice")
        if self.invoice_error:
            raise self.invoice_error
        return self.invoice

    async def default_payment_method(
        self, customer_id: str, subscription_id: str
    ) -> CardSummary | None:
        self.calls.append("card")
        return self.card

    async def price_amounts(self, price_ids: list[str]) -> dict[str, PriceAmount]:
        self.calls.append("prices")
        await asyncio.sleep(self.price_delay)
        if self.price_error:
            raise self.price_error
        return {p: AMOUNTS[p] for p in price_ids}

    def count(self, name: str) -> int:
        return self.calls.count(name)


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "stripe_plan_prices": PRICES,
        "stripe_pack_credits": {"price_pack": 1000},
    }
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        **{**base, **over},
    )


def _sub(**over: Any) -> Subscription:
    values: dict[str, Any] = {
        "user_id": uuid.uuid4(),
        "plan": PlanType.BASIC,
        "status": SubscriptionStatus.ACTIVE,
        "billing_interval": "year",
        "current_period_end": NOW + timedelta(days=30),
        "cancel_at": None,
        "expires_at": NOW + timedelta(days=30),
        "stripe_customer_id": "cus_abc",
        "stripe_subscription_id": "sub_abc",
    }
    return Subscription(**{**values, **over})


def _local_trial(**over: Any) -> Subscription:
    return _sub(
        status=SubscriptionStatus.TRIALING,
        billing_interval=None,
        current_period_end=None,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        expires_at=NOW + timedelta(days=5),
        **over,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def gw() -> FakeGateway:
    return FakeGateway()


def _svc(gw: FakeGateway, clock: FakeClock, caches: SummaryCaches | None = None, **s: Any) -> Any:
    return BillingSummaryService(gw, _settings(**s), caches=caches or SummaryCaches(clock=clock))


async def test_local_trial_makes_no_per_user_stripe_calls(
    gw: FakeGateway, clock: FakeClock
) -> None:
    out = await _svc(gw, clock).summarize(_local_trial(), now=NOW)
    assert out.trial.state == "active" and out.trial.ends_at == NOW + timedelta(days=5)
    assert out.next_invoice is None and out.payment_method is None
    assert gw.calls == ["prices"]
    assert out.stripe_status == "ok"
    assert out.prices is not None and len(out.prices) == 4


async def test_local_trial_expired(gw: FakeGateway, clock: FakeClock) -> None:
    sub = _local_trial()
    sub.expires_at = NOW - timedelta(seconds=1)
    out = await _svc(gw, clock).summarize(sub, now=NOW)
    assert out.trial.state == "expired" and out.trial.ends_at == sub.expires_at


async def test_stripe_trialing_is_active_with_invoice(gw: FakeGateway, clock: FakeClock) -> None:
    out = await _svc(gw, clock).summarize(_sub(status=SubscriptionStatus.TRIALING), now=NOW)
    assert out.trial.state == "active"
    assert out.next_invoice is not None and out.payment_method is not None


async def test_active_yearly_full_shape(gw: FakeGateway, clock: FakeClock) -> None:
    sub = _sub()
    out = await _svc(gw, clock).summarize(sub, now=NOW)
    assert out.trial.state == "none" and out.trial.ends_at is None
    assert (out.plan, out.status, out.billing_interval) == (
        PlanType.BASIC,
        SubscriptionStatus.ACTIVE,
        "year",
    )
    assert out.current_period_end == sub.current_period_end
    assert out.next_invoice is not None
    assert (out.next_invoice.amount_cents, out.next_invoice.currency) == (2500, "usd")
    assert out.payment_method is not None
    assert (out.payment_method.brand, out.payment_method.last4) == ("visa", "4242")
    assert out.packs_available is True and out.stripe_status == "ok"
    assert {(p.plan.value, p.interval): p.amount_cents for p in out.prices or []} == {
        ("basic", "month"): 2500,
        ("basic", "year"): 20000,
        ("pro", "month"): 3500,
        ("pro", "year"): 30000,
    }


async def test_cancel_pending_has_no_next_invoice_but_keeps_card(
    gw: FakeGateway, clock: FakeClock
) -> None:
    out = await _svc(gw, clock).summarize(_sub(cancel_at=NOW + timedelta(days=9)), now=NOW)
    assert out.next_invoice is None and out.cancel_at == NOW + timedelta(days=9)
    assert out.payment_method is not None
    assert gw.count("invoice") == 0


@pytest.mark.parametrize("status", [SubscriptionStatus.CANCELED, SubscriptionStatus.PAST_DUE])
async def test_non_billing_statuses_have_no_next_invoice(
    gw: FakeGateway, clock: FakeClock, status: SubscriptionStatus
) -> None:
    out = await _svc(gw, clock).summarize(_sub(status=status), now=NOW)
    assert out.status == status and out.next_invoice is None
    assert out.trial.state == "none"
    assert gw.count("invoice") == 0


async def test_invoice_error_degrades_only_that_field(gw: FakeGateway, clock: FakeClock) -> None:
    gw.invoice_error = StripeOperationError("invoice.create_preview", code="timeout")
    out = await _svc(gw, clock).summarize(_sub(), now=NOW)
    assert out.stripe_status == "unavailable"
    assert out.next_invoice is None
    assert out.payment_method is not None and out.prices is not None
    assert out.plan == PlanType.BASIC


async def test_price_failure_nulls_prices_and_marks_unavailable(
    gw: FakeGateway, clock: FakeClock
) -> None:
    gw.price_error = StripeOperationError("price.retrieve", code="timeout")
    out = await _svc(gw, clock).summarize(_sub(), now=NOW)
    assert out.prices is None and out.stripe_status == "unavailable"
    assert out.next_invoice is not None


async def test_unconfigured_makes_no_stripe_calls(gw: FakeGateway, clock: FakeClock) -> None:
    gw.unconfigured = True
    out = await _svc(gw, clock).summarize(_sub(), now=NOW)
    assert out.stripe_status == "unconfigured"
    assert out.prices is None and out.next_invoice is None and out.payment_method is None
    assert gw.calls == []


async def test_no_price_mapping_is_unconfigured(gw: FakeGateway, clock: FakeClock) -> None:
    out = await _svc(gw, clock, stripe_plan_prices={}).summarize(_sub(), now=NOW)
    assert out.stripe_status == "unconfigured" and out.prices is None


async def test_prices_cache_is_global_and_expires(gw: FakeGateway, clock: FakeClock) -> None:
    svc = _svc(gw, clock)
    await svc.summarize(_sub(), now=NOW)
    await svc.summarize(_sub(), now=NOW)
    assert gw.count("prices") == 1
    clock.now += 599
    await svc.summarize(_sub(), now=NOW)
    assert gw.count("prices") == 1
    clock.now += 2
    await svc.summarize(_sub(), now=NOW)
    assert gw.count("prices") == 2


async def test_concurrent_cold_requests_fetch_prices_once(
    gw: FakeGateway, clock: FakeClock
) -> None:
    gw.price_delay = 0.05
    svc = _svc(gw, clock)
    await asyncio.gather(*(svc.summarize(_sub(), now=NOW) for _ in range(8)))
    assert gw.count("prices") == 1


async def test_failed_price_fetch_is_negative_cached_briefly(
    gw: FakeGateway, clock: FakeClock
) -> None:
    gw.price_error = StripeOperationError("price.retrieve", code="timeout")
    svc = _svc(gw, clock)
    await svc.summarize(_sub(), now=NOW)
    await svc.summarize(_sub(), now=NOW)
    assert gw.count("prices") == 1
    gw.price_error = None
    clock.now += 31
    out = await svc.summarize(_sub(), now=NOW)
    assert out.prices is not None and gw.count("prices") == 2


async def test_per_user_cache_hits_within_ttl_and_is_user_scoped(
    gw: FakeGateway, clock: FakeClock
) -> None:
    svc = _svc(gw, clock)
    a, b = _sub(), _sub()
    await svc.summarize(a, now=NOW)
    await svc.summarize(a, now=NOW)
    assert gw.count("invoice") == 1
    await svc.summarize(b, now=NOW)
    assert gw.count("invoice") == 2
    clock.now += 61
    await svc.summarize(a, now=NOW)
    assert gw.count("invoice") == 3


async def test_cached_entry_never_served_to_another_user(gw: FakeGateway, clock: FakeClock) -> None:
    svc = _svc(gw, clock)
    a, b = _sub(), _sub()
    await svc.summarize(a, now=NOW)
    gw.card = CardSummary("amex", "0005")
    out_b = await svc.summarize(b, now=NOW)
    assert out_b.payment_method is not None and out_b.payment_method.last4 == "0005"
    out_a = await svc.summarize(a, now=NOW)
    assert out_a.payment_method is not None and out_a.payment_method.last4 == "4242"


async def test_row_change_busts_the_user_cache(gw: FakeGateway, clock: FakeClock) -> None:
    svc = _svc(gw, clock)
    sub = _sub()
    await svc.summarize(sub, now=NOW)
    sub.cancel_at = NOW + timedelta(days=3)
    out = await svc.summarize(sub, now=NOW)
    assert out.cancel_at is not None and out.next_invoice is None


async def test_degraded_user_entry_expires_sooner(gw: FakeGateway, clock: FakeClock) -> None:
    gw.invoice_error = StripeOperationError("invoice.create_preview", code="timeout")
    svc = _svc(gw, clock)
    sub = _sub()
    await svc.summarize(sub, now=NOW)
    await svc.summarize(sub, now=NOW)
    assert gw.count("invoice") == 1
    gw.invoice_error = None
    clock.now += 11
    out = await svc.summarize(sub, now=NOW)
    assert out.stripe_status == "ok" and out.next_invoice is not None


async def test_user_cache_is_bounded(gw: FakeGateway, clock: FakeClock) -> None:
    caches = SummaryCaches(clock=clock, max_user_entries=2)
    svc = _svc(gw, clock, caches)
    subs = [_sub() for _ in range(3)]
    for s in subs:
        await svc.summarize(s, now=NOW)
    await svc.summarize(subs[0], now=NOW)  # evicted -> refetch
    assert gw.count("invoice") == 4


async def test_packs_unavailable_when_config_empty(gw: FakeGateway, clock: FakeClock) -> None:
    out = await _svc(gw, clock, stripe_pack_credits={}).summarize(_sub(), now=NOW)
    assert out.packs_available is False


async def test_only_checkoutable_well_formed_prices_listed(
    gw: FakeGateway, clock: FakeClock
) -> None:
    extra = {**PRICES, "enterprise:month": "price_ent", "basic:week": "price_w", "junk": "price_j"}
    out = await _svc(gw, clock, stripe_plan_prices=extra).summarize(_sub(), now=NOW)
    assert {(p.plan.value, p.interval) for p in out.prices or []} == {
        ("basic", "month"),
        ("basic", "year"),
        ("pro", "month"),
        ("pro", "year"),
    }


async def test_result_contains_no_stripe_ids(gw: FakeGateway, clock: FakeClock) -> None:
    out = await _svc(gw, clock).summarize(_sub(), now=NOW)
    blob = out.model_dump_json()
    for needle in ("cus_", "sub_", "pm_", "price_", "in_"):
        assert needle not in blob
