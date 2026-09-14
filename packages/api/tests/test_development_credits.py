"""ADR-024 development exception: scoped admission only, never free accounting."""

import uuid

import pytest
from pydantic import ValidationError
from solus_api.billing import credits
from solus_api.billing.development import SESSION_SETTINGS_KEY, is_development_unlimited
from solus_api.core.config import Settings
from solus_api.core.db import build_sessionmaker
from solus_api.main import create_app
from solus_api.models import (
    CreditBalance,
    CreditLedger,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    InsufficientCreditsError,
    TrialCapReachedError,
    assert_can_spend,
    check_frequency_cap,
)
from sqlalchemy import select
from test_gates import FakeRedis


def configured(settings, identity, environment="dev"):
    return Settings(
        _env_file=None,
        **{
            **settings.model_dump(),
            "app_env": environment,
            "development_unlimited_credit_user_ids": str(identity),
        },
    )


@pytest.mark.parametrize(
    "environment,allowed",
    [
        ("dev", True),
        ("prod", False),
        ("production", False),
        ("staging", False),
        ("test", False),
        ("DEV", False),
        ("dev ", False),
    ],
)
def test_allowlist_requires_exact_development_environment(settings, environment, allowed):
    identity = uuid.uuid4()
    config = configured(settings, identity, environment)
    assert is_development_unlimited(identity, config) is allowed
    assert is_development_unlimited(uuid.uuid4(), config) is False


def test_default_and_invalid_allowlists_fail_closed(settings):
    assert settings.development_unlimited_credit_user_ids == ""
    assert not is_development_unlimited(uuid.uuid4(), settings)
    assert not is_development_unlimited(uuid.uuid4(), None)
    for invalid in ("*", "all", "email@example.test", "not-a-uuid", str(uuid.uuid4()) + ",*"):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                **{**settings.model_dump(), "development_unlimited_credit_user_ids": invalid},
            )


async def seeded(db, *, trial=False):
    user = User(supabase_user_id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.test")
    db.add(user)
    await db.flush()
    db.add(CreditBalance(user_id=user.id, balance=-12, spent_total=10000))
    if trial:
        db.add(
            Subscription(user_id=user.id, plan=PlanType.BASIC, status=SubscriptionStatus.TRIALING)
        )
    await db.commit()
    return user.id


@pytest.mark.parametrize("trial", [False, True])
async def test_allowlisted_account_passes_empty_balance_and_trial_caps(db, settings, trial):
    identity = await seeded(db, trial=trial)
    db.info[SESSION_SETTINGS_KEY] = configured(settings, identity)
    assert await credits.check_spend_allowed(db, identity, 999999999)
    await assert_can_spend(identity, session=db, limits=LimitsConfig(trial_credit_cap=1))
    assert await credits.get_balance(db, identity) == -12


@pytest.mark.parametrize("mode", ["missing", "foreign", "prod", "malformed"])
async def test_other_accounts_and_production_keep_credit_and_trial_limits(db, settings, mode):
    identity = await seeded(db, trial=True)
    if mode != "missing":
        db.info[SESSION_SETTINGS_KEY] = (
            "dev"
            if mode == "malformed"
            else configured(
                settings,
                uuid.uuid4() if mode == "foreign" else identity,
                "prod" if mode == "prod" else "dev",
            )
        )
    assert not await credits.check_spend_allowed(db, identity, 1)
    with pytest.raises(TrialCapReachedError):
        await assert_can_spend(identity, session=db, limits=LimitsConfig(trial_credit_cap=1))


async def test_unlimited_still_records_real_idempotent_cost_and_keeps_frequency_limit(db, settings):
    identity = await seeded(db)
    db.info[SESSION_SETTINGS_KEY] = configured(settings, identity)
    first = await credits.debit_credits(db, identity, 25, idempotency_key="development-call")
    second = await credits.debit_credits(db, identity, 25, idempotency_key="development-call")
    assert first.applied and second.duplicate
    assert await credits.get_balance(db, identity) == -37
    balance = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == identity))
    assert balance.spent_total == 10025
    ledger = list(await db.scalars(select(CreditLedger).where(CreditLedger.user_id == identity)))
    assert len(ledger) == 1 and ledger[0].amount == -25
    redis = FakeRedis()
    limits = LimitsConfig(max_calls_per_minute=1)
    await check_frequency_cap(identity, redis=redis, limits=limits, now=1, session=db)
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(identity, redis=redis, limits=limits, now=2, session=db)


async def test_app_and_session_factories_keep_development_settings_isolated(
    engine, settings, db, monkeypatch
):
    # External storage setup is unrelated to application/session configuration.
    monkeypatch.setattr("solus_api.main.build_secret_store", lambda *_: object())
    monkeypatch.setattr("solus_api.main.build_artifact_store", lambda *_: object())
    identity = await seeded(db)
    development = configured(settings, identity)
    production = configured(settings, identity, "prod")
    for config, expected in ((development, True), (production, False)):
        app = create_app(settings=config, engine=engine)
        async with app.state.sessionmaker() as session:
            assert session.info[SESSION_SETTINGS_KEY] is config
            assert await credits.check_spend_allowed(session, identity, 1) is expected
    async with build_sessionmaker(engine)() as session:
        assert not await credits.check_spend_allowed(session, identity, 1)
        with pytest.raises(InsufficientCreditsError):
            await assert_can_spend(identity, session=session, limits=LimitsConfig())
