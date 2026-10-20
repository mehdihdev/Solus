"""Pure derivation of local subscription state from a Stripe Subscription object
(SOLUSDEV-236, docs/schemas/subscriptions.md §expires_at).

No I/O: the webhook handler (and, later, reconciliation) feed it a signed payload or a
retrieved subscription dict and get one immutable value back. Payloads are schema-loose,
so every read is defensive and a malformed field degrades to None, never an exception.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from solus_api.billing.plans import plan_for_price_id
from solus_api.models import PlanType, SubscriptionStatus

type BillingInterval = Literal["month", "year"]

_INTERVALS: tuple[BillingInterval, ...] = ("month", "year")

# Stripe subscription.status → our SubscriptionStatus. Unknown/unpaid states are
# treated as past_due (dunning), which the app surfaces as "action needed".
STATUS_MAP: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.TRIALING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "incomplete": SubscriptionStatus.PAST_DUE,
    "paused": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete_expired": SubscriptionStatus.CANCELED,
}


@dataclass(frozen=True)
class StripeSubscriptionState:
    """What a Stripe subscription says about a local row. Datetimes are tz-aware or None."""

    status: SubscriptionStatus
    plan: PlanType | None
    interval: BillingInterval | None
    current_period_end: datetime | None
    trial_end: datetime | None
    cancel_at: datetime | None
    expires_at: datetime | None


def as_dict(value: object) -> dict[str, Any]:
    """`value` if it is a dict, else {} — signed payloads are still schema-loose."""
    return value if isinstance(value, dict) else {}


def parse_timestamp(raw: object) -> datetime | None:
    """Epoch seconds (int, float or numeric string) → aware UTC; anything else → None."""
    if not raw or isinstance(raw, bool):
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)  # type: ignore[call-overload]
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _first_item(obj: Mapping[str, Any]) -> dict[str, Any]:
    items = as_dict(obj.get("items")).get("data")
    if not isinstance(items, list) or not items:
        return {}
    return as_dict(items[0])


def subscription_price_id(obj: Mapping[str, Any]) -> str | None:
    """The first line item's Stripe Price id on a subscription object, or None."""
    pid = as_dict(_first_item(obj).get("price")).get("id")
    return str(pid) if pid else None


def _interval_from_config(plan_prices: Mapping[str, str], price_id: str) -> BillingInterval | None:
    for key, mapped in plan_prices.items():
        _, _, interval = key.partition(":")
        if mapped == price_id and interval in _INTERVALS:
            return "month" if interval == "month" else "year"
    return None


def _interval_from_recurring(obj: Mapping[str, Any]) -> BillingInterval | None:
    raw = as_dict(as_dict(_first_item(obj).get("price")).get("recurring")).get("interval")
    if raw == "month":
        return "month"
    return "year" if raw == "year" else None


def _derive_interval(
    obj: Mapping[str, Any], plan_prices: Mapping[str, str], price_id: str | None
) -> BillingInterval | None:
    configured = _interval_from_config(plan_prices, price_id) if price_id else None
    return configured or _interval_from_recurring(obj)


def derive_subscription_state(
    obj: Mapping[str, Any], plan_prices: Mapping[str, str], *, deleted: bool = False
) -> StripeSubscriptionState:
    """Derive status/plan/interval/period dates from a Stripe subscription object.

    `current_period_end` is read from the top level, else from the first item (newer
    Stripe API versions moved it there). `expires_at` is the trial end while trialing,
    else the period end (schema doc rule)."""
    status = (
        SubscriptionStatus.CANCELED
        if deleted
        else STATUS_MAP.get(str(obj.get("status")), SubscriptionStatus.PAST_DUE)
    )
    price_id = subscription_price_id(obj)
    period_end = parse_timestamp(obj.get("current_period_end")) or parse_timestamp(
        _first_item(obj).get("current_period_end")
    )
    trial_end = parse_timestamp(obj.get("trial_end"))
    is_trial = status is SubscriptionStatus.TRIALING and trial_end is not None
    return StripeSubscriptionState(
        status=status,
        plan=plan_for_price_id(dict(plan_prices), price_id) if price_id else None,
        interval=_derive_interval(obj, plan_prices, price_id),
        current_period_end=period_end,
        trial_end=trial_end,
        cancel_at=parse_timestamp(obj.get("cancel_at")),
        expires_at=trial_end if is_trial else period_end,
    )
