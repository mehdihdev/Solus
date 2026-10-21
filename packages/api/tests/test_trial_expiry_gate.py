"""Trial-expiry pre-flight gate (SOLUSDEV-236, ADR-024 amendment 2026-10-19).

A local trial (trialing, no Stripe subscription) past `expires_at` refuses metered
calls with `TrialExpiredError`, unless the ledger holds a PURCHASE and the balance
covers at least one credit. Stripe-linked trials, unexpired trials and trials with
no `expires_at` keep the pre-existing behavior.
"""

import uuid
from datetime import timedelta

import pytest
from solus_api.billing.credits import add_credits, grant_trial_credits
from solus_api.models import (
    CreditBalance,
    CreditTxnType,
    DataEvent,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    utcnow,
)
from solus_api.orchestration import TrialExpiredError as ExportedTrialExpiredError
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.gates import (
    InsufficientCreditsError,
    TrialCapReachedError,
    TrialExpiredError,
    assert_can_spend,
)
from solus_api.orchestration.gateway import _PASSTHROUGH_ERRORS
from solus_api.routers.sol import _POLICY_BLOCKS
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

_LIMITS = LimitsConfig(trial_credit_cap=100)


async def _seed(
    db: AsyncSession,
    *,
    expires_in: timedelta | None,
    status: SubscriptionStatus = SubscriptionStatus.TRIALING,
    stripe_id: str | None = None,
    consent: bool = False,
) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com", data_collection_consent=consent
    )
    db.add(user)
    await db.flush()
    db.add(
        Subscription(
            user_id=user.id,
            plan=PlanType.BASIC,
            status=status,
            stripe_subscription_id=stripe_id,
            expires_at=None if expires_in is None else utcnow() + expires_in,
        )
    )
    await db.commit()
    return user.id


_EXPIRED = timedelta(hours=-1)


async def test_expired_local_trial_is_blocked(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED)
    with pytest.raises(TrialExpiredError) as excinfo:
        await assert_can_spend(user_id, session=db, limits=_LIMITS)
    assert excinfo.value.ends_at is not None
    assert excinfo.value.upgrade_url == "/settings/billing"


async def test_expired_block_emits_consented_event_with_ends_at(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED, consent=True)
    with pytest.raises(TrialExpiredError) as excinfo:
        await assert_can_spend(user_id, session=db, limits=_LIMITS)
    event = await db.scalar(select(DataEvent).where(DataEvent.user_id == user_id))
    assert event is not None
    assert event.event_type == "orchestration.blocked"
    assert event.payload["reason"] == "trial_expired"
    ends_at = excinfo.value.ends_at
    assert ends_at is not None
    assert event.payload["ends_at"] == ends_at.isoformat()


async def test_unexpired_local_trial_is_allowed(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=timedelta(days=3))
    await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_expiry_check_precedes_trial_cap(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED)
    db.add(CreditBalance(user_id=user_id, balance=0, spent_total=500))
    await db.commit()
    with pytest.raises(TrialExpiredError):
        await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_unexpired_trial_over_cap_still_hits_trial_cap(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=timedelta(days=3))
    db.add(CreditBalance(user_id=user_id, balance=0, spent_total=500))
    await db.commit()
    with pytest.raises(TrialCapReachedError):
        await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_expiry_exactly_now_is_expired(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _seed(db, expires_in=timedelta(days=1))
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    assert sub is not None
    frozen = sub.expires_at
    assert frozen is not None
    monkeypatch.setattr("solus_api.billing.entitlements.utcnow", lambda: frozen)
    with pytest.raises(TrialExpiredError):
        await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_stripe_linked_trial_is_never_blocked_by_expiry(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED, stripe_id="sub_live")
    await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_null_expires_at_is_allowed(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=None)
    await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_dev_unlimited_bypass_still_wins(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED)
    monkeypatch.setattr(
        "solus_api.orchestration.gates.session_development_unlimited", lambda *_a, **_k: True
    )
    await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_expired_with_purchase_and_balance_is_allowed(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED)
    await add_credits(db, user_id, 500, CreditTxnType.PURCHASE, idempotency_key=f"p-{user_id}")
    await db.commit()
    await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_expired_with_purchase_but_zero_balance_is_blocked_as_trial_expired(
    db: AsyncSession,
) -> None:
    """The doc (API-implementation §10): the purchase unlock needs balance >= 1;
    otherwise the call is refused with the same `trial_expired` code (the account is
    still an expired trial, and one code keeps the UI's single Billing CTA)."""
    user_id = await _seed(db, expires_in=_EXPIRED)
    await add_credits(db, user_id, 5, CreditTxnType.PURCHASE, idempotency_key=f"p-{user_id}")
    await db.execute(
        update(CreditBalance).where(CreditBalance.user_id == user_id).values(balance=0)
    )
    await db.commit()
    with pytest.raises(TrialExpiredError):
        await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_expired_with_only_trial_grant_credits_is_blocked(db: AsyncSession) -> None:
    user_id = await _seed(db, expires_in=_EXPIRED)
    await grant_trial_credits(db, user_id, 1_000)
    with pytest.raises(TrialExpiredError):
        await assert_can_spend(user_id, session=db, limits=_LIMITS)


async def test_other_users_purchase_never_unlocks_this_user(db: AsyncSession) -> None:
    alice = await _seed(db, expires_in=_EXPIRED)
    bob = await _seed(db, expires_in=_EXPIRED)
    await add_credits(db, bob, 500, CreditTxnType.PURCHASE, idempotency_key=f"p-{bob}")
    await db.commit()
    await assert_can_spend(bob, session=db, limits=_LIMITS)
    with pytest.raises(TrialExpiredError):
        await assert_can_spend(alice, session=db, limits=_LIMITS)


def test_trial_expired_error_carries_code_and_is_registered_everywhere() -> None:
    assert ExportedTrialExpiredError is TrialExpiredError
    assert TrialExpiredError in _PASSTHROUGH_ERRORS
    code, message = _POLICY_BLOCKS[TrialExpiredError]
    assert code == "trial_expired"
    assert "choose a plan" in message.lower()
    assert issubclass(TrialExpiredError, RuntimeError)
    assert not issubclass(TrialExpiredError, InsufficientCreditsError)
