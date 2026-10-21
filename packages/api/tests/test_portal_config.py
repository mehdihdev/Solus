"""Portal configuration builder + find-or-create (SOLUSDEV-236). No network."""

import asyncio
from typing import Any

import pytest
from conftest import TEST_JWT_SECRET
from solus_api.billing.portal_config import (
    HASH_METADATA_KEY,
    PORTAL_CONFIG_VERSION,
    VERSION_METADATA_KEY,
    PortalConfigCache,
    ensure_portal_configuration,
    portal_configuration_params,
)
from solus_api.billing.stripe_gateway import BillingUnconfiguredError
from solus_api.core.config import Settings

PRICES = {"basic:month": "price_bm", "basic:year": "price_by", "pro:month": "price_pm"}
PRODUCTS = {"price_bm": "prod_basic", "price_by": "prod_basic", "price_pm": "prod_pro"}


def _settings(prices: dict[str, str] | None = None) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret=TEST_JWT_SECRET,
        stripe_plan_prices=PRICES if prices is None else prices,
    )


class FakeGw:
    def __init__(self, existing: list[Any] | None = None) -> None:
        self.existing = existing or []
        self.created: list[dict[str, Any]] = []
        self.listed = 0

    async def price_products(self, price_ids: list[str]) -> dict[str, str]:
        await asyncio.sleep(0)
        return {p: PRODUCTS.get(p, "prod_x") for p in price_ids}

    async def list_portal_configurations(self) -> list[Any]:
        await asyncio.sleep(0)
        self.listed += 1
        return self.existing

    async def create_portal_configuration(self, params: dict[str, Any], *, key_hash: str) -> str:
        await asyncio.sleep(0)
        self.created.append({"params": params, "key_hash": key_hash})
        return f"bpc_{len(self.created)}"


def test_params_proration_and_schedule_conditions() -> None:
    f = portal_configuration_params(_settings(), PRODUCTS)["features"]
    upd = f["subscription_update"]
    assert upd["enabled"] is True
    assert upd["default_allowed_updates"] == ["price"]
    assert upd["proration_behavior"] == "always_invoice"
    assert upd["schedule_at_period_end"]["conditions"] == [
        {"type": "decreasing_item_amount"},
        {"type": "shortening_interval"},
    ]


def test_params_cancel_at_period_end_and_other_features() -> None:
    f = portal_configuration_params(_settings(), PRODUCTS)["features"]
    assert f["subscription_cancel"] == {
        "enabled": True,
        "mode": "at_period_end",
        "proration_behavior": "none",
    }
    assert f["payment_method_update"] == {"enabled": True}
    assert f["invoice_history"] == {"enabled": True}
    assert f["customer_update"] == {"enabled": False}


def test_params_products_grouped_by_product() -> None:
    f = portal_configuration_params(_settings(), PRODUCTS)["features"]
    assert f["subscription_update"]["products"] == [
        {"product": "prod_basic", "prices": ["price_bm", "price_by"]},
        {"product": "prod_pro", "prices": ["price_pm"]},
    ]


def test_params_only_offer_self_serve_plans_and_intervals() -> None:
    # Same gate as Checkout (CHECKOUTABLE_PLANS × VALID_INTERVALS): an enterprise or
    # malformed key in the config must never become a portal switch target.
    prices = {**PRICES, "enterprise:month": "price_em", "pro:week": "price_pw", "junk": "price_j"}
    f = portal_configuration_params(_settings(prices), PRODUCTS)["features"]
    offered = {p for row in f["subscription_update"]["products"] for p in row["prices"]}
    assert offered == {"price_bm", "price_by", "price_pm"}


def test_params_have_no_invented_branding() -> None:
    assert "business_profile" not in portal_configuration_params(_settings(), PRODUCTS)


def test_metadata_version_and_hash_stable_and_price_sensitive() -> None:
    a = portal_configuration_params(_settings(), PRODUCTS)["metadata"]
    b = portal_configuration_params(_settings(dict(reversed(PRICES.items()))), PRODUCTS)["metadata"]
    other = {**PRICES, "pro:year": "price_py"}
    c = portal_configuration_params(_settings(other), {**PRODUCTS, "price_py": "prod_pro"})[
        "metadata"
    ]
    assert a[VERSION_METADATA_KEY] == PORTAL_CONFIG_VERSION
    assert a == b
    assert a[HASH_METADATA_KEY] != c[HASH_METADATA_KEY]


async def test_ensure_creates_once_then_uses_cache() -> None:
    gw, cache = FakeGw(), PortalConfigCache()
    first = await ensure_portal_configuration(gw, _settings(), cache=cache)
    second = await ensure_portal_configuration(gw, _settings(), cache=cache)
    assert first == second == "bpc_1"
    assert len(gw.created) == 1
    assert gw.listed == 1
    assert gw.created[0]["key_hash"] == gw.created[0]["params"]["metadata"][HASH_METADATA_KEY]


async def test_ensure_reuses_matching_existing_configuration() -> None:
    want = portal_configuration_params(_settings(), PRODUCTS)["metadata"][HASH_METADATA_KEY]
    existing = [
        {"id": "bpc_other", "metadata": {VERSION_METADATA_KEY: "0", HASH_METADATA_KEY: want}},
        {"id": "bpc_nometa", "metadata": {}},
        {
            "id": "bpc_match",
            "metadata": {VERSION_METADATA_KEY: PORTAL_CONFIG_VERSION, HASH_METADATA_KEY: want},
        },
    ]
    gw = FakeGw(existing)
    assert (
        await ensure_portal_configuration(gw, _settings(), cache=PortalConfigCache()) == "bpc_match"
    )
    assert gw.created == []


async def test_ensure_creates_new_when_hash_differs() -> None:
    stale = [
        {
            "id": "bpc_old",
            "metadata": {
                VERSION_METADATA_KEY: PORTAL_CONFIG_VERSION,
                HASH_METADATA_KEY: "deadbeef",
            },
        }
    ]
    gw = FakeGw(stale)
    got = await ensure_portal_configuration(gw, _settings(), cache=PortalConfigCache())
    assert got == "bpc_1"
    assert len(gw.created) == 1


async def test_ensure_price_change_creates_a_new_configuration() -> None:
    gw, cache = FakeGw(), PortalConfigCache()
    a = await ensure_portal_configuration(gw, _settings(), cache=cache)
    b = await ensure_portal_configuration(gw, _settings({"basic:month": "price_zz"}), cache=cache)
    assert a != b
    assert len(gw.created) == 2


async def test_concurrent_ensure_creates_at_most_once() -> None:
    gw, cache = FakeGw(), PortalConfigCache()
    ids = await asyncio.gather(
        *(ensure_portal_configuration(gw, _settings(), cache=cache) for _ in range(10))
    )
    assert set(ids) == {"bpc_1"}
    assert len(gw.created) == 1


async def test_ensure_without_plan_prices_is_unconfigured() -> None:
    with pytest.raises(BillingUnconfiguredError):
        await ensure_portal_configuration(FakeGw(), _settings({}), cache=PortalConfigCache())
