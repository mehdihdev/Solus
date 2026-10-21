"""POST /billing/portal-session optional flow body (SOLUSDEV-236).

Gateway stubbed via dependency_overrides; asserts route logic: server-derived
subscription id, 409/422 codes, rate limit, error mapping, event, isolation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import stripe
from conftest import ALICE, BOB, TEST_AUDIENCE, TEST_DATABASE_URL, TEST_JWT_SECRET, bearer, me
from httpx import ASGITransport, AsyncClient
from solus_api.billing.portal_config import reset_portal_config_cache
from solus_api.billing.stripe_gateway import BillingUnconfiguredError, StripeOperationError
from solus_api.core.config import Settings
from solus_api.deps import get_stripe_gateway
from solus_api.main import create_app
from solus_api.models import DataEvent, Subscription, SubscriptionStatus, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

URL = "/api/v1/billing/portal-session"


class FakeGateway:
    def __init__(self) -> None:
        self.unconfigured = False
        self.provider_error: Exception | None = None
        self.portal_calls: list[dict[str, Any]] = []
        self.configs_created = 0

    def _guard(self) -> None:
        if self.unconfigured:
            raise BillingUnconfiguredError("no key")
        if self.provider_error is not None:
            raise self.provider_error

    async def price_products(self, price_ids: list[str]) -> dict[str, str]:
        self._guard()
        return {p: "prod_1" for p in price_ids}

    async def list_portal_configurations(self) -> list[Any]:
        return []

    async def create_portal_configuration(self, params: dict[str, Any], *, key_hash: str) -> str:
        self.configs_created += 1
        return "bpc_flow"

    async def create_portal_session(self, **kwargs: Any) -> str:
        self._guard()
        self.portal_calls.append(kwargs)
        return "https://billing.stripe.com/p/test"


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
        sync_inline=True,
        stripe_plan_prices={"basic:month": "price_bm", "pro:year": "price_py"},
    )


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    reset_portal_config_cache()


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
async def bclient(engine: Any, gateway: FakeGateway) -> Any:
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_stripe_gateway] = lambda: gateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _setup(
    client: AsyncClient,
    db: AsyncSession,
    who: dict[str, str] = ALICE,
    *,
    customer: str | None = "cus_a",
    sub_id: str | None = "sub_a",
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    cancel_at: datetime | None = None,
) -> dict[str, str]:
    headers = bearer(who["sub"], who["email"])
    data = await me(client, headers)
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(data["id"])))
    assert sub is not None
    sub.stripe_customer_id = customer
    sub.stripe_subscription_id = sub_id
    sub.status = status
    sub.cancel_at = cancel_at
    await db.commit()
    return dict(headers)


async def test_no_body_general_portal(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    headers = await _setup(bclient, db)
    resp = await bclient.post(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"url": "https://billing.stripe.com/p/test"}
    call = gateway.portal_calls[-1]
    assert call["configuration"] == "bpc_flow"
    assert call["flow"] is None
    assert call["subscription_id"] is None
    assert call["customer"] == "cus_a"


async def test_general_portal_works_without_stripe_subscription(
    bclient: AsyncClient, db: AsyncSession
) -> None:
    headers = await _setup(bclient, db, sub_id=None, status=SubscriptionStatus.TRIALING)
    assert (await bclient.post(URL, headers=headers)).status_code == 200


async def test_empty_json_body_is_general(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db)
    resp = await bclient.post(URL, json={}, headers=headers)
    assert resp.status_code == 200
    assert resp.status_code == 200


@pytest.mark.parametrize("flow", ["update", "cancel"])
async def test_flow_uses_callers_own_subscription(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway, flow: str
) -> None:
    headers = await _setup(bclient, db)
    resp = await bclient.post(URL, json={"flow": flow}, headers=headers)
    assert resp.status_code == 200, resp.text
    call = gateway.portal_calls[-1]
    assert call["flow"] == flow
    assert call["subscription_id"] == "sub_a"
    assert resp.json()["data"] == {"url": "https://billing.stripe.com/p/test"}


@pytest.mark.parametrize("status", [SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE])
async def test_flow_allowed_for_trialing_and_past_due(
    bclient: AsyncClient, db: AsyncSession, status: SubscriptionStatus
) -> None:
    headers = await _setup(bclient, db, status=status)
    assert (await bclient.post(URL, json={"flow": "update"}, headers=headers)).status_code == 200


async def test_body_with_subscription_id_is_422(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db)
    resp = await bclient.post(
        URL, json={"flow": "cancel", "subscription_id": "sub_evil"}, headers=headers
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("body", [{"flow": "delete"}, {"customer": "cus_x"}, {"flow": 3}])
async def test_unknown_flow_or_field_is_422(
    bclient: AsyncClient, db: AsyncSession, body: dict[str, Any]
) -> None:
    headers = await _setup(bclient, db)
    assert (await bclient.post(URL, json=body, headers=headers)).status_code == 422


async def test_flow_without_stripe_subscription_is_409(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    headers = await _setup(bclient, db, sub_id=None)
    resp = await bclient.post(URL, json={"flow": "update"}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_active_subscription"
    assert gateway.portal_calls == []


async def test_flow_with_canceled_status_is_409(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db, status=SubscriptionStatus.CANCELED)
    resp = await bclient.post(URL, json={"flow": "cancel"}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_active_subscription"


async def test_cancel_with_cancel_at_set_is_409(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db, cancel_at=datetime.now(UTC) + timedelta(days=5))
    resp = await bclient.post(URL, json={"flow": "cancel"}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "cancel_already_scheduled"


async def test_update_with_cancel_at_set_is_allowed(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db, cancel_at=datetime.now(UTC) + timedelta(days=5))
    assert (await bclient.post(URL, json={"flow": "update"}, headers=headers)).status_code == 200


async def test_no_customer_is_409(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db, customer=None)
    resp = await bclient.post(URL, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_billing_customer"


async def test_unauthenticated_is_401(bclient: AsyncClient) -> None:
    assert (await bclient.post(URL, json={"flow": "update"})).status_code == 401


async def test_cross_user_never_uses_other_users_subscription(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    alice = await _setup(bclient, db, ALICE, customer="cus_a", sub_id="sub_a")
    bob = await _setup(bclient, db, BOB, customer="cus_b", sub_id="sub_b")
    await bclient.post(URL, json={"flow": "cancel"}, headers=alice)
    await bclient.post(URL, json={"flow": "cancel"}, headers=bob)
    seen = [(c["customer"], c["subscription_id"]) for c in gateway.portal_calls]
    assert seen == [("cus_a", "sub_a"), ("cus_b", "sub_b")]


async def test_rate_limited_after_ten_per_minute(bclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _setup(bclient, db)
    codes = [(await bclient.post(URL, headers=headers)).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429
    other = await _setup(bclient, db, BOB, customer="cus_b", sub_id="sub_b")
    assert (await bclient.post(URL, headers=other)).status_code == 200


@pytest.mark.parametrize(
    "error", [stripe.error.StripeError("down"), StripeOperationError("x", code="boom")]
)
async def test_stripe_error_is_502(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway, error: Exception
) -> None:
    headers = await _setup(bclient, db)
    gateway.provider_error = error
    resp = await bclient.post(URL, headers=headers)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "billing_provider_error"


async def test_unconfigured_is_503(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    headers = await _setup(bclient, db)
    gateway.unconfigured = True
    resp = await bclient.post(URL, headers=headers)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "billing_unconfigured"


async def test_configuration_created_once_across_requests(
    bclient: AsyncClient, db: AsyncSession, gateway: FakeGateway
) -> None:
    headers = await _setup(bclient, db)
    for _ in range(3):
        await bclient.post(URL, headers=headers)
    assert gateway.configs_created == 1


@pytest.mark.parametrize(
    ("body", "label"),
    [(None, "general"), ({"flow": "update"}, "update"), ({"flow": "cancel"}, "cancel")],
)
async def test_event_emitted_without_stripe_ids(
    bclient: AsyncClient, db: AsyncSession, body: dict[str, str] | None, label: str
) -> None:
    headers = await _setup(bclient, db)
    user = await db.scalar(select(User).where(User.email == ALICE["email"]))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()
    resp = (
        await bclient.post(URL, json=body, headers=headers)
        if body
        else await bclient.post(URL, headers=headers)
    )
    assert resp.status_code == 200
    db.expire_all()
    events = (
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "billing.portal_session.created")
        )
    ).all()
    assert [e.payload for e in events] == [{"flow": label}]
