"""Behavioural tests for FakeStripeGateway (SOLUSDEV-313): the shared test double must
mirror the real gateway's validation, idempotency and failure semantics."""

import pytest
from fixtures.stripe_fake import FakeStripeGateway
from solus_api.billing.stripe_gateway import (
    ADMIN_ACTION_METADATA_KEY,
    ADMIN_ACTOR_METADATA_KEY,
    StripeIdempotencyConflictError,
    StripeOperationError,
    StripeResourceMissingError,
    SubscriptionListTruncatedError,
)


@pytest.fixture
def fake() -> FakeStripeGateway:
    f = FakeStripeGateway()
    f.seed_subscription("sub_1", price_id="price_old")
    return f


async def test_change_price_updates_state_and_records_call(fake: FakeStripeGateway) -> None:
    snap = await fake.change_subscription_price(
        "sub_1",
        "price_new",
        proration="none",
        audit_action_id="a1",
        actor="s1",
        coupon_id="solus-comp-once",
        extra_metadata={"solus_comp_prev_price": "price_old"},
    )
    assert snap.price_id == "price_new"
    assert snap.coupon_id == "solus-comp-once"
    assert snap.metadata[ADMIN_ACTION_METADATA_KEY] == "a1"
    assert snap.metadata[ADMIN_ACTOR_METADATA_KEY] == "s1"
    assert snap.metadata["solus_comp_prev_price"] == "price_old"
    assert (await fake.retrieve_subscription("sub_1")).price_id == "price_new"
    assert len(fake.calls_to("change_subscription_price")) == 1


async def test_idempotent_replay_returns_same_result(fake: FakeStripeGateway) -> None:
    kw = {"proration": "none", "audit_action_id": "a1", "actor": "s1"}
    first = await fake.change_subscription_price("sub_1", "price_new", **kw)  # type: ignore[arg-type]
    second = await fake.change_subscription_price("sub_1", "price_new", **kw)  # type: ignore[arg-type]
    assert first == second


async def test_idempotency_key_reuse_with_different_params_conflicts(
    fake: FakeStripeGateway,
) -> None:
    kw = {"proration": "none", "audit_action_id": "a1", "actor": "s1"}
    await fake.change_subscription_price("sub_1", "price_new", **kw)  # type: ignore[arg-type]
    with pytest.raises(StripeIdempotencyConflictError):
        await fake.change_subscription_price("sub_1", "price_other", **kw)  # type: ignore[arg-type]


async def test_invalid_args_rejected_without_recording_a_call(fake: FakeStripeGateway) -> None:
    with pytest.raises(ValueError):
        await fake.change_subscription_price(
            "sub_1",
            "price_new",
            proration="bogus",  # type: ignore[arg-type]
            audit_action_id="a",
            actor="s",
        )
    with pytest.raises(ValueError):
        await fake.ensure_comp_coupon("repeating", 99)
    with pytest.raises(ValueError):
        await fake.apply_comp_coupon("sub_1", "SUMMER", "a", "s")
    assert fake.calls == []


async def test_failure_injection_next_then_recovers(fake: FakeStripeGateway) -> None:
    fake.fail_next("retrieve_subscription", FakeStripeGateway.connection_error())
    with pytest.raises(StripeOperationError) as ei:
        await fake.retrieve_subscription("sub_1")
    assert ei.value.retryable is True
    assert (await fake.retrieve_subscription("sub_1")).subscription_id == "sub_1"


async def test_failure_injection_always_and_clear(fake: FakeStripeGateway) -> None:
    fake.fail_always("remove_comp_coupon", FakeStripeGateway.idempotency_conflict())
    for _ in range(2):
        with pytest.raises(StripeIdempotencyConflictError):
            await fake.remove_comp_coupon("sub_1", "a", "s")
    fake.clear_failures()
    assert (await fake.remove_comp_coupon("sub_1", "a", "s")).coupon_id is None


async def test_unknown_subscription_is_resource_missing(fake: FakeStripeGateway) -> None:
    with pytest.raises(StripeResourceMissingError):
        await fake.retrieve_subscription("sub_nope")


async def test_coupon_apply_remove_and_ensure(fake: FakeStripeGateway) -> None:
    cid = await fake.ensure_comp_coupon("repeating", 3)
    assert cid == "solus-comp-repeating-3" and cid in fake.coupons
    assert await fake.ensure_comp_coupon("once") == "solus-comp-once"
    assert await fake.ensure_comp_coupon("forever") == "solus-comp-forever"
    assert (await fake.apply_comp_coupon("sub_1", cid, "a1", "s")).coupon_id == cid
    assert (await fake.remove_comp_coupon("sub_1", "a2", "s")).coupon_id is None


