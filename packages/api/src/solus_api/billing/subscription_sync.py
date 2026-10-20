"""Hourly Stripe subscription reconciliation (SOLUSDEV-236, API-implementation.md §10).

The webhook is the primary writer of Stripe-backed subscription state; this is the safety
net for a missed or dropped delivery. For each live Stripe-linked row it re-reads the
subscription from Stripe, derives the state with the SAME code the webhook uses
(`stripe_events.apply_subscription_state`) and converges the row.

Safety rules:

- Phase 1 only READS from Stripe; nothing is written until every result is in, so the
  circuit breaker can still abort cleanly.
- Breaker: more than max(10, 5% of the batch) `resource_missing` subscriptions means the
  Stripe key/mode is probably wrong, not that dozens of subscriptions vanished. The run
  aborts and commits NOTHING (drift fixes included: if Stripe is answering from the wrong
  account, none of this run's answers can be trusted).
- A missing subscription cancels the row only when its customer still exists in Stripe.
- All writes land in ONE commit; each row is applied inside a savepoint so a failing row
  never leaves a partial write.
- `stripe_event_at` is set to the run time on every applied change: a webhook created
  later still applies, an older replay is ignored (the webhook's existing guard).
- Logs and events carry counts and field names only: no user ids, emails or Stripe ids.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.billing.plan_grants import LIVE_STATUSES, grant_plan_credits
from solus_api.billing.stripe_events import apply_subscription_state
from solus_api.billing.stripe_gateway import (
    BillingUnconfiguredError,
    StripeGateway,
    StripeOperationError,
    StripeResourceMissingError,
)
from solus_api.core.config import Settings
from solus_api.models import Subscription, SubscriptionStatus, User, utcnow
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.billing.reconcile")

RECONCILE_EVENT = "billing.subscription.reconciled"
RECONCILE_BATCH_SIZE = 200
FETCH_CONCURRENCY = 5
BREAKER_MIN_MISSING = 10
BREAKER_MISSING_FRACTION = 0.05

type Cause = Literal["drift", "resource_missing"]
type SessionMaker = async_sessionmaker[AsyncSession]

# Row fields reconciliation may change, in the order they are reported.
_TRACKED_FIELDS = (
    "plan",
    "status",
    "limits",
    "billing_interval",
    "current_period_end",
    "expires_at",
    "cancel_at",
)


class ReconcileGateway(Protocol):
    """The slice of `StripeGateway` the reconciler needs (read-only)."""

    def ensure_configured(self) -> Awaitable[None]: ...
    def retrieve_subscription_raw(self, sub_id: str) -> Awaitable[dict[str, Any]]: ...
    def customer_exists(self, customer_id: str) -> Awaitable[bool]: ...


@dataclass(frozen=True)
class _Target:
    row_id: uuid.UUID
    subscription_id: str
    customer_id: str | None


@dataclass(frozen=True)
class _Fetched:
    target: _Target
    raw: dict[str, Any] | None = None
    missing: bool = False
    customer_present: bool = False


def _snapshot(row: Subscription) -> dict[str, Any]:
    return {name: getattr(row, name) for name in _TRACKED_FIELDS}


def _status_value(value: object) -> str:
    return value.value if isinstance(value, SubscriptionStatus) else str(value)


async def _load_targets(maker: SessionMaker) -> list[_Target]:
    async with maker() as session:
        rows = (
            await session.execute(
                select(
                    Subscription.id,
                    Subscription.stripe_subscription_id,
                    Subscription.stripe_customer_id,
                )
                .where(
                    Subscription.deleted_at.is_(None),
                    Subscription.stripe_subscription_id.is_not(None),
                    Subscription.status != SubscriptionStatus.CANCELED,
                )
                .order_by(Subscription.updated_at, Subscription.id)
                .limit(RECONCILE_BATCH_SIZE)
            )
        ).all()
    return [_Target(r[0], str(r[1]), r[2]) for r in rows]


async def _fetch_one(gateway: ReconcileGateway, target: _Target) -> _Fetched | None:
    """One row's Stripe truth, or None when it cannot be determined (logged, skipped)."""
    try:
        try:
            raw = await gateway.retrieve_subscription_raw(target.subscription_id)
        except StripeResourceMissingError:
            present = bool(target.customer_id) and await gateway.customer_exists(
                target.customer_id or ""
            )
            return _Fetched(target, missing=True, customer_present=present)
        return _Fetched(target, raw=raw)
    except (StripeOperationError, ValueError) as exc:
        logger.warning("billing.reconcile.row_skipped error=%s", type(exc).__name__)
        return None


async def _fetch_all(gateway: ReconcileGateway, targets: Sequence[_Target]) -> list[_Fetched]:
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def bounded(target: _Target) -> _Fetched | None:
        async with gate:
            return await _fetch_one(gateway, target)

    results = await asyncio.gather(*(bounded(t) for t in targets))
    return [r for r in results if r is not None]


