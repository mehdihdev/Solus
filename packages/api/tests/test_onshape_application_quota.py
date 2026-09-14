"""Application replacement must not inherit another OAuth app's quota refusal."""

import hashlib
import uuid

import pytest
from conftest import TEST_JWT_SECRET
from solus_api.connectors.quota import CallMeter, QuotaBlockedError
from solus_api.connectors.registry import ConnectorContext, _onshape_meter
from solus_api.core.config import Settings
from test_connector_quota import FakeRedis


def meter(
    redis: FakeRedis,
    app: str,
    account: str = "account-a",
    secret: str = "test",
    bound_app: str | None = None,
) -> CallMeter:
    settings = Settings(
        _env_file=None,
        supabase_jwt_secret=TEST_JWT_SECRET,
        onshape_client_id=app,
        onshape_client_secret=secret,
    )
    return _onshape_meter(
        settings,
        redis,
        ConnectorContext(
            account_ref=account,
            onshape_application=hashlib.sha256((bound_app or app).encode()).hexdigest(),
        ),
    )


async def test_new_application_does_not_inherit_exhaustion_or_usage() -> None:
    redis = FakeRedis()
    old = meter(redis, "old-app")
    await old.record(200)
    await old.record(402)
    history = dict(redis.values)
    new = meter(redis, "new-app")
    await new.admit()
    assert (await new.state()).used == 0
    assert not (await new.state()).exhausted
    assert redis.values == history
    assert (await old.state()).used == 1
    assert (await old.state()).exhausted


async def test_secret_rotation_preserves_same_application_quota() -> None:
    redis = FakeRedis()
    await meter(redis, "same-app", secret="before").record(402)
    with pytest.raises(QuotaBlockedError, match="allowance exhausted"):
        await meter(redis, "same-app", secret="after").admit()


async def test_accounts_remain_isolated_within_application() -> None:
    redis = FakeRedis()
    await meter(redis, "same-app", "account-a").record(402)
    await meter(redis, "same-app", "account-b").admit()


async def test_verified_new_grant_preserves_old_legacy_latch() -> None:
    redis = FakeRedis()
    redis.values["solus:intq:onshape:acct:account-a:402"] = "1"
    await meter(redis, "new-app").admit()
    assert redis.values["solus:intq:onshape:acct:account-a:402"] == "1"


async def test_missing_account_retains_project_isolation() -> None:
    redis = FakeRedis()
    settings = Settings(
        _env_file=None, supabase_jwt_secret=TEST_JWT_SECRET, onshape_client_id="same-app"
    )
    one = _onshape_meter(settings, redis, ConnectorContext(project_id=uuid.uuid4()))
    two = _onshape_meter(settings, redis, ConnectorContext(project_id=uuid.uuid4()))
    await one.record(402)
    await two.admit()


async def test_settings_change_does_not_rebind_old_grant() -> None:
    redis = FakeRedis()
    await meter(redis, "old-app", bound_app="old-app").record(402)
    with pytest.raises(QuotaBlockedError):
        await meter(redis, "new-app", bound_app="old-app").admit()


async def test_unknown_legacy_grant_retains_existing_bucket() -> None:
    redis = FakeRedis()
    redis.values["solus:intq:onshape:acct:account-a:402"] = "1"
    settings = Settings(
        _env_file=None, supabase_jwt_secret=TEST_JWT_SECRET, onshape_client_id="new-app"
    )
    with pytest.raises(QuotaBlockedError):
        await _onshape_meter(settings, redis, ConnectorContext(account_ref="account-a")).admit()


def test_transition_dedupe_follows_verified_application() -> None:
    from solus_api.models import AccountConnection, SourceType
    from solus_api.services.connection_health import _seen_key

    connection = AccountConnection(
        provider=SourceType.ONSHAPE, account_external_id="account-a", config={}
    )
    legacy = _seen_key(connection)
    connection.config = {"_onshape_oauth_application": "a" * 64}
    first = _seen_key(connection)
    connection.config = {"_onshape_oauth_application": "b" * 64}
    assert len({legacy, first, _seen_key(connection)}) == 3
