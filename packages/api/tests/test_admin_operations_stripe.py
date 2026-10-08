"""Staff billing operations on STRIPE-BACKED subscriptions (SOLUSDEV-313 T6).

Stripe is the source of truth: the local row must stay untouched (the webhook
converges it) and `after` is projected from the Stripe snapshot."""

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fixtures.stripe_fake import FakeStripeGateway
from solus_api.billing import admin_operations
from solus_api.billing.admin_operations import (
    AdminBillingOperations,
    AdminOperationTimeoutError,
    InvalidOperation,
    NotCompedError,
)
from solus_api.billing.stripe_gateway import (
    COMP_PLAN_METADATA_KEY,
    COMP_PREV_PRICE_METADATA_KEY,
    StripeIdempotencyConflictError,
    StripeOperationError,
)
from solus_api.core.config import Settings
from solus_api.models import (
    CreditLedger,
    DataEvent,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
REASON = "goodwill for outage, contact pat@example.com"
SUB = "sub_test1"
BASIC_M, PRO_M, PRO_Y = "pricebasicm", "priceprom", "priceproy"
PRICES = {
    "basic:month": f"price_{BASIC_M}",
    "pro:month": f"price_{PRO_M}",
    "pro:year": f"price_{PRO_Y}",
}
BASIC_P, PRO_P = PRICES["basic:month"], PRICES["pro:month"]
Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
def maker(engine: Any) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def cfg(settings: Settings) -> Settings:
    return settings.model_copy(update={"stripe_plan_prices": PRICES})


@pytest.fixture
def fake() -> FakeStripeGateway:
    gw = FakeStripeGateway()
    gw.seed_subscription(SUB, price_id=BASIC_P)
    return gw


async def _user(
    maker: Maker, *, sub_id: str = SUB, consent: bool = False, **fields: Any
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
                plan=PlanType.BASIC,
                status=SubscriptionStatus.ACTIVE,
                limits=default_limits(PlanType.BASIC),
                stripe_subscription_id=sub_id,
                stripe_customer_id="cus_fake",
                **fields,
            )
        )
        await s.commit()
    return uid


async def _row(maker: Maker, uid: uuid.UUID) -> dict[str, Any]:
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None
    return {
        c.name: getattr(sub, c.name)
        for c in Subscription.__table__.columns
        if c.name != "updated_at"
    }


def _ops(s: AsyncSession, cfg: Settings, fake: FakeStripeGateway) -> AdminBillingOperations:
    return AdminBillingOperations(s, fake, cfg, now=lambda: NOW)


def _audit(n: int = 1) -> dict[str, Any]:
    return {"actor_staff_user_id": ACTOR, "audit_action_id": f"audit-{n}", "reason": REASON}


async def _run(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway, op: str, uid: Any, **kw: Any
) -> Any:
    async with maker() as s:
        return await getattr(_ops(s, cfg, fake), op)(uid, **kw)


# ---------------------------------------------------------------- change_plan
@pytest.mark.parametrize("proration", ["create_prorations", "none", "always_invoice"])
async def test_change_plan_swaps_price_passes_proration_and_leaves_row_alone(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway, proration: str
) -> None:
    uid = await _user(maker)
    before_row = await _row(maker, uid)
    res = await _run(
        maker,
        cfg,
        fake,
        "change_plan",
        uid,
        plan=PlanType.PRO,
        interval="month",
        proration=proration,
        **_audit(),
    )
    (call,) = fake.calls_to("change_subscription_price")
    assert call.args == (SUB, PRO_P)
    assert call.kwargs["proration"] == proration
    assert call.kwargs["audit_action_id"] == "audit-1"
    assert call.kwargs["actor"] == f"staff:{ACTOR}"
    assert "solus-admin-audit-1-change-price" in fake._idem_store
    assert await _row(maker, uid) == before_row  # webhook converges the local row
    assert res.converges_via_webhook and not res.noop
    assert (res.before.plan, res.after.plan) == ("basic", "pro")
    assert res.after.effective_limits == default_limits(PlanType.PRO)
    assert res.after.stripe_price_id == PRO_P
    assert res.stripe_refs["subscription"] == SUB and res.stripe_refs["price"] == PRO_P