def _breaker_tripped(missing: int, batch: int) -> bool:
    return missing > max(BREAKER_MIN_MISSING, int(batch * BREAKER_MISSING_FRACTION))


def _is_stale(row: Subscription, fetched: _Fetched, now: datetime) -> bool:
    """The row moved on while we were talking to Stripe: a webhook landed after this run
    began, or the row was relinked to another subscription."""
    if row.stripe_subscription_id != fetched.target.subscription_id:
        return True
    return row.stripe_event_at is not None and row.stripe_event_at > now


async def _apply_one(
    session: AsyncSession,
    fetched: _Fetched,
    settings: Settings,
    now: datetime,
) -> Subscription | None:
    """Apply one fetched result inside the caller's savepoint; the changed row or None."""
    row = await session.get(Subscription, fetched.target.row_id, with_for_update=True)
    if row is None or row.deleted_at is not None or _is_stale(row, fetched, now):
        return None
    cause: Cause = "resource_missing" if fetched.missing else "drift"
    if fetched.missing and not fetched.customer_present:
        return None
    before = _snapshot(row)
    apply_subscription_state(
        session,
        row,
        fetched.raw or {},
        dict(settings.stripe_plan_prices),
        deleted=fetched.missing,
    )
    changed = [name for name in _TRACKED_FIELDS if getattr(row, name) != before[name]]
    if not changed:
        return None
    row.stripe_event_at = now
    user = await session.get(User, row.user_id)
    if user is not None:
        emit_event(
            session,
            user=user,
            event_type=RECONCILE_EVENT,
            payload={
                "changed_fields": changed,
                "from_status": _status_value(before["status"]),
                "to_status": _status_value(row.status),
                "cause": cause,
            },
        )
    return row


async def _apply_all(
    session: AsyncSession, results: Sequence[_Fetched], settings: Settings, now: datetime
) -> list[uuid.UUID]:
    changed: list[uuid.UUID] = []
    for fetched in results:
        try:
            async with session.begin_nested():
                row = await _apply_one(session, fetched, settings, now)
        except Exception as exc:  # noqa: BLE001 — savepoint rolled back; class only, never ids
            logger.error("billing.reconcile.row_failed error=%s", type(exc).__name__)
            continue
        if row is not None:
            changed.append(row.id)
    return changed


async def _grant_starting_credits(
    maker: SessionMaker, row_ids: Sequence[uuid.UUID], settings: Settings
) -> None:
    """A missed webhook also missed the one-time plan grant; it is idempotent per plan."""
    for row_id in row_ids:
        async with maker() as session:
            row = await session.get(Subscription, row_id)
            if row is not None and row.status in LIVE_STATUSES:
                await grant_plan_credits(session, row, dict(settings.plan_credit_grants))


async def reconcile_subscriptions(
    maker: SessionMaker, gateway: ReconcileGateway, settings: Settings, now: datetime
) -> int:
    """Converge live Stripe-linked rows onto Stripe; returns how many rows changed."""
    try:
        await gateway.ensure_configured()
    except BillingUnconfiguredError:
        logger.info("billing.reconcile.skipped reason=stripe_unconfigured")
        return 0
    targets = await _load_targets(maker)
    try:
        results = await _fetch_all(gateway, targets)
    except BillingUnconfiguredError:
        logger.info("billing.reconcile.skipped reason=stripe_unconfigured")
        return 0
    missing = sum(1 for r in results if r.missing)
    if _breaker_tripped(missing, len(targets)):
        logger.error(
            "billing.reconcile.aborted missing=%d batch=%d threshold=%d",
            missing,
            len(targets),
            max(BREAKER_MIN_MISSING, int(len(targets) * BREAKER_MISSING_FRACTION)),
        )
        return 0
    async with maker() as session:
        changed = await _apply_all(session, results, settings, now)
        await session.commit()
    await _grant_starting_credits(maker, changed, settings)
    logger.info(
        "billing.reconcile.done checked=%d fetched=%d changed=%d",
        len(targets),
        len(results),
        len(changed),
    )
    return len(changed)


async def reconcile_stripe_subscriptions(ctx: dict[str, Any]) -> int:
    """ARQ cron (hourly): see module docstring. Never raises to ARQ; the next run retries."""
    try:
        gateway = ctx.get("stripe_gateway") or StripeGateway(ctx["secret_store"])
        return await reconcile_subscriptions(
            ctx["sessionmaker"], gateway, ctx["settings"], utcnow()
        )
    except Exception as exc:  # noqa: BLE001 — logged; the reconciler is idempotent
        # Type name only: DB tracebacks carry bound parameters (Stripe/user ids).
        logger.error("billing.reconcile.failed error=%s", type(exc).__name__)
        return 0
