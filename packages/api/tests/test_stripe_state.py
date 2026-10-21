"""Pure Stripe subscription state derivation (SOLUSDEV-236)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from solus_api.billing.stripe_state import StripeSubscriptionState, derive_subscription_state
from solus_api.models import PlanType, SubscriptionStatus

PRICES = {"basic:month": "price_b_m", "pro:month": "price_p_m", "pro:year": "price_p_y"}


def _obj(
    *,
    status: str = "active",
    price: str | None = "price_p_y",
    recurring: str | None = None,
    top_period_end: Any = None,
    item_period_end: Any = None,
    trial_end: Any = None,
    cancel_at: Any = None,
) -> dict[str, Any]:
    price_obj: dict[str, Any] = {"id": price}
    if recurring is not None:
        price_obj["recurring"] = {"interval": recurring}
    item: dict[str, Any] = {"price": price_obj}
    if item_period_end is not None:
        item["current_period_end"] = item_period_end
    obj: dict[str, Any] = {"status": status, "items": {"data": [item]}, "cancel_at": cancel_at}
    if top_period_end is not None:
        obj["current_period_end"] = top_period_end
    if trial_end is not None:
        obj["trial_end"] = trial_end
    return obj


def _dt(secs: int) -> datetime:
    return datetime.fromtimestamp(secs, tz=UTC)


def test_item_level_period_end_is_read() -> None:
    state = derive_subscription_state(_obj(item_period_end=1_900_000_000), PRICES)
    assert state.current_period_end == _dt(1_900_000_000)
    assert state.expires_at == _dt(1_900_000_000)


def test_top_level_period_end_wins_over_item() -> None:
    state = derive_subscription_state(
        _obj(top_period_end=1_800_000_000, item_period_end=1_900_000_000), PRICES
    )
    assert state.current_period_end == _dt(1_800_000_000)


def test_trialing_expires_at_is_trial_end() -> None:
    state = derive_subscription_state(
        _obj(status="trialing", trial_end=1_700_000_000, item_period_end=1_900_000_000), PRICES
    )
    assert state.status is SubscriptionStatus.TRIALING
    assert state.trial_end == _dt(1_700_000_000)
    assert state.expires_at == _dt(1_700_000_000)
    assert state.current_period_end == _dt(1_900_000_000)


def test_trialing_without_trial_end_falls_back_to_period_end() -> None:
    state = derive_subscription_state(
        _obj(status="trialing", item_period_end=1_900_000_000), PRICES
    )
    assert state.trial_end is None
    assert state.expires_at == _dt(1_900_000_000)


def test_active_ignores_stale_trial_end_for_expires_at() -> None:
    state = derive_subscription_state(
        _obj(trial_end=1_700_000_000, item_period_end=1_900_000_000), PRICES
    )
    assert state.trial_end == _dt(1_700_000_000)
    assert state.expires_at == _dt(1_900_000_000)


def test_interval_comes_from_config_map_over_recurring() -> None:
    state = derive_subscription_state(_obj(price="price_p_y", recurring="month"), PRICES)
    assert state.interval == "year"
    assert state.plan is PlanType.PRO


def test_interval_falls_back_to_recurring_for_unknown_price() -> None:
    state = derive_subscription_state(_obj(price="price_other", recurring="month"), PRICES)
    assert state.plan is None
    assert state.interval == "month"


def test_unknown_price_without_recurring_has_no_interval() -> None:
    state = derive_subscription_state(_obj(price="price_other"), PRICES)
    assert (state.plan, state.interval) == (None, None)


@pytest.mark.parametrize("raw", ["week", "day", "", 5])
def test_non_month_year_interval_is_none(raw: Any) -> None:
    state = derive_subscription_state(_obj(price="price_other", recurring=raw), PRICES)
    assert state.interval is None


def test_malformed_config_key_yields_no_interval_from_map() -> None:
    state = derive_subscription_state(_obj(price="p"), {"pro": "p"})
    assert state.interval is None


@pytest.mark.parametrize("raw", ["soon", {}, [], 1e30, -(10**30), True, None, float("nan")])
def test_malformed_timestamps_become_none_and_never_raise(raw: Any) -> None:
    state = derive_subscription_state(
        _obj(top_period_end=raw, trial_end=raw, cancel_at=raw), PRICES
    )
    assert state.trial_end is None
    assert state.cancel_at is None
    assert state.current_period_end is None


def test_numeric_string_timestamps_are_accepted() -> None:
    state = derive_subscription_state(_obj(top_period_end="1900000000"), PRICES)
    assert state.current_period_end == _dt(1_900_000_000)


def test_no_items_and_garbage_object_never_raise() -> None:
    state = derive_subscription_state({"status": "active", "items": "junk"}, PRICES)
    assert state == StripeSubscriptionState(
        status=SubscriptionStatus.ACTIVE,
        plan=None,
        interval=None,
        current_period_end=None,
        trial_end=None,
        cancel_at=None,
        expires_at=None,
    )


def test_cancel_at_is_parsed() -> None:
    state = derive_subscription_state(_obj(cancel_at=1_950_000_000), PRICES)
    assert state.cancel_at == _dt(1_950_000_000)


def test_deleted_maps_to_canceled_regardless_of_status() -> None:
    state = derive_subscription_state(_obj(status="active"), PRICES, deleted=True)
    assert state.status is SubscriptionStatus.CANCELED


@pytest.mark.parametrize(
    ("stripe_status", "expected"),
    [
        ("unpaid", SubscriptionStatus.PAST_DUE),
        ("incomplete_expired", SubscriptionStatus.CANCELED),
        ("trialing", SubscriptionStatus.TRIALING),
    ],
)
def test_status_mapping(stripe_status: str, expected: SubscriptionStatus) -> None:
    assert derive_subscription_state(_obj(status=stripe_status), PRICES).status is expected
