"""GET /api/v1/billing/summary (SOLUSDEV-236 T5): auth, 404, shape, 429, isolation, degraded."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import ALICE, BOB, TEST_AUDIENCE, TEST_DATABASE_URL, TEST_JWT_SECRET, bearer, me
from httpx import ASGITransport, AsyncClient
from solus_api.billing.stripe_gateway import (
    BillingUnconfiguredError,
    CardSummary,
    InvoicePreview,
    PriceAmount,
    StripeOperationError,
)
from solus_api.billing.summary import reset_billing_summary_caches
from solus_api.core.config import Settings
from solus_api.deps import get_stripe_gateway
from solus_api.main import create_app
from solus_api.models import Subscription, SubscriptionStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

URL = "/api/v1/billing/summary"
PRICES = {"basic:month": "price_bm", "pro:year": "price_py"}


class FakeGateway:
    def __init__(self) -> None:
        self.unconfigured = False
        self.error: Exception | None = None
        self.by_customer: dict[str, tuple[InvoicePreview, CardSummary]] = {}
        self.user_calls = 0
        self.price_calls = 0

    async def ensure_configured(self) -> None:
        if self.unconfigured:
            raise BillingUnconfiguredError("no key")

    async def upcoming_invoice(
        self, customer_id: str, subscription_id: str
    ) -> InvoicePreview | None:
        self.user_calls += 1
        if self.error:
            raise self.error
        return self.by_customer[customer_id][0]

    async def default_payment_method(
        self, customer_id: str, subscription_id: str
    ) -> CardSummary | None:
        self.user_calls += 1
        return self.by_customer[customer_id][1]

    async def price_amounts(self, price_ids: list[str]) -> dict[str, PriceAmount]:
        self.price_calls += 1
        if self.error:
            raise self.error
        return {p: PriceAmount(2500, "usd", "month") for p in price_ids}


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
        sync_inline=True,
        stripe_plan_prices=PRICES,
        stripe_pack_credits={"price_pack": 1000},
    )


@pytest.fixture(autouse=True)
def _fresh_caches() -> None:
    reset_billing_summary_caches()


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
async def bclient(engine: Any, gateway: FakeGateway) -> Any:
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_stripe_gateway] = lambda: gateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _link(
    client: AsyncClient, db: AsyncSession, who: dict[str, str], customer: str, sub_id: str
) -> dict[str, str]:
    headers = bearer(who["sub"], who["email"])
    data = await me(client, headers)
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(data["id"])))
    assert sub is not None
    sub.stripe_customer_id = customer
    sub.stripe_subscription_id = sub_id
    sub.status = SubscriptionStatus.ACTIVE
    await db.commit()
    return dict(headers)


def _invoice(cents: int) -> InvoicePreview:
    return InvoicePreview(cents, "usd", datetime.now(UTC) + timedelta(days=10))


async def test_unauthenticated_is_401(bclient: AsyncClient) -> None:
    assert (await bclient.get(URL)).status_code == 401


async def test_no_subscription_row_is_404(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    data = await me(bclient, headers)
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(data["id"])))
    assert sub is not None
    sub.deleted_at = datetime.now(UTC)
    await db.commit()
    resp = await bclient.get(URL, headers=headers)
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"


async def test_local_trial_shape_and_no_user_stripe_calls(
    bclient: AsyncClient, gateway: FakeGateway
) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    resp = await bclient.get(URL, headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["trial"]["state"] == "active" and data["trial"]["ends_at"]
    assert data["next_invoice"] is None and data["payment_method"] is None
    assert data["packs_available"] is True and data["stripe_status"] == "ok"
    assert {(p["plan"], p["interval"]) for p in data["prices"]} == {
        ("basic", "month"),
        ("pro", "year"),
    }
    assert set(data) == {
        "plan", "status", "billing_interval", "current_period_end", "cancel_at", "trial",
        "next_invoice", "payment_method", "prices", "packs_available", "stripe_status",
    }  # fmt: skip
    assert gateway.user_calls == 0


async def test_rate_limited_after_thirty_per_minute(bclient: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(bclient, headers)
    codes = [(await bclient.get(URL, headers=headers)).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


async def test_cross_user_isolation_including_cached(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    gateway.by_customer = {
        "cus_a": (_invoice(1111), CardSummary("visa", "1111")),
        "cus_b": (_invoice(2222), CardSummary("amex", "2222")),
    }
    ha = await _link(bclient, db, ALICE, "cus_a", "sub_a")
    hb = await _link(bclient, db, BOB, "cus_b", "sub_b")
    for _ in range(2):  # second pass is served from the per-user cache
        a = (await bclient.get(URL, headers=ha)).json()["data"]
        b = (await bclient.get(URL, headers=hb)).json()["data"]
        assert (a["next_invoice"]["amount_cents"], a["payment_method"]["last4"]) == (1111, "1111")
        assert (b["next_invoice"]["amount_cents"], b["payment_method"]["last4"]) == (2222, "2222")
    assert gateway.user_calls == 4


async def test_response_has_no_stripe_ids(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    gateway.by_customer = {"cus_a": (_invoice(1), CardSummary("visa", "4242"))}
    headers = await _link(bclient, db, ALICE, "cus_a", "sub_a")
    text = (await bclient.get(URL, headers=headers)).text
    for needle in ("cus_", "sub_", "pm_", "price_", "in_"):
        assert needle not in text


async def test_gateway_errors_degrade_to_200(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    gateway.by_customer = {"cus_a": (_invoice(1), CardSummary("visa", "4242"))}
    gateway.error = StripeOperationError("x", code="timeout")
    headers = await _link(bclient, db, ALICE, "cus_a", "sub_a")
    resp = await bclient.get(URL, headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stripe_status"] == "unavailable"
    assert data["next_invoice"] is None and data["prices"] is None
    assert data["plan"] == "basic"


async def test_unconfigured_degrades_to_200(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    gateway.unconfigured = True
    headers = await _link(bclient, db, ALICE, "cus_a", "sub_a")
    data = (await bclient.get(URL, headers=headers)).json()["data"]
    assert data["stripe_status"] == "unconfigured" and gateway.user_calls == 0
