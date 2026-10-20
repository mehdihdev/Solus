"""Unit tests for the outbound Stripe gateway (SOLUSDEV-83 follow-up).

No network: the stripe.* async classmethods are monkeypatched, and the SecretStore
is a fake. Asserts the gateway sources the key from the SecretStore, passes the
right params, and raises BillingUnconfiguredError when no key is provisioned.
"""

from typing import Any

import pytest
import stripe
from solus_api.billing.stripe_gateway import (
    STRIPE_API_KEY_NAME,
    BillingUnconfiguredError,
    StripeGateway,
    SubscriptionListTruncatedError,
)
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore


class _FakeStore(SecretStore):
    def __init__(self, key: str | None) -> None:
        self._key = key

    async def get(self, ref: str) -> str:
        if self._key is None or ref != STRIPE_API_KEY_NAME:
            raise SecretNotFoundError(ref)
        return self._key

    async def put(self, ref: str, value: str) -> None:  # pragma: no cover - unused by gateway
        raise NotImplementedError

    async def delete(self, ref: str) -> None:  # pragma: no cover - unused by gateway
        raise NotImplementedError


class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    async def fake_customer_create(**params: Any) -> _Obj:
        calls["customer"] = params
        return _Obj(id="cus_new")

    async def fake_session_create(**params: Any) -> _Obj:
        calls["checkout"] = params
        return _Obj(id="cs_1", url="https://checkout.stripe.com/c/cs_1")

    async def fake_portal_create(**params: Any) -> _Obj:
        calls["portal"] = params
        return _Obj(id="bps_1", url="https://billing.stripe.com/p/bps_1")

    monkeypatch.setattr(stripe.Customer, "create_async", fake_customer_create)
    monkeypatch.setattr(stripe.checkout.Session, "create_async", fake_session_create)
    monkeypatch.setattr(stripe.billing_portal.Session, "create_async", fake_portal_create)
    return calls


async def test_reuses_existing_customer_without_calling_stripe(captured: dict[str, Any]) -> None:
    gw = StripeGateway(_FakeStore("sk_test_x"))
    cid = await gw.get_or_create_customer(existing="cus_old", email="a@b.co", user_id="u1")
    assert cid == "cus_old"
    assert "customer" not in captured  # no Stripe call


async def test_creates_customer_with_key_and_metadata(captured: dict[str, Any]) -> None:
    gw = StripeGateway(_FakeStore("sk_test_x"))
    cid = await gw.get_or_create_customer(existing=None, email="a@b.co", user_id="u1")
    assert cid == "cus_new"
    assert captured["customer"]["api_key"] == "sk_test_x"
    assert captured["customer"]["email"] == "a@b.co"
    assert captured["customer"]["metadata"] == {"solus_user_id": "u1"}


async def test_subscription_checkout_sets_trial_metadata_and_ref(captured: dict[str, Any]) -> None:
    gw = StripeGateway(_FakeStore("sk_test_x"))
    url = await gw.create_checkout_session(
        mode="subscription",
        price_id="price_bm",
        customer="cus_1",
        user_id="u1",
        success_url="https://ok",
        cancel_url="https://no",
        trial_days=14,
    )
    assert url == "https://checkout.stripe.com/c/cs_1"
    p = captured["checkout"]
    assert p["mode"] == "subscription"
    assert p["line_items"] == [{"price": "price_bm", "quantity": 1}]
    assert p["client_reference_id"] == "u1"
    assert p["metadata"] == {"solus_user_id": "u1", "price_id": "price_bm"}
    assert p["subscription_data"] == {"trial_period_days": 14}
    assert p["success_url"] == "https://ok"
    assert p["api_key"] == "sk_test_x"


async def test_payment_checkout_has_no_subscription_data(captured: dict[str, Any]) -> None:
    gw = StripeGateway(_FakeStore("sk_test_x"))
    await gw.create_checkout_session(
        mode="payment",
        price_id="price_pack10",
        customer="cus_1",
        user_id="u1",
        success_url="https://ok",
        cancel_url="https://no",
        trial_days=None,
    )
    assert "subscription_data" not in captured["checkout"]


async def test_portal_session_returns_url(captured: dict[str, Any]) -> None:
    gw = StripeGateway(_FakeStore("sk_test_x"))
    url = await gw.create_portal_session(customer="cus_1", return_url="https://back")
    assert url == "https://billing.stripe.com/p/bps_1"
    assert captured["portal"]["customer"] == "cus_1"
    assert captured["portal"]["return_url"] == "https://back"
    assert captured["portal"]["api_key"] == "sk_test_x"


