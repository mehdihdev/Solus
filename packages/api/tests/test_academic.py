"""Academic monthly credits, expiry, the daily sweep and the spend gate (ADR-042).

The domain rule and entitlement predicates are pure; the grant/sweep tests run
against the test database through the real credit primitives."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.billing import credits
from solus_api.billing.academic import (
    AcademicPlanService,
    academic_domain,
    is_academic_email,
    month_key,
    normalize_email,
    sweep_academic,
)
from solus_api.billing.entitlements import is_academic_expired, is_local_access_expired
from solus_api.core.config import Settings
from solus_api.models import (
    AcademicVerification,
    CreditLedger,
    CreditTxnType,
    DataEvent,
    Notification,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
    utcnow,
)
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.gates import AcademicExpiredError, TrialExpiredError, assert_can_spend
from solus_api.routers.billing import _carried_trial_end
from solus_api.routers.sol import _POLICY_BLOCKS
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SUFFIXES = ["edu", "ac.uk", "edu.au"]
NOV = datetime(2026, 11, 8, tzinfo=UTC)
DEC = datetime(2026, 12, 1, 0, 30, tzinfo=UTC)


def _settings(**kw: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret="test-only",
        academic_monthly_credits=1000,
        **kw,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ pure rules


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("ada@mit.edu", True),
        ("ada@csail.mit.edu", True),
        ("ada@ox.ac.uk", True),
        ("ada@unimelb.edu.au", True),
        ("ada@edu", False),
        ("ada@ac.uk", False),
        ("ada@mit.edu.evil.com", False),
        ("ada@fakeedu", False),
        ("ada@gmail.com", False),
        ("ada", False),
        ("@mit.edu", False),
        ("a@b@mit.edu", False),
    ],
)
def test_is_academic_email(raw: str, ok: bool) -> None:
    assert is_academic_email(raw, SUFFIXES) is ok


def test_normalize_and_domain() -> None:
    assert normalize_email("  Ada@MIT.Edu ") == "ada@mit.edu"
    assert academic_domain("ada@csail.mit.edu") == "csail.mit.edu"


def test_month_key_is_utc_year_month() -> None:
    assert month_key(datetime(2026, 1, 31, 23, 59, tzinfo=UTC)) == "2026-01"


def _sub(**kw: object) -> Subscription:
    base: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "plan": PlanType.ACADEMIC,
        "status": SubscriptionStatus.ACTIVE,
        "expires_at": NOV + timedelta(days=10),
    }
    return Subscription(**{**base, **kw})


def test_academic_expiry_predicate() -> None:
    assert not is_academic_expired(_sub(), NOV)
    assert is_academic_expired(_sub(expires_at=NOV - timedelta(seconds=1)), NOV)
    assert not is_academic_expired(
        _sub(plan=PlanType.BASIC, expires_at=NOV - timedelta(days=1)), NOV
    )
    assert is_local_access_expired(_sub(expires_at=NOV - timedelta(days=1)), NOV)


def test_academic_plan_has_basic_limits() -> None:
    assert default_limits(PlanType.ACADEMIC) == default_limits(PlanType.BASIC)


def test_academic_expiry_is_never_carried_into_a_stripe_trial() -> None:
    assert _carried_trial_end(_sub(expires_at=NOV + timedelta(days=300)), NOV) is None


def test_sol_maps_academic_expiry_to_its_own_code() -> None:
    assert _POLICY_BLOCKS[AcademicExpiredError][0] == "academic_expired"
    assert issubclass(AcademicExpiredError, TrialExpiredError)


# ------------------------------------------------------------------ DB helpers


async def _user(db: AsyncSession, *, expires: datetime, consent: bool = True) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"s-{tag}", email=f"{tag}@example.com", data_collection_consent=consent
    )
    db.add(user)
    await db.flush()
    db.add(
        Subscription(
            user_id=user.id,
            plan=PlanType.ACADEMIC,
            status=SubscriptionStatus.ACTIVE,
            limits=default_limits(PlanType.ACADEMIC),
            expires_at=expires,
        )
    )
    db.add(
        AcademicVerification(
            user_id=user.id, verified_email=f"{tag}@mit.edu", verified_at=NOV, expires_at=expires
        )
    )
    await db.commit()
    return user.id


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[CreditTxnType, int]]:
    db.expire_all()
    rows = await db.scalars(
        select(CreditLedger)
        .where(CreditLedger.user_id == user_id)
        .order_by(CreditLedger.created_at)
    )
    return [(r.type, r.amount) for r in rows.all()]


# ------------------------------------------------------------------ monthly grant


async def test_grant_is_idempotent_within_a_month(db: AsyncSession) -> None:
    uid = await _user(db, expires=NOV + timedelta(days=300))
    service = AcademicPlanService(db, _settings())
    assert await service.apply_monthly_grant(uid, NOV) is True
    assert await service.apply_monthly_grant(uid, NOV + timedelta(days=5)) is False
    assert await _ledger(db, uid) == [(CreditTxnType.ACADEMIC_GRANT, 1000)]


async def test_unspent_credits_do_not_roll_over(db: AsyncSession) -> None:
    uid = await _user(db, expires=NOV + timedelta(days=300))
    service = AcademicPlanService(db, _settings())
    await service.apply_monthly_grant(uid, NOV)
    await credits.debit_credits(db, uid, 300, idempotency_key=f"use-{uid}")
    await service.apply_monthly_grant(uid, DEC)
    assert await _ledger(db, uid) == [
        (CreditTxnType.ACADEMIC_GRANT, 1000),
        (CreditTxnType.USAGE, -300),
        (CreditTxnType.ADJUSTMENT, -700),
        (CreditTxnType.ACADEMIC_GRANT, 1000),
    ]
    assert await credits.get_balance(db, uid) == 1000


async def test_purchased_credits_survive_the_month_end(db: AsyncSession) -> None:
    uid = await _user(db, expires=NOV + timedelta(days=300))
    service = AcademicPlanService(db, _settings())
    await service.apply_monthly_grant(uid, NOV)
    await credits.add_credits(db, uid, 500, CreditTxnType.PURCHASE, idempotency_key=f"buy-{uid}")
    await credits.debit_credits(db, uid, 1200, idempotency_key=f"use-{uid}")
    await service.apply_monthly_grant(uid, DEC)
    # Academic credits are spent first: all 1,000 went, so nothing is removed and the
    # 300 purchased credits that remain carry into December.
    assert await credits.get_balance(db, uid) == 1300
    assert (CreditTxnType.ADJUSTMENT, 0) not in await _ledger(db, uid)


async def test_expiry_removal_never_drives_the_balance_negative(db: AsyncSession) -> None:
    uid = await _user(db, expires=NOV + timedelta(days=300))
    service = AcademicPlanService(db, _settings())
    await service.apply_monthly_grant(uid, NOV)
    # A refund-style negative adjustment outside usage leaves less than the unspent grant.
    await credits.expire_credits(db, uid, 900, idempotency_key=f"x-{uid}", attrs={})
    await service.apply_monthly_grant(uid, DEC)
    assert await credits.get_balance(db, uid) == 1000


async def test_no_grant_for_expired_or_non_academic(db: AsyncSession) -> None:
    expired = await _user(db, expires=NOV - timedelta(days=1))
    service = AcademicPlanService(db, _settings())
    assert await service.apply_monthly_grant(expired, NOV) is False
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == expired))
    assert sub is not None
    sub.plan, sub.expires_at = PlanType.PRO, None
    await db.commit()
    assert await service.apply_monthly_grant(expired, NOV) is False
    assert await _ledger(db, expired) == []


# ------------------------------------------------------------------ sweep


async def test_sweep_grants_live_users_and_notifies_expiry_once(db: AsyncSession) -> None:
    live = await _user(db, expires=DEC + timedelta(days=200))
    ended = await _user(db, expires=DEC - timedelta(hours=1))
    first = await sweep_academic(db, _settings(), now=DEC)
    second = await sweep_academic(db, _settings(), now=DEC + timedelta(hours=1))
    assert first.granted == 1 and first.expired == 1
    assert second.granted == 0 and second.expired == 0
    assert await _ledger(db, live) == [(CreditTxnType.ACADEMIC_GRANT, 1000)]
    events = (
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "billing.academic.expired")
        )
    ).all()
    assert [e.user_id for e in events] == [ended]
    notes = (await db.scalars(select(Notification).where(Notification.user_id == ended))).all()
    assert len(notes) == 1


async def test_sweep_skips_rows_that_moved_to_a_paid_plan(db: AsyncSession) -> None:
    uid = await _user(db, expires=DEC + timedelta(days=200))
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None
    sub.plan, sub.stripe_subscription_id = PlanType.PRO, "sub_pro"
    await db.commit()
    summary = await sweep_academic(db, _settings(), now=DEC)
    assert summary.granted == 0 and await _ledger(db, uid) == []


# ------------------------------------------------------------------ spend gate


async def test_gate_blocks_an_expired_academic_plan(db: AsyncSession) -> None:
    uid = await _user(db, expires=utcnow() - timedelta(hours=1))
    await credits.add_credits(db, uid, 50, CreditTxnType.ACADEMIC_GRANT, idempotency_key=f"g-{uid}")
    with pytest.raises(AcademicExpiredError):
        await assert_can_spend(uid, session=db, limits=LimitsConfig(trial_credit_cap=100))
    event = await db.scalar(
        select(DataEvent).where(
            DataEvent.user_id == uid, DataEvent.event_type == "orchestration.blocked"
        )
    )
    assert event is not None and event.payload["reason"] == "academic_expired"


async def test_gate_allows_a_live_academic_plan_with_credits(db: AsyncSession) -> None:
    uid = await _user(db, expires=utcnow() + timedelta(days=30))
    await AcademicPlanService(db, _settings()).apply_monthly_grant(uid, utcnow())
    await assert_can_spend(uid, session=db, limits=LimitsConfig(trial_credit_cap=100))


async def test_purchase_unlocks_an_expired_academic_plan(db: AsyncSession) -> None:
    uid = await _user(db, expires=utcnow() - timedelta(hours=1))
    await credits.add_credits(db, uid, 50, CreditTxnType.PURCHASE, idempotency_key=f"p-{uid}")
    await assert_can_spend(uid, session=db, limits=LimitsConfig(trial_credit_cap=100))


def test_academic_sweep_cron_is_registered_daily() -> None:
    from solus_api.connectors.worker import build_worker_settings

    settings = build_worker_settings(_settings(redis_url="redis://localhost:6379"))
    crons = {job.coroutine.__name__: job for job in settings.cron_jobs}
    sweep = crons["academic_sweep"]
    assert sweep.hour == {0} and sweep.minute == {10} and sweep.run_at_startup is True


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("Ada+Lab@MIT.edu", "ada@mit.edu"),
        ("ada.lovelace@ox.ac.uk", "ada.lovelace@ox.ac.uk"),
        ('"ada"@mit.edu', None),
        ("ada@mit..edu", None),
        ("ada..x@mit.edu", None),
    ],
)
def test_canonical_email(raw: str, canonical: str | None) -> None:
    from solus_api.billing.academic import canonical_email

    assert canonical_email(raw) == canonical


async def test_sweep_prunes_the_send_log(db: AsyncSession) -> None:
    from solus_api.models import AcademicCodeSend

    db.add(AcademicCodeSend(address="old@mit.edu", created_at=DEC - timedelta(days=2)))
    db.add(AcademicCodeSend(address="new@mit.edu", created_at=DEC - timedelta(hours=1)))
    await db.commit()
    await sweep_academic(db, _settings(), now=DEC)
    db.expire_all()
    left = (await db.scalars(select(AcademicCodeSend.address))).all()
    assert left == ["new@mit.edu"]