async def test_cancel_modes_and_already_canceled(fake: FakeStripeGateway) -> None:
    res = await fake.cancel_subscription(
        "sub_1",
        mode="period_end",
        invoice_now=False,
        prorate=False,
        audit_action_id="c1",
        actor="s",
    )
    assert res.subscription is not None and res.subscription.cancel_at_period_end is True
    res = await fake.cancel_subscription(
        "sub_1",
        mode="immediate",
        invoice_now=True,
        prorate=False,
        audit_action_id="c2",
        actor=None,
    )
    assert res.already_canceled is False
    assert res.subscription is not None and res.subscription.status == "canceled"
    again = await fake.cancel_subscription(
        "sub_1",
        mode="immediate",
        invoice_now=True,
        prorate=False,
        audit_action_id="c3",
        actor=None,
    )
    assert again.already_canceled is True
    missing = await fake.cancel_subscription(
        "sub_zzz",
        mode="immediate",
        invoice_now=True,
        prorate=False,
        audit_action_id="c4",
        actor=None,
    )
    assert missing.already_canceled is True and missing.subscription is None
    with pytest.raises(ValueError):
        await fake.cancel_subscription(
            "sub_1",
            mode="later",  # type: ignore[arg-type]
            invoice_now=True,
            prorate=False,
            audit_action_id="c5",
            actor=None,
        )


async def test_schedule_create_release_lifecycle(fake: FakeStripeGateway) -> None:
    res = await fake.create_revert_schedule(
        "sub_1", "price_orig", comp_months=2, audit_action_id="s1", actor="s"
    )
    assert res.schedule_id is not None and res.revert_price_id == "price_orig"
    assert await fake.find_schedule_for_subscription("sub_1") == res.schedule_id
    released = await fake.release_subscription_schedule("sub_1", "s2", "s")
    assert released.already_released is False and released.schedule_id == res.schedule_id
    assert await fake.find_schedule_for_subscription("sub_1") is None
    again = await fake.release_subscription_schedule("sub_1", "s3", "s")
    assert again.already_released is True


async def test_release_by_schedule_id_and_unknown_schedule(fake: FakeStripeGateway) -> None:
    res = await fake.create_revert_schedule(
        "sub_1", "price_orig", comp_months=1, audit_action_id="s1", actor="s"
    )
    assert res.schedule_id is not None
    out = await fake.release_subscription_schedule(res.schedule_id, "s2", "s")
    assert out.subscription_id == "sub_1" and out.already_released is False
    ghost = await fake.release_subscription_schedule("sub_sched_ghost", "s3", "s")
    assert ghost.already_released is True
    with pytest.raises(ValueError):
        await fake.release_subscription_schedule("cus_1", "s4", "s")


async def test_customer_and_checkout_parity(fake: FakeStripeGateway) -> None:
    assert await fake.get_or_create_customer(existing="cus_old", email="a@b.co", user_id="u") == (
        "cus_old"
    )
    assert (
        await fake.get_or_create_customer(existing=None, email="a@b.co", user_id="u")
    ).startswith("cus_")
    assert (await fake.create_checkout_session(mode="payment")).startswith("https://")
    assert (await fake.create_portal_session(customer="cus_1", return_url="https://x")).startswith(
        "https://"
    )


async def test_list_customer_subscriptions_returns_only_live_ones_of_that_customer() -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription("sub_a", customer_id="cus_1")
    fake.seed_subscription("sub_b", customer_id="cus_1", status="canceled")
    fake.seed_subscription("sub_c", customer_id="cus_2")
    fake.seed_subscription("sub_d", customer_id="cus_1", status="incomplete_expired")
    fake.seed_subscription("sub_e", customer_id="cus_1", status="past_due")
    assert await fake.list_customer_subscriptions("cus_1") == ["sub_a", "sub_e"]
    assert [c.args for c in fake.calls_to("list_customer_subscriptions")] == [("cus_1",)]


async def test_list_customer_subscriptions_validates_and_injects_failures() -> None:
    fake = FakeStripeGateway()
    with pytest.raises(ValueError):
        await fake.list_customer_subscriptions("sub_1")
    fake.fail_next("list_customer_subscriptions", FakeStripeGateway.connection_error())
    with pytest.raises(StripeOperationError):
        await fake.list_customer_subscriptions("cus_1")
    assert await fake.list_customer_subscriptions("cus_1") == []


async def test_listing_helpers_hide_and_truncate() -> None:
    fake = FakeStripeGateway()
    for sub in ("sub_a", "sub_b", "sub_c"):
        fake.seed_subscription(sub, customer_id="cus_1")
    fake.hide_from_listing("sub_b")
    assert await fake.list_customer_subscriptions("cus_1") == ["sub_a", "sub_c"]
    assert (await fake.retrieve_subscription("sub_b")).subscription_id == "sub_b"
    fake.truncate_listing_after(1)
    with pytest.raises(SubscriptionListTruncatedError) as err:
        await fake.list_customer_subscriptions("cus_1")
    assert err.value.partial == ["sub_a"] and err.value.retryable is True


async def test_seeded_coupon_ids_and_coupon_changes_stay_in_sync() -> None:
    fake = FakeStripeGateway()
    snap = fake.seed_subscription("sub_1", coupon_ids=("promo_x", "solus-comp-once"))
    assert snap.coupon_id == "solus-comp-once" and snap.coupon_ids == ("promo_x", "solus-comp-once")
    plain = fake.seed_subscription("sub_2", coupon_id="solus-comp-forever")
    assert plain.coupon_ids == ("solus-comp-forever",)
    applied = await fake.apply_comp_coupon("sub_1", "solus-comp-forever", "a1", "s")
    assert applied.coupon_ids == ("solus-comp-forever",)
    cleared = await fake.remove_comp_coupon("sub_1", "a2", "s")
    assert cleared.coupon_ids == () and cleared.coupon_id is None
    assert fake.seed_subscription("sub_3", customer_id=None).customer_id is None