async def test_change_plan_default_proration_and_yearly_price(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="year", **_audit())
    (call,) = fake.calls_to("change_subscription_price")
    assert call.args[1] == f"price_{PRO_Y}"
    assert call.kwargs["proration"] == "create_prorations"


async def test_change_plan_projection_merges_override_over_new_plan_defaults(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker, limits_override={"max_projects": 99})
    res = await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
    )
    assert res.after.effective_limits == {**default_limits(PlanType.PRO), "max_projects": 99}


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"plan": PlanType.PRO}, "interval"),
        ({"plan": PlanType.PRO, "interval": "week"}, "interval"),
        ({"plan": PlanType.ENTERPRISE, "interval": "month"}, "price"),
        ({"plan": PlanType.BASIC, "interval": "year"}, "price"),  # unmapped in config
        ({"plan": PlanType.PRO, "interval": "month", "proration": "bogus"}, "proration"),
    ],
)
async def test_change_plan_stripe_validation(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway, kwargs: dict[str, Any], match: str
) -> None:
    uid = await _user(maker)
    with pytest.raises(InvalidOperation, match=match):
        await _run(maker, cfg, fake, "change_plan", uid, **kwargs, **_audit())
    assert fake.calls_to("change_subscription_price") == []


async def test_change_plan_releases_schedule_before_price_change(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(SUB, price_id=BASIC_P, schedule_id="sub_sched_9")
    fake.schedules["sub_sched_9"] = None  # type: ignore[assignment]
    uid = await _user(maker)
    await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
    )
    order = [c.method for c in fake.calls]
    assert order.index("release_subscription_schedule") < order.index("change_subscription_price")
    assert fake.subscriptions[SUB].schedule_id is None


async def test_change_plan_noop_when_price_already_target(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker, consent=True)
    res = await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.BASIC, interval="month", **_audit()
    )
    assert res.noop and fake.calls_to("change_subscription_price") == []
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(DataEvent)) == 0


