"""Billing summary read model (SOLUSDEV-236, docs/api/API-implementation.md section 10).

Assembles `GET /billing/summary` from the caller's own subscription row plus a few
Stripe reads, and degrades to nulls (never an error) when Stripe is unavailable.

Caching (no Stripe call is ever made per request for prices):
  * Prices: ONE process-global cache shared by all users (10 min); a failed fetch is
    cached briefly (30 s) so an outage is not hammered, and a lock makes concurrent
    cold requests fetch once. Prices are not user data, so sharing is safe.
  * Per-user Stripe reads (next invoice, card): keyed by (user_id, row fingerprint) so an
    entry can never reach another user and a webhook-driven row change busts it. 60 s when
    complete, 10 s when degraded (an outage recovers quickly, yet a hot loop is absorbed).
    Bounded LRU. Local fields are always recomputed from the row, never cached.

No Stripe object ids are produced or logged here (CLAUDE.md section 7).
"""

import asyncio
import logging
import time
import weakref
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from solus_api.billing.entitlements import is_local_trial_expired
from solus_api.billing.plans import CHECKOUTABLE_PLANS, VALID_INTERVALS, plan_price_id
from solus_api.billing.stripe_gateway import (
    BillingUnconfiguredError,
    CardSummary,
    InvoicePreview,
    PriceAmount,
    StripeOperationError,
)
from solus_api.core.config import Settings
from solus_api.models import Subscription, SubscriptionStatus, utcnow
from solus_api.schemas import (
    BillingCardRead,
    BillingInvoiceRead,
    BillingPriceRead,
    BillingSummaryRead,
    BillingTrialRead,
)

logger = logging.getLogger("solus.billing.summary")

PRICES_TTL_SECONDS = 600.0
PRICES_FAILURE_TTL_SECONDS = 30.0
USER_TTL_SECONDS = 60.0
USER_DEGRADED_TTL_SECONDS = 10.0
MAX_USER_ENTRIES = 1024
#: Budget for each per-user Stripe leg (docs: PROPOSED 3 s per call).
STRIPE_BUDGET_SECONDS = 3.0

_INVOICE_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})
_STRIPE_FAILURES = (StripeOperationError, BillingUnconfiguredError, ValueError, TimeoutError)
_PriceKey = tuple[str, str, str]  # (plan, interval, price id) -- id stays internal.


class SummaryGateway(Protocol):
    async def ensure_configured(self) -> None: ...
    async def upcoming_invoice(
        self, customer_id: str, subscription_id: str
    ) -> InvoicePreview | None: ...
    async def default_payment_method(
        self, customer_id: str, subscription_id: str
    ) -> CardSummary | None: ...
    async def price_amounts(self, price_ids: list[str]) -> dict[str, PriceAmount]: ...


@dataclass(frozen=True)
class _Remote:
    next_invoice: InvoicePreview | None
    payment_method: CardSummary | None
    ok: bool


_MISSING: Any = object()


class _TtlCache:
    """Bounded LRU with per-entry expiry on an injectable monotonic clock."""

    def __init__(self, clock: Callable[[], float], max_entries: int) -> None:
        self._clock = clock
        self._max = max_entries
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    def get(self, key: Any) -> Any:
        entry = self._data.get(key)
        if entry is None or entry[0] <= self._clock():
            self._data.pop(key, None)
            return _MISSING
        self._data.move_to_end(key)
        return entry[1]

    def put(self, key: Any, value: Any, ttl: float) -> None:
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


