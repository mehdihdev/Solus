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
