"""Effective plan/limits (ADR-023 clarification 2026-10-07, SOLUSDEV-313): pure reads."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.billing.entitlements import (
    effective_limits,
    effective_plan,
    is_comp_active,
    is_local_trial_expired,
)
from solus_api.models import (
    PlanType,
    Subscription,
    SubscriptionStatus,
    default_limits,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _sub(
    plan: PlanType = PlanType.BASIC,
    *,
    limits: dict[str, int | None] | None = None,
    override: dict[str, int | None] | None = None,
    comp_plan: PlanType | None = None,
    comp_expires_at: datetime | None = None,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> Subscription:
    return Subscription(
        plan=plan,
        status=status,
        limits=default_limits(plan) if limits is None else limits,
        limits_override=override,
        comp_plan=comp_plan,
        comp_expires_at=comp_expires_at,
    )


def test_no_override_returns_stored_plan_limits() -> None:
    assert effective_limits(_sub(), NOW) == default_limits(PlanType.BASIC)


def test_override_none_is_the_same_as_no_override() -> None:
    sub = _sub(override=None)
    assert effective_limits(sub, NOW) == sub.limits


def test_empty_override_changes_nothing() -> None:
    assert effective_limits(_sub(override={}), NOW) == default_limits(PlanType.BASIC)


def test_override_merges_per_key_and_absent_keys_fall_through() -> None:
    result = effective_limits(_sub(override={"max_projects": 10}), NOW)
    defaults = default_limits(PlanType.BASIC)
    assert result["max_projects"] == 10
    assert result["max_integrations"] == defaults["max_integrations"]
    assert result["max_teams"] == defaults["max_teams"]


def test_explicit_null_means_unlimited_not_fall_through() -> None:
    result = effective_limits(_sub(override={"max_projects": None}), NOW)
    assert "max_projects" in result
    assert result["max_projects"] is None


def test_override_may_add_a_key_the_plan_does_not_define() -> None:
    assert effective_limits(_sub(override={"max_widgets": 3}), NOW)["max_widgets"] == 3


def test_override_survives_an_ended_subscription() -> None:
    clamped = default_limits(PlanType.BASIC)
    sub = _sub(
        PlanType.PRO,
        limits=clamped,
        override={"max_projects": None},
        status=SubscriptionStatus.CANCELED,
    )
    result = effective_limits(sub, NOW)
    assert result["max_projects"] is None
    assert result["max_integrations"] == clamped["max_integrations"]


def test_active_comp_uses_comp_plan_defaults_not_stored_limits() -> None:
    sub = _sub(PlanType.BASIC, comp_plan=PlanType.PRO, comp_expires_at=NOW + timedelta(days=1))
    assert effective_plan(sub, NOW) is PlanType.PRO
    assert effective_limits(sub, NOW) == default_limits(PlanType.PRO)


def test_override_applies_over_comp_plan_defaults() -> None:
    sub = _sub(
        comp_plan=PlanType.PRO,
        comp_expires_at=NOW + timedelta(days=1),
        override={"max_teams": 1},
    )
    result = effective_limits(sub, NOW)
    assert result["max_teams"] == 1
    assert result["max_projects"] == default_limits(PlanType.PRO)["max_projects"]


def test_expired_comp_is_ignored_at_read_time() -> None:
    sub = _sub(PlanType.BASIC, comp_plan=PlanType.PRO, comp_expires_at=NOW - timedelta(seconds=1))
    assert not is_comp_active(sub, NOW)
    assert effective_plan(sub, NOW) is PlanType.BASIC
    assert effective_limits(sub, NOW) == default_limits(PlanType.BASIC)


def test_comp_expiring_exactly_now_is_expired() -> None:
    sub = _sub(comp_plan=PlanType.PRO, comp_expires_at=NOW)
    assert not is_comp_active(sub, NOW)


def test_forever_comp_has_no_expiry() -> None:
    sub = _sub(comp_plan=PlanType.PRO, comp_expires_at=None)
    far_future = NOW + timedelta(days=365 * 200)
    assert is_comp_active(sub, far_future)
    assert effective_limits(sub, far_future) == default_limits(PlanType.PRO)


def test_no_comp_plan_is_never_active() -> None:
    assert not is_comp_active(_sub(comp_expires_at=NOW + timedelta(days=1)), NOW)


def test_naive_comp_expiry_is_read_as_utc() -> None:
    naive = (NOW + timedelta(days=1)).replace(tzinfo=None)
    assert is_comp_active(_sub(comp_plan=PlanType.PRO, comp_expires_at=naive), NOW)


def test_comp_beats_ended_subscription_clamp() -> None:
    sub = _sub(
        PlanType.PRO,
        limits=default_limits(PlanType.BASIC),
        comp_plan=PlanType.PRO,
        status=SubscriptionStatus.CANCELED,
    )
    assert effective_limits(sub, NOW) == default_limits(PlanType.PRO)


def test_now_defaults_to_the_current_time() -> None:
    live = _sub(comp_plan=PlanType.PRO, comp_expires_at=datetime.now(UTC) + timedelta(hours=1))
    gone = _sub(comp_plan=PlanType.PRO, comp_expires_at=datetime.now(UTC) - timedelta(hours=1))
    assert effective_plan(live) is PlanType.PRO
    assert effective_plan(gone) is PlanType.BASIC
    assert effective_limits(live) == default_limits(PlanType.PRO)
    assert is_comp_active(gone) is False


def test_inputs_are_never_mutated() -> None:
    sub = _sub(override={"max_projects": None}, comp_plan=PlanType.PRO)
    before = (copy.deepcopy(sub.limits), copy.deepcopy(sub.limits_override))
    result = effective_limits(sub, NOW)
    result["max_teams"] = 999
    assert (sub.limits, sub.limits_override) == before


def test_empty_stored_limits_with_no_comp_stays_empty_plus_override() -> None:
    assert effective_limits(_sub(limits={}, override={"max_teams": 5}), NOW) == {"max_teams": 5}


@pytest.mark.parametrize("plan", list(PlanType))
def test_every_plan_resolves_without_branching_on_names(plan: PlanType) -> None:
    assert effective_limits(_sub(plan), NOW) == default_limits(plan)


# --- is_local_trial_expired (SOLUSDEV-236, ADR-024 trial expiry) ---


def _trial(
    expires_at: datetime | None,
    *,
    status: SubscriptionStatus = SubscriptionStatus.TRIALING,
    stripe_id: str | None = None,
) -> Subscription:
    return Subscription(
        plan=PlanType.BASIC,
        status=status,
        expires_at=expires_at,
        stripe_subscription_id=stripe_id,
    )


def test_local_trial_past_expiry_is_expired() -> None:
    assert is_local_trial_expired(_trial(NOW - timedelta(seconds=1)), NOW) is True


def test_local_trial_at_exact_expiry_is_expired() -> None:
    assert is_local_trial_expired(_trial(NOW), NOW) is True


def test_local_trial_before_expiry_is_live() -> None:
    assert is_local_trial_expired(_trial(NOW + timedelta(seconds=1)), NOW) is False


def test_local_trial_without_expiry_is_never_expired() -> None:
    assert is_local_trial_expired(_trial(None), NOW) is False


def test_stripe_linked_trial_is_never_locally_expired() -> None:
    past = NOW - timedelta(days=3)
    assert is_local_trial_expired(_trial(past, stripe_id="sub_1"), NOW) is False


@pytest.mark.parametrize(
    "status", [SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.PAST_DUE]
)
def test_non_trialing_status_is_not_trial_expired(status: SubscriptionStatus) -> None:
    assert is_local_trial_expired(_trial(NOW - timedelta(days=1), status=status), NOW) is False


def test_naive_expires_at_is_treated_as_utc() -> None:
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert is_local_trial_expired(_trial(naive), NOW) is True


def test_default_now_is_the_current_time() -> None:
    assert is_local_trial_expired(_trial(datetime.now(UTC) - timedelta(minutes=1))) is True
    assert is_local_trial_expired(_trial(datetime.now(UTC) + timedelta(days=1))) is False
