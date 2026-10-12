"""Pure projections of staff billing operations (SOLUSDEV-313)."""

import uuid
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from fixtures.stripe_fake import FakeStripeGateway
from solus_api.billing.admin_projection import (
    bare_snapshot,
    comp_prev_price,
    detached,
    epoch_to_datetime,
    has_comp_coupon,
    is_stripe_backed,
    iso,
    local_outcome,
    stripe_outcome,
    view,
)
from solus_api.billing.stripe_gateway import (
    COMP_PREV_PRICE_METADATA_KEY,
    SubscriptionSnapshot,
)
from solus_api.models import PlanType, Subscription, SubscriptionStatus, default_limits

NOW = datetime(2026, 3, 1, tzinfo=UTC)
PRICES = {"pro:month": "price_pro"}


def _sub(**fields: object) -> Subscription:
    base: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "plan": PlanType.BASIC,
        "status": SubscriptionStatus.ACTIVE,
        "limits": default_limits(PlanType.BASIC),
    }
    return Subscription(**{**base, **fields})


def _snap(**fields: object) -> SubscriptionSnapshot:
    snap = FakeStripeGateway().seed_subscription("sub_p1", price_id="price_pro")
    return replace(snap, **fields)  # type: ignore[arg-type]


def test_iso_and_epoch() -> None:
    assert iso(None) is None and iso(NOW) == NOW.isoformat()
    assert epoch_to_datetime(None) is None and epoch_to_datetime(0) is None
    assert epoch_to_datetime(86400) == datetime(1970, 1, 2, tzinfo=UTC)


def test_is_stripe_backed() -> None:
    assert not is_stripe_backed(_sub())
    assert is_stripe_backed(_sub(stripe_subscription_id="sub_1"))
    assert not is_stripe_backed(
        _sub(stripe_subscription_id="sub_1", status=SubscriptionStatus.CANCELED)
    )


def test_detached_copies_without_mutating_the_original() -> None:
    sub = _sub(limits_override={"max_teams": 1})
    copy = detached(sub, plan=PlanType.PRO)
    assert copy.plan is PlanType.PRO and sub.plan is PlanType.BASIC
    assert copy.limits_override == {"max_teams": 1} and copy.limits == sub.limits


def test_view_projects_effective_values_and_snapshot_refs() -> None:
    sub = _sub(comp_plan=PlanType.PRO, limits_override={"max_teams": 9})
    out = view(sub, NOW, _snap(coupon_id="solus-comp-forever", schedule_id="sub_sched_1"))
    assert out.effective_plan == "pro" and out.comp_plan == "pro"
    assert out.limits_override == {"max_teams": 9}
    assert (out.stripe_price_id, out.stripe_coupon_id, out.stripe_schedule_id) == (
        "price_pro",
        "solus-comp-forever",
        "sub_sched_1",
    )
    assert view(_sub(), NOW).limits_override is None
    assert view(_sub(), NOW, _snap(), schedule_id="sub_sched_7").stripe_schedule_id == "sub_sched_7"


def test_local_outcome_is_frozen() -> None:
    out = local_outcome(_sub(), NOW, noop=True)
    assert out.noop and not out.converges and out.after_commit is None
    with pytest.raises(FrozenInstanceError):
        out.noop = False  # type: ignore[misc]


def test_stripe_outcome_projects_plan_from_price_and_merges_refs() -> None:
    out = stripe_outcome(_sub(), _snap(), NOW, PRICES, extra_refs={"schedule": "sub_sched_2"})
    assert out.converges and out.after.plan == "pro"
    assert out.after.effective_limits == default_limits(PlanType.PRO)
    assert out.refs["schedule"] == "sub_sched_2" and out.refs["subscription"] == "sub_p1"


def test_stripe_outcome_falls_back_to_the_local_plan_and_applies_status() -> None:
    sub = _sub(plan=PlanType.PRO)
    out = stripe_outcome(
        sub,
        _snap(price_id="price_unknown"),
        NOW,
        PRICES,
        status=SubscriptionStatus.CANCELED,
        cancel_at=NOW,
        noop=True,
    )
    assert out.after.plan == "pro" and out.after.status == "canceled" and out.noop
    assert out.after.cancel_at == NOW.isoformat()


def test_bare_snapshot_is_a_canceled_stand_in() -> None:
    snap = bare_snapshot("sub_gone")
    assert snap.status == "canceled" and snap.subscription_id == "sub_gone"


@pytest.mark.parametrize(
    ("coupon", "expected"),
    [
        ("solus-comp-once", True),
        ("solus-comp-forever", True),
        ("solus-comp-repeating-12", True),
        ("SPRING25", False),
        ("solus-comp-repeating-99x", False),
        (None, False),
    ],
)
def test_has_comp_coupon(coupon: str | None, expected: bool) -> None:
    assert has_comp_coupon(_snap(coupon_id=coupon)) is expected


def test_comp_prev_price_needs_both_the_coupon_and_the_marker() -> None:
    marker = {COMP_PREV_PRICE_METADATA_KEY: "price_old"}
    assert comp_prev_price(_snap(coupon_id="solus-comp-forever", metadata=marker)) == "price_old"
    assert comp_prev_price(_snap(coupon_id=None, metadata=marker)) is None  # stale marker
    assert comp_prev_price(_snap(coupon_id="solus-comp-forever", metadata={})) is None
    assert (
        comp_prev_price(
            _snap(coupon_id="solus-comp-forever", metadata={COMP_PREV_PRICE_METADATA_KEY: ""})
        )
        is None
    )


def test_a_comp_coupon_is_found_among_several_discounts() -> None:
    both = _snap(coupon_id="promo_x", coupon_ids=("promo_x", "solus-comp-forever"))
    assert has_comp_coupon(both)
    assert not has_comp_coupon(_snap(coupon_id="promo_x", coupon_ids=("promo_x",)))
    assert not has_comp_coupon(_snap(coupon_id=None, coupon_ids=()))
    # Backwards compatible: a snapshot built with only `coupon_id` still works.
    assert has_comp_coupon(_snap(coupon_id="solus-comp-once", coupon_ids=()))


def test_comp_prev_price_survives_a_promo_listed_before_the_comp() -> None:
    snap = _snap(
        coupon_id="promo_x",
        coupon_ids=("promo_x", "solus-comp-forever"),
        metadata={COMP_PREV_PRICE_METADATA_KEY: "price_basic"},
    )
    assert comp_prev_price(snap) == "price_basic"