async def test_missing_key_raises_billing_unconfigured() -> None:
    gw = StripeGateway(_FakeStore(None))
    with pytest.raises(BillingUnconfiguredError):
        await gw.get_or_create_customer(existing=None, email="a@b.co", user_id="u1")
    with pytest.raises(BillingUnconfiguredError):
        await gw.create_portal_session(customer="cus_1", return_url="https://back")


# --------------------------------------------------------------------------- #
# SOLUSDEV-313 T2: staff subscription operations
# --------------------------------------------------------------------------- #

from solus_api.billing.stripe_gateway import (  # noqa: E402
    ADMIN_ACTION_METADATA_KEY,
    ADMIN_ACTOR_METADATA_KEY,
    COMP_PLAN_METADATA_KEY,
    COMP_PREV_PRICE_METADATA_KEY,
    StripeIdempotencyConflictError,
    StripeOperationError,
    StripeResourceMissingError,
)

KEY = "sk_test_x"


def _sub(
    sub_id: str = "sub_1",
    *,
    price: str = "price_old",
    status: str = "active",
    schedule: str | None = None,
    discounts: list[Any] | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": sub_id,
        "customer": "cus_1",
        "status": status,
        "schedule": schedule,
        "cancel_at": None,
        "cancel_at_period_end": False,
        "latest_invoice": "in_1",
        "metadata": metadata or {},
        "discounts": discounts or [],
        "items": {
            "data": [
                {
                    "id": "si_1",
                    "quantity": 1,
                    "price": {"id": price},
                    "current_period_end": 1_900_000_000,
                }
            ]
        },
    }


