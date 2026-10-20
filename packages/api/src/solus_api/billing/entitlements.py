"""Effective plan and limits for a subscription (ADR-023, clarified 2026-10-07).

Pure reads: no I/O, no Stripe, no mutation. Enforcement code asks for
`effective_limits` and never branches on plan names; the plan only selects which
defaults apply. Resolution, in order:

1. Base limits. If a staff comp is ACTIVE, the comp plan's defaults. Otherwise the
   subscription's stored `limits` (the plan-derived data the Stripe webhook
   maintains, including the BASIC clamp after a subscription ends).
2. `limits_override` merged per key on top: a present key wins (explicit `None` =
   unlimited); an absent key falls through to the base.

A comp is active when `comp_plan` is set and `comp_expires_at` is NULL (forever) or in
the future. Expiry is evaluated at read time, so nothing has to sweep expired comps.
"""

from datetime import UTC, datetime

from solus_api.models import PlanType, Subscription, SubscriptionStatus, default_limits, utcnow


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def is_comp_active(sub: Subscription, now: datetime | None = None) -> bool:
    """Whether a staff comp currently grants `comp_plan` (NULL expiry = forever)."""
    if sub.comp_plan is None:
        return False
    if sub.comp_expires_at is None:
        return True
    return _aware(sub.comp_expires_at) > _aware(now or utcnow())


def effective_plan(sub: Subscription, now: datetime | None = None) -> PlanType:
    """The plan whose defaults apply: the active comp plan, else the purchased plan."""
    if is_comp_active(sub, now) and sub.comp_plan is not None:
        return sub.comp_plan
    return sub.plan


def effective_limits(sub: Subscription, now: datetime | None = None) -> dict[str, int | None]:
    """The limits to enforce: comp-or-stored base with `limits_override` merged per key.

    Returns a new dict; `sub` is never mutated."""
    if is_comp_active(sub, now) and sub.comp_plan is not None:
        base: dict[str, int | None] = default_limits(sub.comp_plan)
    else:
        base = dict(sub.limits or {})
    return {**base, **(sub.limits_override or {})}


def is_local_trial_expired(sub: Subscription, now: datetime | None = None) -> bool:
    """Whether a trial that Stripe does not back has run past `expires_at` (ADR-024
    amendment, SOLUSDEV-236). Stripe-linked trials are Stripe's to end; a NULL
    `expires_at` never expires. `expires_at <= now` counts as expired."""
    if sub.status != SubscriptionStatus.TRIALING or sub.stripe_subscription_id is not None:
        return False
    if sub.expires_at is None:
        return False
    return _aware(sub.expires_at) <= _aware(now or utcnow())
