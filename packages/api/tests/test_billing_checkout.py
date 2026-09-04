"""Checkout-session + billing-portal routes (SOLUSDEV-83 follow-up).

The outbound Stripe calls are stubbed by a FakeGateway injected via
dependency_overrides, so these tests never hit Stripe. They assert route logic:
plan/pack validation, customer reuse/persistence, mode selection, auth, and the
503/409 failure paths — plus per-user isolation of the Stripe customer id.
"""

import uuid
from typing import Any

import pytest
import stripe
from conftest import ALICE, BOB, TEST_AUDIENCE, TEST_DATABASE_URL, TEST_JWT_SECRET, bearer, me
from httpx import ASGITransport, AsyncClient
from solus_api.billing.stripe_gateway import BillingUnconfiguredError
from solus_api.core.config import Settings
from solus_api.deps import get_stripe_gateway
from solus_api.main import create_app
from solus_api.models import Subscription, SubscriptionStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class FakeGateway:
    """Records calls; returns deterministic ids. `unconfigured` flips it to raise
    BillingUnconfiguredError, mimicking a missing Stripe key."""

    def __init__(self, *, unconfigured: bool = False, provider_error: bool = False) -> None:
        self.unconfigured = unconfigured
        self.provider_error = provider_error
        self.checkout_calls: list[dict[str, Any]] = []
        self.portal_calls: list[dict[str, Any]] = []

    def _guard(self) -> None:
        if self.unconfigured:
            raise BillingUnconfiguredError("no key")
        if self.provider_error:
            raise stripe.error.StripeError("stripe is down")

    async def get_or_create_customer(
        self, *, existing: str | None, email: str, user_id: str
    ) -> str:
        self._guard()
        return existing or f"cus_{user_id}"

    async def create_checkout_session(self, **kwargs: Any) -> str:
        self._guard()
        self.checkout_calls.append(kwargs)
        return "https://checkout.stripe.com/c/test"

    async def create_portal_session(self, **kwargs: Any) -> str:
        self._guard()
        self.portal_calls.append(kwargs)
        return "https://billing.stripe.com/p/test"


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
        sync_inline=True,
        stripe_plan_prices={"basic:month": "price_bm", "pro:year": "price_py"},
        stripe_pack_credits={"price_pack10": 1000, "price_pack25": 2500},
        stripe_pack_usd={"price_pack10": 10},  # pack25 deliberately unmapped
        stripe_trial_days=14,
    )


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
async def bclient(engine: Any, gateway: FakeGateway) -> Any:
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_stripe_gateway] = lambda: gateway
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_subscription_checkout_returns_url_and_uses_subscription_mode(
    bclient: AsyncClient, gateway: FakeGateway
) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)  # provision user + subscription
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "basic", "interval": "month"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["url"] == "https://checkout.stripe.com/c/test"
    call = gateway.checkout_calls[-1]
    assert call["mode"] == "subscription"
    assert call["price_id"] == "price_bm"
    assert call["trial_days"] == 14


async def test_subscription_checkout_persists_stripe_customer_id(
    bclient: AsyncClient,
) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    data = await me(bclient, headers)
    await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "pro", "interval": "year"},
        headers=headers,
    )
    sub = (await bclient.get("/api/v1/users/me/subscription", headers=headers)).json()["data"]
    assert sub["stripe_customer_id"] == f"cus_{data['id']}"