class _Stripe:
    """Records every stripe.* call; per-op results/errors are settable."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.results: dict[str, Any] = {}
        self.errors: dict[str, list[Exception]] = {}

    def of(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(a, p) for n, a, p in self.calls if n == name]

    def one(self, name: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        found = self.of(name)
        assert len(found) == 1, f"{name}: {len(found)} calls"
        return found[0]

    def make(self, name: str, default: Any) -> Any:
        async def fn(*args: Any, **params: Any) -> Any:
            self.calls.append((name, args, params))
            queue = self.errors.get(name)
            if queue:
                raise queue.pop(0)
            return self.results.get(name, default)

        return fn


@pytest.fixture
def st(monkeypatch: pytest.MonkeyPatch) -> _Stripe:
    s = _Stripe()
    sched = {
        "id": "sub_sched_1",
        "status": "active",
        "subscription": "sub_1",
        "phases": [
            {
                "start_date": 1_800_000_000,
                "items": [{"price": "price_comped", "quantity": 1}],
                "discounts": [{"coupon": "solus-comp-once"}],
            }
        ],
    }
    patches: dict[str, tuple[Any, str, Any]] = {
        "sub.retrieve": (stripe.Subscription, "retrieve_async", _sub()),
        "sub.modify": (stripe.Subscription, "modify_async", _sub(price="price_new")),
        "sub.cancel": (stripe.Subscription, "cancel_async", _sub(status="canceled")),
        "cus.modify": (stripe.Customer, "modify_async", {"id": "cus_1"}),
        "coupon.create": (stripe.Coupon, "create_async", {"id": "x"}),
        "sched.create": (stripe.SubscriptionSchedule, "create_async", sched),
        "sched.modify": (stripe.SubscriptionSchedule, "modify_async", sched),
        "sched.retrieve": (stripe.SubscriptionSchedule, "retrieve_async", sched),
        "sched.release": (
            stripe.SubscriptionSchedule,
            "release_async",
            {**sched, "status": "released"},
        ),
    }
    for name, (cls, attr, default) in patches.items():
        monkeypatch.setattr(cls, attr, s.make(name, default))
    return s


def gw() -> StripeGateway:
    return StripeGateway(_FakeStore(KEY))


def _invalid(code: str | None, msg: str = "boom") -> stripe.InvalidRequestError:
    return stripe.InvalidRequestError(msg, param=None, code=code)  # type: ignore[no-untyped-call]


# ---- constants / retrieve ------------------------------------------------- #


def test_metadata_key_constants() -> None:
    assert ADMIN_ACTION_METADATA_KEY == "solus_admin_action_id"
    assert ADMIN_ACTOR_METADATA_KEY == "solus_actor"
    assert COMP_PREV_PRICE_METADATA_KEY == "solus_comp_prev_price"
    assert COMP_PLAN_METADATA_KEY == "solus_comp_plan"


async def test_retrieve_subscription_projects_stable_fields(st: _Stripe) -> None:
    st.results["sub.retrieve"] = _sub(
        schedule="sub_sched_9",
        discounts=[{"coupon": {"id": "solus-comp-forever"}}],
        metadata={"a": "b"},
    )
    snap = await gw().retrieve_subscription("sub_1")
    assert snap.subscription_id == "sub_1"
    assert snap.status == "active"
    assert snap.price_id == "price_old"
    assert snap.item_id == "si_1"
    assert snap.current_period_end == 1_900_000_000
    assert snap.coupon_id == "solus-comp-forever"
    assert snap.schedule_id == "sub_sched_9"
    assert snap.latest_invoice_id == "in_1"
    assert snap.metadata == {"a": "b"}
    assert snap.stripe_refs() == {
        "subscription": "sub_1",
        "customer": "cus_1",
        "price": "price_old",
        "coupon": "solus-comp-forever",
        "schedule": "sub_sched_9",
        "invoice": "in_1",
    }
    _, params = st.one("sub.retrieve")
    assert params["api_key"] == KEY
    assert "idempotency_key" not in params


async def test_snapshot_exposes_trial_end_and_interval(st: _Stripe) -> None:
    raw = _sub()
    raw["trial_end"] = 1_700_000_000
    raw["items"]["data"][0]["price"]["recurring"] = {"interval": "year"}
    st.results["sub.retrieve"] = raw
    snap = await gw().retrieve_subscription("sub_1")
    assert snap.trial_end == 1_700_000_000
    assert snap.interval == "year"


async def test_snapshot_trial_end_and_interval_default_to_none(st: _Stripe) -> None:
    snap = await gw().retrieve_subscription("sub_1")
    assert snap.trial_end is None
    assert snap.interval is None


async def test_retrieve_handles_source_coupon_and_unexpanded_discount(st: _Stripe) -> None:
    st.results["sub.retrieve"] = _sub(discounts=[{"source": {"coupon": "solus-comp-once"}}])
    assert (await gw().retrieve_subscription("sub_1")).coupon_id == "solus-comp-once"
    st.results["sub.retrieve"] = _sub(discounts=["di_unexpanded"])
    assert (await gw().retrieve_subscription("sub_1")).coupon_id is None


async def test_retrieve_missing_raises_resource_missing(st: _Stripe) -> None:
    st.errors["sub.retrieve"] = [_invalid("resource_missing")]
    with pytest.raises(StripeResourceMissingError):
        await gw().retrieve_subscription("sub_1")


# ---- change_subscription_price -------------------------------------------- #


@pytest.mark.parametrize("proration", ["create_prorations", "none", "always_invoice"])
async def test_change_price_single_modify_with_proration_passthrough(
    st: _Stripe, proration: str
) -> None:
    snap = await gw().change_subscription_price(
        "sub_1",
        "price_new",
        proration=proration,  # type: ignore[arg-type]
        audit_action_id="act1",
        actor="staff-7",
    )
    assert len(st.of("sub.modify")) == 1
    args, p = st.one("sub.modify")
    assert args == ("sub_1",)
    assert p["items"] == [{"id": "si_1", "price": "price_new"}]
    assert p["proration_behavior"] == proration
    assert p["idempotency_key"] == "solus-admin-act1-change-price"
    assert p["api_key"] == KEY
    assert p["metadata"] == {
        ADMIN_ACTION_METADATA_KEY: "act1",
        ADMIN_ACTOR_METADATA_KEY: "staff-7",
    }
    assert "discounts" not in p
    assert snap.price_id == "price_new"


async def test_change_price_with_coupon_and_extra_metadata_in_one_call(st: _Stripe) -> None:
    await gw().change_subscription_price(
        "sub_1",
        "price_new",
        proration="none",
        audit_action_id="act1",
        actor="staff-7",
        coupon_id="solus-comp-repeating-3",
        extra_metadata={COMP_PREV_PRICE_METADATA_KEY: "price_old"},
    )
    assert len(st.of("sub.modify")) == 1
    _, p = st.one("sub.modify")
    assert p["discounts"] == [{"coupon": "solus-comp-repeating-3"}]
    assert p["metadata"][COMP_PREV_PRICE_METADATA_KEY] == "price_old"
    assert p["metadata"][ADMIN_ACTION_METADATA_KEY] == "act1"


async def test_change_price_rejects_multi_item_subscription(st: _Stripe) -> None:
    sub = _sub()
    sub["items"]["data"].append({"id": "si_2", "price": {"id": "price_x"}})
    st.results["sub.retrieve"] = sub
    with pytest.raises(StripeOperationError):
        await gw().change_subscription_price(
            "sub_1", "price_new", proration="none", audit_action_id="a", actor="s"
        )
    assert not st.of("sub.modify")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"proration": "bogus"},
        {"audit_action_id": ""},
        {"audit_action_id": "x" * 200},
        {"audit_action_id": "a b"},
        {"actor": "bob@example.com"},
        {"actor": ""},
        {"coupon_id": "not-a-comp-coupon"},
        {"extra_metadata": {ADMIN_ACTOR_METADATA_KEY: "spoof"}},
        {"extra_metadata": {"k": "v" * 501}},
    ],
)
async def test_change_price_invalid_args_rejected_before_any_call(
    st: _Stripe, kwargs: dict[str, Any]
) -> None:
    base: dict[str, Any] = {"proration": "none", "audit_action_id": "a1", "actor": "s1"}
    with pytest.raises(ValueError):
        await gw().change_subscription_price("sub_1", "price_new", **{**base, **kwargs})
    assert st.calls == []


@pytest.mark.parametrize("sub_id,price_id", [("", "price_1"), ("cus_1", "price_1"), ("sub_1", "x")])
async def test_change_price_rejects_bad_ids(st: _Stripe, sub_id: str, price_id: str) -> None:
    with pytest.raises(ValueError):
        await gw().change_subscription_price(
            sub_id, price_id, proration="none", audit_action_id="a", actor="s"
        )
    assert st.calls == []


async def test_write_without_key_raises_unconfigured_and_never_calls(st: _Stripe) -> None:
    with pytest.raises(BillingUnconfiguredError):
        await StripeGateway(_FakeStore(None)).change_subscription_price(
            "sub_1", "price_new", proration="none", audit_action_id="a", actor="s"
        )
    assert st.calls == []


async def test_idempotency_mismatch_maps_to_typed_error(st: _Stripe) -> None:
    st.errors["sub.modify"] = [stripe.IdempotencyError("reused")]
    with pytest.raises(StripeIdempotencyConflictError):
        await gw().change_subscription_price(
            "sub_1", "price_new", proration="none", audit_action_id="a", actor="s"
        )


async def test_other_stripe_errors_wrapped_and_key_not_leaked(st: _Stripe) -> None:
    conn_err = stripe.APIConnectionError(f"net down {KEY}")  # type: ignore[no-untyped-call]
    st.errors["sub.modify"] = [conn_err]
    with pytest.raises(StripeOperationError) as ei:
        await gw().change_subscription_price(
            "sub_1", "price_new", proration="none", audit_action_id="a", actor="s"
        )
    assert ei.value.retryable is True
    assert KEY not in str(ei.value)
    st.errors["sub.modify"] = [_invalid("parameter_invalid", "bad")]
    with pytest.raises(StripeOperationError) as ei2:
        await gw().change_subscription_price(
            "sub_1", "price_new", proration="none", audit_action_id="a", actor="s"
        )
    assert ei2.value.retryable is False
    assert ei2.value.code == "parameter_invalid"


# ---- coupons -------------------------------------------------------------- #


@pytest.mark.parametrize(
    "duration,months,cid,extra",
    [
        ("once", None, "solus-comp-once", {"duration": "once"}),
        ("forever", None, "solus-comp-forever", {"duration": "forever"}),
        (
            "repeating",
            3,
            "solus-comp-repeating-3",
            {"duration": "repeating", "duration_in_months": 3},
        ),
        (
            "repeating",
            36,
            "solus-comp-repeating-36",
            {"duration": "repeating", "duration_in_months": 36},
        ),
    ],
)
async def test_ensure_comp_coupon_deterministic_ids(
    st: _Stripe, duration: str, months: int | None, cid: str, extra: dict[str, Any]
) -> None:
    got = await gw().ensure_comp_coupon(duration, months)  # type: ignore[arg-type]
    assert got == cid
    _, p = st.one("coupon.create")
    assert p["id"] == cid
    assert p["percent_off"] == 100
    assert p["api_key"] == KEY
    assert p["idempotency_key"] == f"solus-coupon-{cid}"
    for k, v in extra.items():
        assert p[k] == v


async def test_ensure_comp_coupon_already_exists_is_success(st: _Stripe) -> None:
    st.errors["coupon.create"] = [_invalid("resource_already_exists")]
    assert await gw().ensure_comp_coupon("once", None) == "solus-comp-once"


@pytest.mark.parametrize(
    "duration,months",
    [
        ("repeating", 0),
        ("repeating", 37),
        ("repeating", None),
        ("once", 3),
        ("forever", 1),
        ("weekly", None),
        ("repeating", True),
    ],
)
async def test_ensure_comp_coupon_rejects_bad_args(st: _Stripe, duration: str, months: Any) -> None:
    with pytest.raises(ValueError):
        await gw().ensure_comp_coupon(duration, months)  # type: ignore[arg-type]
    assert st.calls == []


async def test_ensure_comp_coupon_other_error_wrapped(st: _Stripe) -> None:
    st.errors["coupon.create"] = [_invalid("rate_limit")]
    with pytest.raises(StripeOperationError):
        await gw().ensure_comp_coupon("once", None)


async def test_apply_comp_coupon_sets_discount_and_audit(st: _Stripe) -> None:
    await gw().apply_comp_coupon("sub_1", "solus-comp-once", "act2", "staff-1")
    args, p = st.one("sub.modify")
    assert args == ("sub_1",)
    assert p["discounts"] == [{"coupon": "solus-comp-once"}]
    assert p["idempotency_key"] == "solus-admin-act2-apply-coupon"
    assert p["metadata"][ADMIN_ACTION_METADATA_KEY] == "act2"
    assert p["metadata"][ADMIN_ACTOR_METADATA_KEY] == "staff-1"


async def test_apply_comp_coupon_rejects_non_comp_coupon(st: _Stripe) -> None:
    with pytest.raises(ValueError):
        await gw().apply_comp_coupon("sub_1", "SUMMER50", "a", "s")
    assert st.calls == []


async def test_remove_comp_coupon_clears_discounts(st: _Stripe) -> None:
    await gw().remove_comp_coupon("sub_1", "act3", "staff-1")
    _, p = st.one("sub.modify")
    assert p["discounts"] == ""
    assert p["idempotency_key"] == "solus-admin-act3-remove-coupon"
    assert p["metadata"][ADMIN_ACTOR_METADATA_KEY] == "staff-1"


# ---- cancel --------------------------------------------------------------- #


@pytest.mark.parametrize("invoice_now,prorate", [(True, False), (False, True), (True, True)])
async def test_cancel_immediate_passthrough(st: _Stripe, invoice_now: bool, prorate: bool) -> None:
    res = await gw().cancel_subscription(
        "sub_1",
        mode="immediate",
        invoice_now=invoice_now,
        prorate=prorate,
        audit_action_id="req9",
        actor=None,
    )
    args, p = st.one("sub.cancel")
    assert args == ("sub_1",)
    assert p["invoice_now"] is invoice_now
    assert p["prorate"] is prorate
    assert p["idempotency_key"] == "solus-admin-req9-cancel"
    assert p["api_key"] == KEY
    assert not st.of("sub.modify")
    assert res.already_canceled is False
    assert res.subscription is not None and res.subscription.status == "canceled"


async def test_cancel_period_end_uses_update_with_audit(st: _Stripe) -> None:
    st.results["sub.modify"] = {**_sub(), "cancel_at_period_end": True}
    res = await gw().cancel_subscription(
        "sub_1",
        mode="period_end",
        invoice_now=False,
        prorate=False,
        audit_action_id="act4",
        actor="staff-2",
    )
    _, p = st.one("sub.modify")
    assert p["cancel_at_period_end"] is True
    assert p["idempotency_key"] == "solus-admin-act4-cancel"
    assert p["metadata"][ADMIN_ACTOR_METADATA_KEY] == "staff-2"
    assert not st.of("sub.cancel")
    assert res.subscription is not None and res.subscription.cancel_at_period_end is True


async def test_cancel_period_end_without_actor_omits_actor_metadata(st: _Stripe) -> None:
    await gw().cancel_subscription(
        "sub_1",
        mode="period_end",
        invoice_now=False,
        prorate=False,
        audit_action_id="req1",
        actor=None,
    )
    _, p = st.one("sub.modify")
    assert p["metadata"] == {ADMIN_ACTION_METADATA_KEY: "req1"}


@pytest.mark.parametrize("mode", ["immediate", "period_end"])
async def test_cancel_resource_missing_is_success(st: _Stripe, mode: str) -> None:
    st.errors["sub.cancel"] = [_invalid("resource_missing")]
    st.errors["sub.modify"] = [_invalid("resource_missing")]
    res = await gw().cancel_subscription(
        "sub_1",
        mode=mode,  # type: ignore[arg-type]
        invoice_now=False,
        prorate=False,
        audit_action_id="a",
        actor=None,
    )
    assert res.already_canceled is True
    assert res.subscription is None


async def test_cancel_already_canceled_status_is_success(st: _Stripe) -> None:
    st.errors["sub.modify"] = [_invalid(None, "A canceled subscription can only update ...")]
    st.results["sub.retrieve"] = _sub(status="canceled")
    res = await gw().cancel_subscription(
        "sub_1",
        mode="period_end",
        invoice_now=False,
        prorate=False,
        audit_action_id="a",
        actor="s",
    )
    assert res.already_canceled is True
    assert res.subscription is not None and res.subscription.status == "canceled"


async def test_cancel_invalid_request_on_live_sub_is_error(st: _Stripe) -> None:
    st.errors["sub.cancel"] = [_invalid("parameter_invalid")]
    with pytest.raises(StripeOperationError):
        await gw().cancel_subscription(
            "sub_1",
            mode="immediate",
            invoice_now=False,
            prorate=False,
            audit_action_id="a",
            actor=None,
        )


@pytest.mark.parametrize(
    "kwargs",
    [{"mode": "later"}, {"invoice_now": "yes"}, {"prorate": 1}, {"actor": "a@b.co"}],
)
async def test_cancel_invalid_args_rejected(st: _Stripe, kwargs: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "mode": "immediate",
        "invoice_now": False,
        "prorate": False,
        "audit_action_id": "a",
        "actor": None,
    }
    with pytest.raises(ValueError):
        await gw().cancel_subscription("sub_1", **{**base, **kwargs})
    assert st.calls == []


async def test_cancel_idempotency_conflict(st: _Stripe) -> None:
    st.errors["sub.cancel"] = [stripe.IdempotencyError("reused")]
    with pytest.raises(StripeIdempotencyConflictError):
        await gw().cancel_subscription(
            "sub_1",
            mode="immediate",
            invoice_now=True,
            prorate=False,
            audit_action_id="a",
            actor=None,
        )


# ---- schedules ------------------------------------------------------------ #


async def test_create_revert_schedule_two_phases(st: _Stripe) -> None:
    res = await gw().create_revert_schedule(
        "sub_1", "price_orig", comp_months=3, audit_action_id="act5", actor="staff-3"
    )
    _, cp = st.one("sched.create")
    assert cp["from_subscription"] == "sub_1"
    assert cp["idempotency_key"] == "solus-admin-act5-schedule-create"
    # from_subscription cannot be combined with any other schedule param
    assert set(cp) == {"from_subscription", "idempotency_key", "api_key"}
    args, mp = st.one("sched.modify")
    assert args == ("sub_sched_1",)
    assert mp["end_behavior"] == "release"
    assert mp["idempotency_key"] == "solus-admin-act5-schedule-modify"
    p1, p2 = mp["phases"]
    assert p1["items"] == [{"price": "price_comped", "quantity": 1}]
    assert p1["start_date"] == 1_800_000_000
    assert p1["duration"] == {"interval": "month", "interval_count": 3}
    assert p1["discounts"] == [{"coupon": "solus-comp-once"}]
    assert p2["items"] == [{"price": "price_orig", "quantity": 1}]
    assert "duration" not in p2 and "end_date" not in p2
    # Phase 2 is the natural end of the comp: the comp markers must not outlive it,
    # or a later remove_comp could re-price the customer from stale metadata.
    assert p2["metadata"] == {COMP_PREV_PRICE_METADATA_KEY: "", COMP_PLAN_METADATA_KEY: ""}
    assert mp["metadata"][ADMIN_ACTION_METADATA_KEY] == "act5"
    assert res.schedule_id == "sub_sched_1"
    assert res.revert_price_id == "price_orig"
    assert res.stripe_refs() == {
        "subscription": "sub_1",
        "schedule": "sub_sched_1",
        "price": "price_orig",
    }


async def test_create_revert_schedule_reuses_existing_schedule(st: _Stripe) -> None:
    st.results["sub.retrieve"] = _sub(schedule="sub_sched_1")
    await gw().create_revert_schedule(
        "sub_1", "price_orig", comp_months=1, audit_action_id="a", actor="s"
    )
    assert not st.of("sched.create")
    assert len(st.of("sched.modify")) == 1


@pytest.mark.parametrize("months", [0, 37, True, "3"])
async def test_create_revert_schedule_rejects_bad_months(st: _Stripe, months: Any) -> None:
    with pytest.raises(ValueError):
        await gw().create_revert_schedule(
            "sub_1", "price_orig", comp_months=months, audit_action_id="a", actor="s"
        )
    assert st.calls == []


async def test_find_schedule_for_subscription(st: _Stripe) -> None:
    assert await gw().find_schedule_for_subscription("sub_1") is None
    st.results["sub.retrieve"] = _sub(schedule="sub_sched_4")
    assert await gw().find_schedule_for_subscription("sub_1") == "sub_sched_4"


async def test_release_by_schedule_id(st: _Stripe) -> None:
    res = await gw().release_subscription_schedule("sub_sched_1", "act6", "staff-4")
    args, p = st.one("sched.release")
    assert args == ("sub_sched_1",)
    assert p["idempotency_key"] == "solus-admin-act6-schedule-release"
    assert res.already_released is False
    assert res.schedule_id == "sub_sched_1"


async def test_release_by_subscription_id_resolves_schedule(st: _Stripe) -> None:
    st.results["sub.retrieve"] = _sub(schedule="sub_sched_7")
    await gw().release_subscription_schedule("sub_1", "a", "s")
    assert st.one("sched.release")[0] == ("sub_sched_7",)


async def test_release_subscription_without_schedule_is_success(st: _Stripe) -> None:
    res = await gw().release_subscription_schedule("sub_1", "a", "s")
    assert res.already_released is True
    assert res.schedule_id is None
    assert not st.of("sched.release")


async def test_release_missing_schedule_is_success(st: _Stripe) -> None:
    st.errors["sched.release"] = [_invalid("resource_missing")]
    res = await gw().release_subscription_schedule("sub_sched_1", "a", "s")
    assert res.already_released is True


async def test_release_already_released_schedule_is_success(st: _Stripe) -> None:
    st.errors["sched.release"] = [_invalid(None, "already released")]
    st.results["sched.retrieve"] = {"id": "sub_sched_1", "status": "released", "phases": []}
    res = await gw().release_subscription_schedule("sub_sched_1", "a", "s")
    assert res.already_released is True


async def test_release_active_schedule_error_propagates(st: _Stripe) -> None:
    st.errors["sched.release"] = [_invalid("parameter_invalid")]
    with pytest.raises(StripeOperationError):
        await gw().release_subscription_schedule("sub_sched_1", "a", "s")


async def test_release_rejects_bad_id(st: _Stripe) -> None:
    with pytest.raises(ValueError):
        await gw().release_subscription_schedule("cus_1", "a", "s")
    assert st.calls == []


# ---- FIX-A: per-call timeout + list_customer_subscriptions ------------------ #


async def test_every_network_call_is_bounded_by_a_retryable_timeout(
    st: _Stripe, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from solus_api.billing import stripe_gateway

    async def hang(*args: Any, **params: Any) -> Any:
        await asyncio.sleep(5)

    monkeypatch.setattr(stripe.Subscription, "retrieve_async", hang)
    monkeypatch.setattr(stripe_gateway, "STRIPE_CALL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(StripeOperationError) as err:
        await gw().retrieve_subscription("sub_1")
    assert err.value.retryable is True and err.value.code == "timeout"


def _list_page(ids_status: list[tuple[str, str]], *, has_more: bool = False) -> dict[str, Any]:
    return {"data": [{"id": i, "status": s} for i, s in ids_status], "has_more": has_more}


async def test_list_customer_subscriptions_filters_dead_and_scopes_to_the_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake_list(**params: Any) -> dict[str, Any]:
        seen.append(params)
        return _list_page(
            [
                ("sub_live", "active"),
                ("sub_dead", "canceled"),
                ("sub_exp", "incomplete_expired"),
                ("sub_due", "past_due"),
                ("sub_inc", "incomplete"),
                ("bad-id", "active"),
            ]
        )

    monkeypatch.setattr(stripe.Subscription, "list_async", fake_list)
    ids = await gw().list_customer_subscriptions("cus_1")
    assert ids == ["sub_live", "sub_due", "sub_inc"]
    [params] = seen
    # Omitting `status` lists only non-canceled subscriptions (Stripe's default), so a
    # long cancellation history never eats into the pagination cap; incomplete_expired
    # is still filtered out in code.
    assert params["customer"] == "cus_1" and "status" not in params
    assert params["api_key"] == KEY and 0 < params["limit"] <= 100
    assert "idempotency_key" not in params


async def test_list_customer_subscriptions_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        _list_page([("sub_a", "active")], has_more=True),
        _list_page([("sub_b", "trialing")]),
    ]
    cursors: list[Any] = []

    async def fake_list(**params: Any) -> dict[str, Any]:
        cursors.append(params.get("starting_after"))
        return pages.pop(0)

    monkeypatch.setattr(stripe.Subscription, "list_async", fake_list)
    assert await gw().list_customer_subscriptions("cus_1") == ["sub_a", "sub_b"]
    assert cursors == [None, "sub_a"]


async def test_list_customer_subscriptions_hard_caps_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.billing import stripe_gateway

    calls = 0

    async def endless(**params: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _list_page([(f"sub_{calls}", "active")], has_more=True)

    monkeypatch.setattr(stripe.Subscription, "list_async", endless)
    with pytest.raises(SubscriptionListTruncatedError) as err:
        await gw().list_customer_subscriptions("cus_1")
    assert calls == stripe_gateway.MAX_LIST_PAGES and err.value.retryable is True
    # The collected pages are handed back so the caller can act on them before retrying.
    assert err.value.partial == [f"sub_{i}" for i in range(1, stripe_gateway.MAX_LIST_PAGES + 1)]


@pytest.mark.parametrize("bad", ["", "sub_1", "cus_", "cus_a b", None])
async def test_list_customer_subscriptions_rejects_bad_ids_before_any_call(
    st: _Stripe, bad: Any
) -> None:
    with pytest.raises(ValueError):
        await gw().list_customer_subscriptions(bad)
    assert st.calls == []


async def test_list_customer_subscriptions_translates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(**params: Any) -> Any:
        raise stripe.APIConnectionError("x")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(stripe.Subscription, "list_async", boom)
    with pytest.raises(StripeOperationError) as err:
        await gw().list_customer_subscriptions("cus_1")
    assert err.value.retryable is True


async def test_list_customer_subscriptions_without_key_is_unconfigured() -> None:
    with pytest.raises(BillingUnconfiguredError):
        await StripeGateway(_FakeStore(None)).list_customer_subscriptions("cus_1")


# ---- FIX-D: every discount coupon is visible ---------------------------------- #


async def test_a_promo_sorting_ahead_of_the_comp_coupon_does_not_hide_the_comp(
    st: _Stripe,
) -> None:
    st.results["sub.retrieve"] = _sub(
        discounts=[{"coupon": {"id": "promo_SPRING"}}, {"coupon": {"id": "solus-comp-forever"}}]
    )
    snap = await gw().retrieve_subscription("sub_1")
    assert snap.coupon_ids == ("promo_SPRING", "solus-comp-forever")
    assert snap.coupon_id == "solus-comp-forever"


async def test_without_a_comp_the_first_coupon_is_the_primary(st: _Stripe) -> None:
    st.results["sub.retrieve"] = _sub(discounts=[{"coupon": {"id": "a"}}, {"coupon": {"id": "b"}}])
    snap = await gw().retrieve_subscription("sub_1")
    assert (snap.coupon_id, snap.coupon_ids) == ("a", ("a", "b"))
    st.results["sub.retrieve"] = _sub(discounts=[])
    snap = await gw().retrieve_subscription("sub_1")
    assert (snap.coupon_id, snap.coupon_ids) == (None, ())


# ---- redact_customer (account-deletion PII redaction) ---------------------- #


async def test_redact_customer_clears_only_name_and_solus_user_id(st: _Stripe) -> None:
    await gw().redact_customer("cus_1", audit_action_id="acctdel-redact-ab12")
    args, p = st.one("cus.modify")
    assert args == ("cus_1",)
    assert p == {
        "name": "",
        "metadata": {"solus_user_id": ""},
        "api_key": KEY,
        "idempotency_key": "solus-admin-acctdel-redact-ab12-redact-customer",
    }
    assert "email" not in p


async def test_redact_customer_resource_missing_is_success(st: _Stripe) -> None:
    st.errors["cus.modify"] = [_invalid("resource_missing")]
    await gw().redact_customer("cus_1", audit_action_id="a")


@pytest.mark.parametrize("customer_id", ["", "sub_1", "cus_", "cus_a b", "cus_1;x", 5])
async def test_redact_customer_rejects_bad_customer_id_before_any_call(
    st: _Stripe, customer_id: Any
) -> None:
    with pytest.raises(ValueError, match="customer id"):
        await gw().redact_customer(customer_id, audit_action_id="a")
    assert st.calls == []


@pytest.mark.parametrize("audit", ["", "a b", "x@y.co", "a" * 65, None])
async def test_redact_customer_rejects_bad_audit_id_before_any_call(
    st: _Stripe, audit: Any
) -> None:
    with pytest.raises(ValueError, match="audit_action_id"):
        await gw().redact_customer("cus_1", audit_action_id=audit)
    assert st.calls == []


async def test_redact_customer_without_key_is_unconfigured(st: _Stripe) -> None:
    with pytest.raises(BillingUnconfiguredError):
        await StripeGateway(_FakeStore(None)).redact_customer("cus_1", audit_action_id="a")
    assert st.calls == []


async def test_redact_customer_translates_errors_without_leaking(st: _Stripe) -> None:
    st.errors["cus.modify"] = [stripe.APIConnectionError(f"net down {KEY}")]  # type: ignore[no-untyped-call]
    with pytest.raises(StripeOperationError) as err:
        await gw().redact_customer("cus_1", audit_action_id="a")
    assert err.value.retryable is True and KEY not in str(err.value)
    st.errors["cus.modify"] = [stripe.IdempotencyError("reused")]
    with pytest.raises(StripeIdempotencyConflictError):
        await gw().redact_customer("cus_1", audit_action_id="a")
    st.errors["cus.modify"] = [_invalid("parameter_invalid_empty")]
    with pytest.raises(StripeOperationError) as bad:
        await gw().redact_customer("cus_1", audit_action_id="a")
    assert bad.value.retryable is False


async def test_redact_customer_is_bounded_by_a_retryable_timeout(
    st: _Stripe, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from solus_api.billing import stripe_gateway

    async def hang(*args: Any, **params: Any) -> Any:
        await asyncio.sleep(5)

    monkeypatch.setattr(stripe.Customer, "modify_async", hang)
    monkeypatch.setattr(stripe_gateway, "STRIPE_CALL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(StripeOperationError) as err:
        await gw().redact_customer("cus_1", audit_action_id="a")
    assert err.value.retryable is True and err.value.code == "timeout"