async def test_change_plan_retry_with_same_audit_id_is_safe_and_equal(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    kw = {"plan": PlanType.PRO, "interval": "month", **_audit()}
    first = await _run(maker, cfg, fake, "change_plan", uid, **kw)
    second = await _run(maker, cfg, fake, "change_plan", uid, **kw)
    assert second.after.plan == first.after.plan == "pro"
    assert not second.noop
    assert fake.subscriptions[SUB].price_id == PRO_P


async def test_idempotency_conflict_stays_distinguishable(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
    )
    with pytest.raises(StripeIdempotencyConflictError):
        await _run(
            maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="year", **_audit()
        )


async def test_stripe_failure_propagates_without_events_or_local_writes(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker, consent=True)
    before_row = await _row(maker, uid)
    fake.fail_next("change_subscription_price", FakeStripeGateway.connection_error())
    with pytest.raises(StripeOperationError):
        await _run(
            maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
        )
    assert await _row(maker, uid) == before_row
    # the row lock was released: a later op on the same row proceeds
    await _run(maker, cfg, fake, "set_limits_override", uid, limits={"max_teams": 1}, **_audit(2))
    async with maker() as s:
        types = (await s.scalars(select(DataEvent.event_type))).all()
    assert types == ["subscription.admin_changed"]  # only the successful override


async def test_stripe_calls_never_carry_reason_or_email(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="repeating",
        months=2,
        interval="month",
        **_audit(),
    )
    await _run(maker, cfg, fake, "cancel_subscription", uid, immediate=True, **_audit(2))
    blob = repr([(c.method, c.args, dict(c.kwargs)) for c in fake.calls]) + repr(fake.subscriptions)
    assert "pat@example.com" not in blob and "goodwill" not in blob
    assert "@" not in blob


# ----------------------------------------------------------------- comp_upgrade
async def test_comp_upgrade_repeating_applies_coupon_metadata_and_revert_schedule(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    before_row = await _row(maker, uid)
    res = await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="repeating",
        months=3,
        interval="month",
        **_audit(),
    )
    (change,) = fake.calls_to("change_subscription_price")
    assert change.args == (SUB, PRO_P)
    assert change.kwargs["coupon_id"] == "solus-comp-repeating-3"
    assert change.kwargs["proration"] == "none"
    assert change.kwargs["extra_metadata"] == {
        COMP_PREV_PRICE_METADATA_KEY: BASIC_P,
        COMP_PLAN_METADATA_KEY: "pro",
    }
    (sched,) = fake.calls_to("create_revert_schedule")
    assert sched.args == (SUB, BASIC_P) and sched.kwargs["comp_months"] == 3
    assert await _row(maker, uid) == before_row
    assert res.converges_via_webhook and res.after.plan == "pro"
    assert res.after.stripe_coupon_id == "solus-comp-repeating-3"
    assert (
        res.after.stripe_schedule_id and res.stripe_refs["schedule"] == res.after.stripe_schedule_id
    )
    async with maker() as s:  # Stripe-backed comps never grant local credits
        assert await s.scalar(select(func.count()).select_from(CreditLedger)) == 0


@pytest.mark.parametrize(
    ("duration", "months", "coupon", "revert_months"),
    [("once", None, "solus-comp-once", 1), ("forever", None, "solus-comp-forever", None)],
)
async def test_comp_upgrade_once_and_forever(
    maker: Maker,
    cfg: Settings,
    fake: FakeStripeGateway,
    duration: str,
    months: Any,
    coupon: str,
    revert_months: int | None,
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration=duration,
        months=months,
        interval="month",
        proration="always_invoice",
        **_audit(),
    )
    assert fake.calls_to("change_subscription_price")[0].kwargs["coupon_id"] == coupon
    assert fake.calls_to("change_subscription_price")[0].kwargs["proration"] == "always_invoice"
    scheds = fake.calls_to("create_revert_schedule")
    if revert_months is None:
        assert scheds == []
    else:
        assert scheds[0].kwargs["comp_months"] == revert_months


async def test_recomp_preserves_the_original_previous_price(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="forever",
        interval="month",
        **_audit(1),
    )
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="repeating",
        months=2,
        interval="year",
        **_audit(2),
    )
    second = fake.calls_to("change_subscription_price")[1]
    assert second.kwargs["extra_metadata"][COMP_PREV_PRICE_METADATA_KEY] == BASIC_P
    assert fake.calls_to("create_revert_schedule")[0].args == (SUB, BASIC_P)


async def test_comp_upgrade_releases_existing_schedule_first(maker: Maker, cfg: Settings) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(SUB, price_id=BASIC_P, schedule_id="sub_sched_9")
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="once",
        interval="month",
        **_audit(),
    )
    order = [c.method for c in fake.calls]
    assert order.index("release_subscription_schedule") < order.index("change_subscription_price")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration": "repeating"},
        {"duration": "repeating", "months": 37},
        {"duration": "once", "months": 2},
        {"duration": "nope"},
        {"duration": "forever", "interval": None},
        {"duration": "forever", "plan": PlanType.ENTERPRISE},
    ],
)
async def test_comp_upgrade_stripe_validation(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway, kwargs: dict[str, Any]
) -> None:
    uid = await _user(maker)
    args = {"plan": PlanType.PRO, "interval": "month", **kwargs}
    with pytest.raises(InvalidOperation):
        await _run(maker, cfg, fake, "comp_upgrade", uid, **args, **_audit())
    assert fake.calls_to("change_subscription_price") == []