class SummaryCaches:
    """The two caches plus the per-event-loop lock guarding the global price fetch."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_user_entries: int = MAX_USER_ENTRIES,
    ) -> None:
        self.prices = _TtlCache(clock, max_entries=1)
        self.users = _TtlCache(clock, max_entries=max_user_entries)
        self._locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
            weakref.WeakKeyDictionary()
        )

    def price_lock(self) -> asyncio.Lock:
        return self._locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())

    def clear(self) -> None:
        self.prices.clear()
        self.users.clear()


_CACHES = SummaryCaches()


def reset_billing_summary_caches() -> None:
    """Drop the process-global caches (tests)."""
    _CACHES.clear()


def _trial(sub: Subscription, now: datetime) -> BillingTrialRead:
    if sub.status != SubscriptionStatus.TRIALING:
        return BillingTrialRead(state="none", ends_at=None)
    expired = is_local_trial_expired(sub, now)
    return BillingTrialRead(state="expired" if expired else "active", ends_at=sub.expires_at)


def _fingerprint(sub: Subscription) -> tuple[Any, ...]:
    return (
        sub.user_id,
        sub.stripe_customer_id,
        sub.stripe_subscription_id,
        sub.status,
        sub.plan,
        sub.cancel_at,
        sub.current_period_end,
    )


class BillingSummaryService:
    def __init__(
        self, gateway: SummaryGateway, settings: Settings, *, caches: SummaryCaches | None = None
    ) -> None:
        self._gateway = gateway
        self._settings = settings
        self._caches = caches or _CACHES

    async def summarize(
        self, sub: Subscription, *, now: datetime | None = None
    ) -> BillingSummaryRead:
        now = now or utcnow()
        keys = self._price_keys()
        try:
            await self._gateway.ensure_configured()
            configured = bool(keys)
        except BillingUnconfiguredError:
            configured = False
        prices: list[BillingPriceRead] | None = None
        remote = _Remote(None, None, True)
        if configured:
            prices, remote = await asyncio.gather(self._prices(keys), self._remote(sub))
        status = "unconfigured" if not configured else "ok"
        if configured and (prices is None or not remote.ok):
            status = "unavailable"
        return BillingSummaryRead(
            plan=sub.plan,
            status=sub.status,
            billing_interval=sub.billing_interval,
            current_period_end=sub.current_period_end,
            cancel_at=sub.cancel_at,
            trial=_trial(sub, now),
            next_invoice=_invoice_read(remote.next_invoice),
            payment_method=_card_read(remote.payment_method),
            prices=prices,
            packs_available=bool(self._settings.stripe_pack_credits),
            stripe_status=status,  # type: ignore[arg-type]
        )

    def _price_keys(self) -> list[_PriceKey]:
        keys: list[_PriceKey] = []
        for plan in sorted(CHECKOUTABLE_PLANS, key=lambda p: p.value):
            for interval in sorted(VALID_INTERVALS):
                price_id = plan_price_id(self._settings, plan, interval)
                if price_id:
                    keys.append((plan.value, interval, price_id))
        return keys

    async def _prices(self, keys: list[_PriceKey]) -> list[BillingPriceRead] | None:
        cache = self._caches.prices
        cached = cache.get("prices")
        if cached is not _MISSING:
            return cached  # type: ignore[no-any-return]
        async with self._caches.price_lock():
            cached = cache.get("prices")
            if cached is not _MISSING:
                return cached  # type: ignore[no-any-return]
            prices = await self._fetch_prices(keys)
            ttl = PRICES_TTL_SECONDS if prices is not None else PRICES_FAILURE_TTL_SECONDS
            cache.put("prices", prices, ttl)
            return prices

    async def _fetch_prices(self, keys: list[_PriceKey]) -> list[BillingPriceRead] | None:
        try:
            async with asyncio.timeout(STRIPE_BUDGET_SECONDS):
                amounts = await self._gateway.price_amounts([k[2] for k in keys])
            return [
                BillingPriceRead(
                    plan=plan,  # type: ignore[arg-type]
                    interval=interval,  # type: ignore[arg-type]
                    amount_cents=amounts[price_id].amount_cents,
                    currency=amounts[price_id].currency,
                )
                for plan, interval, price_id in keys
            ]
        except (*_STRIPE_FAILURES, KeyError) as exc:
            logger.warning("billing summary price fetch failed: %s", type(exc).__name__)
            return None

    async def _remote(self, sub: Subscription) -> _Remote:
        customer, subscription = sub.stripe_customer_id, sub.stripe_subscription_id
        if not customer or not subscription:
            return _Remote(None, None, True)
        key = _fingerprint(sub)
        cached = self._caches.users.get(key)
        if cached is not _MISSING:
            return cached  # type: ignore[no-any-return]
        wants_invoice = sub.cancel_at is None and sub.status in _INVOICE_STATUSES
        invoice, card = await asyncio.gather(
            self._leg(self._gateway.upcoming_invoice(customer, subscription), wants_invoice),
            self._leg(self._gateway.default_payment_method(customer, subscription), True),
        )
        remote = _Remote(invoice[0], card[0], invoice[1] and card[1])
        ttl = USER_TTL_SECONDS if remote.ok else USER_DEGRADED_TTL_SECONDS
        self._caches.users.put(key, remote, ttl)
        return remote

    @staticmethod
    async def _leg(call: Any, wanted: bool) -> tuple[Any, bool]:
        """(value, ok) for one Stripe read; a skipped or failed read yields None."""
        if not wanted:
            call.close()
            return None, True
        try:
            async with asyncio.timeout(STRIPE_BUDGET_SECONDS):
                return await call, True
        except _STRIPE_FAILURES as exc:
            logger.warning("billing summary stripe read failed: %s", type(exc).__name__)
            return None, False


def _invoice_read(invoice: InvoicePreview | None) -> BillingInvoiceRead | None:
    if invoice is None:
        return None
    return BillingInvoiceRead(
        amount_cents=invoice.amount_cents, currency=invoice.currency, date=invoice.date
    )


def _card_read(card: CardSummary | None) -> BillingCardRead | None:
    return None if card is None else BillingCardRead(brand=card.brand, last4=card.last4)
