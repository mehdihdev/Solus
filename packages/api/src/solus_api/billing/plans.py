"""Pure plan ↔ Stripe Price mapping (ADR-023). No Stripe import, no I/O — just
the config-driven translation between our PlanType and Stripe recurring Price
ids, so it is fully unit-testable and used by both the checkout route (forward)
and the webhook (reverse: derive the local plan from the purchased price).

Config shape (`Settings.stripe_plan_prices`): {"<plan>:<interval>": "<price_id>"},
e.g. {"basic:month": "price_...", "pro:year": "price_..."}.
"""

from solus_api.core.config import Settings
from solus_api.models import PlanType

# Enterprise is contact-sales (ADR-023 application → offer → accept), never a
# self-serve Checkout, so only these plans are checkoutable.
CHECKOUTABLE_PLANS: frozenset[PlanType] = frozenset({PlanType.BASIC, PlanType.PRO})
VALID_INTERVALS: frozenset[str] = frozenset({"month", "year"})


def plan_price_id(settings: Settings, plan: PlanType, interval: str) -> str | None:
    """The Stripe Price id for a plan+interval, or None if unmapped in config."""
    return settings.stripe_plan_prices.get(f"{plan.value}:{interval}")


def plan_for_price_id(plan_prices: dict[str, str], price_id: str) -> PlanType | None:
    """Reverse lookup over a raw plan-prices mapping: the PlanType a Stripe Price
    id belongs to, or None. The webhook uses this to set the local plan/limits
    from what the customer actually bought — never trusting a client-supplied
    plan name for entitlement (CLAUDE.md §7: model/client output is untrusted)."""
    for key, mapped in plan_prices.items():
        if mapped == price_id:
            try:
                return PlanType(key.split(":", 1)[0])
            except ValueError:
                return None
    return None


def plan_for_price(settings: Settings, price_id: str) -> PlanType | None:
    """Settings-scoped convenience wrapper around :func:`plan_for_price_id`."""
    return plan_for_price_id(settings.stripe_plan_prices, price_id)