async def test_enterprise_plan_is_not_checkoutable(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "enterprise", "interval": "month"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "plan_not_checkoutable"


async def test_subscription_without_interval_is_rejected(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "basic"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_interval"


async def test_unmapped_plan_price_returns_billing_unconfigured(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    # basic:year is not in the configured price map.
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "basic", "interval": "year"},
        headers=headers,
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "billing_unconfigured"


async def test_pack_checkout_uses_payment_mode(bclient: AsyncClient, gateway: FakeGateway) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "pack", "price_id": "price_pack10"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    call = gateway.checkout_calls[-1]
    assert call["mode"] == "payment"
    assert call["trial_days"] is None


async def test_unknown_pack_is_rejected(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "pack", "price_id": "price_bogus"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_pack"


async def test_checkout_requires_auth(bclient: AsyncClient) -> None:
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "basic", "interval": "month"},
    )
    assert resp.status_code == 401


async def test_checkout_503_when_gateway_unconfigured(engine: Any) -> None:
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_stripe_gateway] = lambda: FakeGateway(unconfigured=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        headers = bearer(ALICE["sub"], ALICE["email"])
        await me(c, headers)
        resp = await c.post(
            "/api/v1/billing/checkout-session",
            json={"kind": "subscription", "plan": "basic", "interval": "month"},
            headers=headers,
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "billing_unconfigured"


async def test_portal_409_without_customer(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.post("/api/v1/billing/portal-session", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_billing_customer"


async def test_portal_returns_url_after_checkout(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "basic", "interval": "month"},
        headers=headers,
    )
    resp = await bclient.post("/api/v1/billing/portal-session", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["url"] == "https://billing.stripe.com/p/test"


async def test_list_credit_packs_returns_configured_packs(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.get("/api/v1/billing/packs", headers=headers)
    assert resp.status_code == 200, resp.text
    packs = resp.json()["data"]["packs"]
    # `usd` is the display price when mapped (SOLUS_STRIPE_PACK_USD), null when not.
    assert packs == [
        {"price_id": "price_pack10", "credits": 1000, "usd": 10},
        {"price_id": "price_pack25", "credits": 2500, "usd": None},
    ]


async def test_credits_endpoint_reports_balance(client: AsyncClient) -> None:
    """GET /users/me/credits returns the balance (the trial grant on a fresh user)."""
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(client, headers)
    resp = await client.get("/api/v1/users/me/credits", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["balance"] == 1000  # settings.trial_credit_grant default
    assert "user_id" in body


async def test_credits_endpoint_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me/credits")
    assert resp.status_code == 401


async def test_already_subscribed_is_rejected(bclient: AsyncClient, db: AsyncSession) -> None:
    """A user with a live Stripe subscription cannot start a SECOND checkout
    (double-billing guard); they change plans via the portal → 409."""
    headers = bearer(ALICE["sub"], ALICE["email"])
    data = await me(bclient, headers)
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(data["id"])))
    assert sub is not None
    sub.stripe_subscription_id = "sub_live"
    sub.status = SubscriptionStatus.ACTIVE
    await db.commit()
    resp = await bclient.post(
        "/api/v1/billing/checkout-session",
        json={"kind": "subscription", "plan": "pro", "interval": "month"},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_subscribed"


async def test_checkout_provider_error_returns_502(engine: Any) -> None:
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_stripe_gateway] = lambda: FakeGateway(provider_error=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        headers = bearer(ALICE["sub"], ALICE["email"])
        await me(c, headers)
        resp = await c.post(
            "/api/v1/billing/checkout-session",
            json={"kind": "subscription", "plan": "basic", "interval": "month"},
            headers=headers,
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "billing_provider_error"


async def test_pack_checkout_503_when_no_packs_configured(
    engine: Any, gateway: FakeGateway
) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
        sync_inline=True,
        stripe_plan_prices={"basic:month": "price_bm"},
        stripe_pack_credits={},
    )
    app = create_app(settings=settings, engine=engine)
    app.dependency_overrides[get_stripe_gateway] = lambda: gateway
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        headers = bearer(ALICE["sub"], ALICE["email"])
        await me(c, headers)
        resp = await c.post(
            "/api/v1/billing/checkout-session",
            json={"kind": "pack", "price_id": "price_anything"},
            headers=headers,
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "billing_unconfigured"


async def test_customer_id_is_per_user(bclient: AsyncClient) -> None:
    a_headers = bearer(ALICE["sub"], ALICE["email"])
    b_headers = bearer(BOB["sub"], BOB["email"])
    a = await me(bclient, a_headers)
    b = await me(bclient, b_headers)
    for headers in (a_headers, b_headers):
        await bclient.post(
            "/api/v1/billing/checkout-session",
            json={"kind": "subscription", "plan": "basic", "interval": "month"},
            headers=headers,
        )
    a_sub = (await bclient.get("/api/v1/users/me/subscription", headers=a_headers)).json()["data"]
    b_sub = (await bclient.get("/api/v1/users/me/subscription", headers=b_headers)).json()["data"]
    assert a_sub["stripe_customer_id"] == f"cus_{a['id']}"
    assert b_sub["stripe_customer_id"] == f"cus_{b['id']}"
    assert a_sub["stripe_customer_id"] != b_sub["stripe_customer_id"]
    assert uuid.UUID(a["id"]) != uuid.UUID(b["id"])