async def test_comp_upgrade_retry_same_audit_id_is_safe(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    kw = {
        "plan": PlanType.PRO,
        "duration": "repeating",
        "months": 2,
        "interval": "month",
        **_audit(),
    }
    first = await _run(maker, cfg, fake, "comp_upgrade", uid, **kw)
    second = await _run(maker, cfg, fake, "comp_upgrade", uid, **kw)
    assert second.after.stripe_price_id == first.after.stripe_price_id
    assert fake.subscriptions[SUB].metadata[COMP_PREV_PRICE_METADATA_KEY] == BASIC_P
    assert len(fake.schedules) == 1


# ------------------------------------------------------------------ remove_comp
async def test_remove_comp_restores_price_removes_coupon_and_clears_markers(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="repeating",
        months=2,
        interval="month",
        **_audit(1),
    )
    res = await _run(
        maker, cfg, fake, "remove_comp", uid, proration="create_prorations", **_audit(2)
    )
    snap = fake.subscriptions[SUB]
    assert snap.price_id == BASIC_P and snap.coupon_id is None and snap.schedule_id is None
    assert not snap.metadata[COMP_PREV_PRICE_METADATA_KEY]
    assert not snap.metadata[COMP_PLAN_METADATA_KEY]
    back = fake.calls_to("change_subscription_price")[-1]
    assert back.args == (SUB, BASIC_P) and back.kwargs["proration"] == "create_prorations"
    assert back.kwargs["extra_metadata"] == {
        COMP_PREV_PRICE_METADATA_KEY: "",
        COMP_PLAN_METADATA_KEY: "",
    }
    order = [c.method for c in fake.calls]
    assert order.index("release_subscription_schedule") > order.index("create_revert_schedule")
    assert res.after.plan == "basic" and res.converges_via_webhook


async def test_remove_comp_on_uncomped_stripe_sub_errors(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    with pytest.raises(NotCompedError):
        await _run(maker, cfg, fake, "remove_comp", uid, **_audit())
    assert fake.calls_to("change_subscription_price") == []


async def test_remove_comp_retry_after_success_is_a_noop_not_an_error(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="forever",
        interval="month",
        **_audit(1),
    )
    await _run(maker, cfg, fake, "remove_comp", uid, **_audit(2))
    again = await _run(maker, cfg, fake, "remove_comp", uid, **_audit(2))
    assert again.noop
    assert fake.subscriptions[SUB].price_id == BASIC_P


async def test_remove_comp_retry_finishes_a_half_done_attempt(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="forever",
        interval="month",
        **_audit(1),
    )
    fake.fail_next("remove_comp_coupon", FakeStripeGateway.connection_error())
    with pytest.raises(StripeOperationError):
        await _run(maker, cfg, fake, "remove_comp", uid, **_audit(2))
    assert fake.subscriptions[SUB].coupon_id is not None
    done = await _run(maker, cfg, fake, "remove_comp", uid, **_audit(2))
    assert fake.subscriptions[SUB].coupon_id is None and not done.noop


# ----------------------------------------------------------------------- cancel
@pytest.mark.parametrize(("invoice_now", "prorate"), [(False, False), (True, True)])
async def test_cancel_immediate(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway, invoice_now: bool, prorate: bool
) -> None:
    uid = await _user(maker)
    before_row = await _row(maker, uid)
    res = await _run(
        maker,
        cfg,
        fake,
        "cancel_subscription",
        uid,
        immediate=True,
        invoice_now=invoice_now,
        prorate=prorate,
        **_audit(),
    )
    (call,) = fake.calls_to("cancel_subscription")
    assert call.kwargs["mode"] == "immediate"
    assert (call.kwargs["invoice_now"], call.kwargs["prorate"]) == (invoice_now, prorate)
    assert call.kwargs["actor"] == f"staff:{ACTOR}"
    assert await _row(maker, uid) == before_row
    assert res.after.status == "canceled" and res.converges_via_webhook and not res.noop
    assert "solus-admin-audit-1-cancel" in fake._idem_store


async def test_cancel_period_end_projects_cancel_at(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    res = await _run(maker, cfg, fake, "cancel_subscription", uid, immediate=False, **_audit())
    assert fake.calls_to("cancel_subscription")[0].kwargs["mode"] == "period_end"
    assert res.after.status == "active"
    assert res.after.cancel_at is not None
    assert datetime.fromisoformat(res.after.cancel_at).tzinfo is not None


async def test_cancel_releases_schedule_first_and_tolerates_already_canceled(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(SUB, price_id=BASIC_P, schedule_id="sub_sched_9")
    uid = await _user(maker)
    await _run(maker, cfg, fake, "cancel_subscription", uid, immediate=True, **_audit(1))
    order = [c.method for c in fake.calls]
    assert order.index("release_subscription_schedule") < order.index("cancel_subscription")
    again = await _run(maker, cfg, fake, "cancel_subscription", uid, immediate=True, **_audit(2))
    assert again.noop


async def test_cancel_when_stripe_subscription_is_gone_is_a_noop(
    maker: Maker, cfg: Settings
) -> None:
    uid = await _user(maker, sub_id="sub_gone9")
    res = await _run(
        maker, cfg, FakeStripeGateway(), "cancel_subscription", uid, immediate=True, **_audit()
    )
    assert res.noop and res.after.status == "canceled"


async def test_cancel_args_validated(maker: Maker, cfg: Settings, fake: FakeStripeGateway) -> None:
    uid = await _user(maker)
    with pytest.raises(InvalidOperation):
        await _run(
            maker,
            cfg,
            fake,
            "cancel_subscription",
            uid,
            immediate=True,
            invoice_now="yes",
            **_audit(),
        )
    assert fake.calls == []


# ------------------------------------------------- limits override / isolation
async def test_limits_override_on_stripe_backed_never_touches_stripe(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    res = await _run(
        maker, cfg, fake, "set_limits_override", uid, limits={"max_projects": 12}, **_audit()
    )
    assert fake.calls == [] and not res.converges_via_webhook
    assert (await _row(maker, uid))["limits_override"] == {"max_projects": 12}


async def test_stripe_ops_only_touch_the_targets_own_subscription(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription("sub_aaa1", price_id=BASIC_P)
    fake.seed_subscription("sub_bbb2", price_id=BASIC_P)
    a, b = await _user(maker, sub_id="sub_aaa1"), await _user(maker, sub_id="sub_bbb2")
    before_b = await _row(maker, b)
    await _run(maker, cfg, fake, "change_plan", a, plan=PlanType.PRO, interval="month", **_audit(1))
    await _run(maker, cfg, fake, "cancel_subscription", a, immediate=True, **_audit(2))
    assert fake.subscriptions["sub_bbb2"].price_id == BASIC_P
    assert fake.subscriptions["sub_bbb2"].status == "active"
    assert {c.args[0] for c in fake.calls if c.args} == {"sub_aaa1"}
    assert await _row(maker, b) == before_b


async def test_stripe_event_and_json_result(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker, consent=True)
    res = await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
    )
    async with maker() as s:
        (ev,) = (await s.scalars(select(DataEvent))).all()
    assert ev.payload["operation"] == "change_plan" and ev.payload["audit_action_id"] == "audit-1"
    assert "goodwill" not in json.dumps(ev.payload) and "@" not in json.dumps(ev.payload)
    data = json.loads(json.dumps(res.to_dict()))
    assert data["after"]["stripe_price_id"] == PRO_P and data["converges_via_webhook"] is True


# ------------------------------------------------- M-1: customer ownership check
OTHER_CUSTOMER = "cus_someone_else"
_CUSTOMER_OPS: list[tuple[str, dict[str, Any]]] = [
    ("change_plan", {"plan": PlanType.PRO, "interval": "month"}),
    ("comp_upgrade", {"plan": PlanType.PRO, "duration": "forever", "interval": "month"}),
    ("remove_comp", {}),
    ("cancel_subscription", {"immediate": True}),
]
_WRITES = (
    "change_subscription_price",
    "ensure_comp_coupon",
    "remove_comp_coupon",
    "cancel_subscription",
    "create_revert_schedule",
    "release_subscription_schedule",
)


@pytest.mark.parametrize(("op", "kwargs"), _CUSTOMER_OPS)
async def test_every_stripe_op_refuses_a_subscription_of_another_customer(
    maker: Maker, cfg: Settings, op: str, kwargs: dict[str, Any]
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(
        SUB,
        price_id=BASIC_P,
        customer_id=OTHER_CUSTOMER,
        coupon_id="solus-comp-forever",
        schedule_id="sub_sched_9",
        metadata={COMP_PREV_PRICE_METADATA_KEY: BASIC_P},
    )
    uid = await _user(maker, consent=True)
    before_row = await _row(maker, uid)
    with pytest.raises(InvalidOperation) as exc:
        await _run(maker, cfg, fake, op, uid, **kwargs, **_audit())
    assert exc.value.code == "invalid_operation"
    leaked = repr(exc.value.context) + exc.value.message
    assert OTHER_CUSTOMER not in leaked and "cus_fake" not in leaked
    assert [c for c in fake.calls if c.method in _WRITES] == []
    assert await _row(maker, uid) == before_row
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(DataEvent)) == 0


# --------------------------------------------- M-2: comp state vs plan changes
async def test_change_plan_refuses_while_comped(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="forever",
        interval="month",
        **_audit(1),
    )
    calls_before = len(fake.calls_to("change_subscription_price"))
    with pytest.raises(InvalidOperation, match="remove the comp first"):
        await _run(
            maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="year", **_audit(2)
        )
    assert len(fake.calls_to("change_subscription_price")) == calls_before
    assert fake.calls_to("release_subscription_schedule") == []


async def test_change_plan_after_natural_comp_end_clears_stale_metadata(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(  # comp ended naturally: no coupon, markers left behind
        SUB,
        price_id=BASIC_P,
        metadata={COMP_PREV_PRICE_METADATA_KEY: "price_stale", COMP_PLAN_METADATA_KEY: "pro"},
    )
    uid = await _user(maker)
    await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
    )
    (call,) = fake.calls_to("change_subscription_price")
    assert call.kwargs["extra_metadata"] == {
        COMP_PREV_PRICE_METADATA_KEY: "",
        COMP_PLAN_METADATA_KEY: "",
    }
    assert not fake.subscriptions[SUB].metadata[COMP_PREV_PRICE_METADATA_KEY]


async def test_change_plan_without_markers_sends_no_metadata(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    uid = await _user(maker)
    await _run(
        maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
    )
    (call,) = fake.calls_to("change_subscription_price")
    assert call.kwargs["extra_metadata"] == {}


async def test_remove_comp_with_stale_metadata_after_natural_end_is_not_comped(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(
        SUB,
        price_id=PRO_P,  # the customer was legitimately moved to pro since
        metadata={COMP_PREV_PRICE_METADATA_KEY: BASIC_P, COMP_PLAN_METADATA_KEY: "pro"},
    )
    uid = await _user(maker)
    with pytest.raises(NotCompedError):
        await _run(maker, cfg, fake, "remove_comp", uid, **_audit())
    assert fake.calls_to("change_subscription_price") == []
    assert fake.subscriptions[SUB].price_id == PRO_P


async def test_remove_comp_with_coupon_but_no_prev_price_is_not_comped(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(SUB, price_id=BASIC_P, coupon_id="solus-comp-forever")
    uid = await _user(maker)
    with pytest.raises(NotCompedError):
        await _run(maker, cfg, fake, "remove_comp", uid, **_audit())
    assert fake.calls_to("change_subscription_price") == []


async def test_remove_comp_ignores_a_non_comp_coupon(maker: Maker, cfg: Settings) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(
        SUB,
        price_id=PRO_P,
        coupon_id="SPRING25",
        metadata={COMP_PREV_PRICE_METADATA_KEY: BASIC_P},
    )
    uid = await _user(maker)
    with pytest.raises(NotCompedError):
        await _run(maker, cfg, fake, "remove_comp", uid, **_audit())
    assert fake.calls_to("remove_comp_coupon") == []


async def test_comp_upgrade_ignores_stale_prev_price_when_not_currently_comped(
    maker: Maker, cfg: Settings
) -> None:
    fake = FakeStripeGateway()
    fake.seed_subscription(
        SUB, price_id=PRO_P, metadata={COMP_PREV_PRICE_METADATA_KEY: "price_stale"}
    )
    uid = await _user(maker)
    await _run(
        maker,
        cfg,
        fake,
        "comp_upgrade",
        uid,
        plan=PlanType.PRO,
        duration="once",
        interval="year",
        **_audit(),
    )
    (change,) = fake.calls_to("change_subscription_price")
    assert change.kwargs["extra_metadata"][COMP_PREV_PRICE_METADATA_KEY] == PRO_P


# ------------------------------------------------------ M-5: bounded under lock
class _HangingGateway(FakeStripeGateway):
    async def retrieve_subscription(self, sub_id: str) -> Any:
        await asyncio.sleep(30)
        return await super().retrieve_subscription(sub_id)


@pytest.mark.parametrize(("op", "kwargs"), _CUSTOMER_OPS)
async def test_a_hanging_stripe_call_times_out_rolls_back_and_frees_the_lock(
    maker: Maker,
    cfg: Settings,
    monkeypatch: pytest.MonkeyPatch,
    op: str,
    kwargs: dict[str, Any],
) -> None:
    monkeypatch.setattr(admin_operations, "OPERATION_TIMEOUT_SECONDS", 0.05)
    hanging = _HangingGateway()
    hanging.seed_subscription(SUB, price_id=BASIC_P)
    uid = await _user(maker, consent=True)
    before_row = await _row(maker, uid)
    with pytest.raises(AdminOperationTimeoutError) as exc:
        await _run(maker, cfg, hanging, op, uid, **kwargs, **_audit())
    assert exc.value.code == "operation_timeout" and exc.value.retryable is True
    assert exc.value.context["operation"] == op
    assert await _row(maker, uid) == before_row
    # the FOR UPDATE lock is gone: another op on the same row proceeds immediately
    await asyncio.wait_for(
        _run(maker, cfg, hanging, "set_limits_override", uid, limits={"max_teams": 1}, **_audit(2)),
        timeout=5,
    )


async def test_a_timeout_raised_by_the_gateway_itself_is_not_our_deadline(
    maker: Maker, cfg: Settings, fake: FakeStripeGateway
) -> None:
    fake.fail_next("retrieve_subscription", TimeoutError("gateway-level"))
    uid = await _user(maker)
    with pytest.raises(TimeoutError, match="gateway-level"):
        await _run(
            maker, cfg, fake, "change_plan", uid, plan=PlanType.PRO, interval="month", **_audit()
        )


async def test_comp_upgrade_needs_a_current_price_to_revert_to(maker: Maker, cfg: Settings) -> None:
    fake = FakeStripeGateway()
    snap = fake.seed_subscription(SUB)
    fake.subscriptions[SUB] = replace(snap, price_id=None)
    uid = await _user(maker)
    with pytest.raises(InvalidOperation, match="no current price"):
        await _run(
            maker,
            cfg,
            fake,
            "comp_upgrade",
            uid,
            plan=PlanType.PRO,
            duration="forever",
            interval="month",
            **_audit(),
        )
    assert fake.calls_to("change_subscription_price") == []
