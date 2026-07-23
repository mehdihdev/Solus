"""Unit tests for the pure plan ↔ Stripe Price mapping (SOLUSDEV-83 follow-up)."""

from conftest import TEST_AUDIENCE, TEST_JWT_SECRET
from solus_api.billing.plans import (
    CHECKOUTABLE_PLANS,
    VALID_INTERVALS,
    plan_for_price,
    plan_for_price_id,
    plan_price_id,
)
from solus_api.core.config import Settings
from solus_api.models import PlanType


def _settings(prices: dict[str, str]) -> Settings:
    return Settings(
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        stripe_plan_prices=prices,
    )


def test_plan_price_id_forward_lookup() -> None:
    s = _settings({"basic:month": "price_bm", "pro:year": "price_py"})
    assert plan_price_id(s, PlanType.BASIC, "month") == "price_bm"
    assert plan_price_id(s, PlanType.PRO, "year") == "price_py"


def test_plan_price_id_returns_none_when_unmapped() -> None:
    s = _settings({"basic:month": "price_bm"})
    assert plan_price_id(s, PlanType.PRO, "month") is None
    assert plan_price_id(s, PlanType.BASIC, "year") is None


def test_plan_for_price_reverse_lookup() -> None:
    s = _settings({"basic:month": "price_bm", "pro:year": "price_py"})
    assert plan_for_price(s, "price_bm") is PlanType.BASIC
    assert plan_for_price(s, "price_py") is PlanType.PRO


def test_plan_for_price_unknown_price_is_none() -> None:
    s = _settings({"basic:month": "price_bm"})
    assert plan_for_price(s, "price_unknown") is None


def test_plan_for_price_ignores_a_malformed_plan_key() -> None:
    s = _settings({"bogus:month": "price_x"})
    assert plan_for_price(s, "price_x") is None


def test_plan_for_price_id_dict_reverse_lookup() -> None:
    mapping = {"basic:month": "price_bm", "pro:year": "price_py"}
    assert plan_for_price_id(mapping, "price_bm") is PlanType.BASIC
    assert plan_for_price_id(mapping, "price_py") is PlanType.PRO
    assert plan_for_price_id(mapping, "nope") is None
    assert plan_for_price_id({}, "price_bm") is None


def test_checkoutable_plans_excludes_enterprise() -> None:
    assert PlanType.BASIC in CHECKOUTABLE_PLANS
    assert PlanType.PRO in CHECKOUTABLE_PLANS
    assert PlanType.ENTERPRISE not in CHECKOUTABLE_PLANS
    assert VALID_INTERVALS == {"month", "year"}
