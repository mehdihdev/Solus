"""ADR-038 amendment (SOLUSDEV-312): per-account usage beside the owner pool,
account-first 402 latch, own-usage read-out, and the staff-only pool view."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

import pytest
from conftest import ALICE, TEST_DATABASE_URL, TEST_JWT_SECRET, bearer
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.agent.runtime import ScaffoldRunner
from solus_api.connectors.quota import CallMeter, QuotaBlockedError
from solus_api.connectors.registry import ConnectorContext, _onshape_meter
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.models import User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_connector_quota import BrokenRedis, FakeRedis

APP = hashlib.sha256(b"app-one").hexdigest()
OTHER_APP = hashlib.sha256(b"app-two").hexdigest()
THRESHOLD = 1750
POOL_YEAR_PREFIX = f"solus:intq:onshape:acct:oauth-app%3A{APP}"


def _settings(
    pool: Literal["owner", "user"] = "owner",
    distribution: Literal["private", "app_store"] = "private",
) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        supabase_jwt_secret=TEST_JWT_SECRET,
        onshape_client_id="app-one",
        onshape_client_secret="shh-secret",
        onshape_quota_pool=pool,
        onshape_app_distribution=distribution,
    )


def _meter(
    redis: Any,
    *,
    pool: Literal["owner", "user"] = "owner",
    distribution: Literal["private", "app_store"] = "private",
    account: str = "acct-a",
    application: str | None = APP,
    purpose: Any = "user",
    label: Any = None,
) -> CallMeter:
    return _onshape_meter(
        _settings(pool, distribution),
        redis,
        ConnectorContext(
            account_ref=account, onshape_application=application, purpose=purpose, label=label
        ),
    )


def _year() -> int:
    return _meter(None)._year  # noqa: SLF001


def _set_pool_used(redis: FakeRedis, used: int) -> None:
    redis.values[f"{POOL_YEAR_PREFIX}:{_year()}"] = str(used)


# ------------------------------------------------------------ ledgers


async def test_owner_mode_increments_pool_and_account_ledgers() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-a", label="sync").record(200)
    await _meter(redis, account="acct-a", label="picker").record(200)
    await _meter(redis, account="acct-b", label="sweep").record(200)
    year = _year()
    assert redis.values[f"{POOL_YEAR_PREFIX}:{year}"] == "3"
    assert redis.values[f"{POOL_YEAR_PREFIX}:{year}:sync"] == "1"
    acct_a = f"solus:intq:onshape:acct:oauth-app%3A{APP}%3Aaccount%3Aacct-a:{year}"
    acct_b = f"solus:intq:onshape:acct:oauth-app%3A{APP}%3Aaccount%3Aacct-b:{year}"
    assert redis.values[acct_a] == "2"
    assert redis.values[f"{acct_a}:sync"] == "1"
    assert redis.values[f"{acct_a}:picker"] == "1"
    assert redis.values[acct_b] == "1"
    assert redis.expiries[acct_a] > 0 and redis.expiries[f"{acct_a}:sync"] > 0


async def test_readout_is_own_usage_while_status_band_is_the_pools() -> None:
    redis = FakeRedis()
    a, b = _meter(redis, account="acct-a", label="sync"), _meter(redis, account="acct-b")
    await a.record(200)
    await a.record(200)
    await b.record(200)
    sa, sb = await a.state(), await b.state()
    assert (sa.used, sa.by_label) == (2, {"sync": 2})
    assert (sb.used, sb.by_label) == (1, {"sync": 1})
    assert sa.allowance == sb.allowance == 2500
    assert sa.status == sb.status == "ok"
    # The pool crosses 70 %: BOTH teams flip, each still showing only their own calls.
    _set_pool_used(redis, THRESHOLD)
    sa, sb = await a.state(), await b.state()
    assert sa.status == sb.status == "degraded"
    assert (sa.used, sb.used) == (2, 1)
    assert sa.readout()["used"] == 2 and sb.readout()["used"] == 1


async def test_pool_exhaustion_band_applies_to_every_account() -> None:
    redis = FakeRedis()
    _set_pool_used(redis, 2500)
    assert (await _meter(redis, account="acct-b").state()).status == "exhausted"


async def test_readout_shape_has_no_pool_totals_or_identifiers() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-secret-a", label="sync").record(200)
    await _meter(redis, account="acct-secret-b", label="sweep").record(200)
    payload = (await _meter(redis, account="acct-secret-a").state()).readout()
    assert payload["used"] == 1 and payload["by_label"] == {"sync": 1}
    assert set(payload) == {
        "status",
        "used",
        "allowance",
        "estimated",
        "pool",
        "distribution",
        "by_label",
        "rate_limit_remaining",
    }
    assert payload["estimated"] is True and payload["pool"] == "owner"
    assert "acct-secret" not in repr(payload)


async def test_admission_stays_pool_based_with_no_per_account_cap() -> None:
    redis = FakeRedis()
    a = _meter(redis, account="acct-a", purpose="scheduled")
    for _ in range(5):
        await a.record(200)
    await a.admit()  # one account's own usage never blocks it below the pool band
    _set_pool_used(redis, THRESHOLD)
    for account in ("acct-a", "acct-fresh"):
        with pytest.raises(QuotaBlockedError) as err:
            await _meter(redis, account=account, purpose="scheduled").admit()
        assert err.value.code == "quota_degraded"
    await _meter(redis, account="acct-fresh", purpose="user").admit()


async def test_user_mode_has_a_single_per_account_ledger() -> None:
    redis = FakeRedis()
    meter = _meter(redis, pool="user", account="acct-a", label="sync")
    await meter.record(200)
    year = _year()
    ledger_keys = {k for k in redis.values if k.endswith(f":{year}")}
    assert ledger_keys == {f"solus:intq:onshape:acct:oauth-app%3A{APP}%3Aaccount%3Aacct-a:{year}"}
    assert (await meter.state()).used == 1
    assert not redis.sets.get("solus:intq:onshape:pools")


# ------------------------------------------------------------ 402 latch


async def test_402_latches_only_the_calling_account() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-a").record(402)
    with pytest.raises(QuotaBlockedError) as err:
        await _meter(redis, account="acct-a").admit()
    assert err.value.code == "quota_exhausted"
    await _meter(redis, account="acct-b").admit()
    state_a, state_b = (
        await _meter(redis, account="acct-a").state(),
        await _meter(redis, account="acct-b").state(),
    )
    assert state_a.status == "exhausted" and state_b.status == "ok"
    year = _year()
    latch = f"solus:intq:onshape:acct:oauth-app%3A{APP}%3Aaccount%3Aacct-a:402"
    assert redis.values[latch] == "1" and redis.expiries[latch] == 24 * 3600
    assert f"{POOL_YEAR_PREFIX}:402" not in redis.values
    assert f"{POOL_YEAR_PREFIX}:{year}" not in redis.values  # a 402 is not a counted call


async def test_402_accounts_set_is_hashed_with_a_24h_ttl() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-a").record(402)
    key = f"{POOL_YEAR_PREFIX}:402accts"
    members = redis.sets[key]
    assert len(members) == 1
    assert "acct-a" not in repr(members)
    assert redis.expiries[key] == 24 * 3600


async def test_same_account_402_twice_never_latches_the_pool() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-a").record(402)
    await _meter(redis, account="acct-a").record(402)
    await _meter(redis, account="acct-b").admit()


async def test_second_distinct_account_402_latches_the_pool_for_everyone() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-a").record(402)
    await _meter(redis, account="acct-b").record(402)
    for account in ("acct-a", "acct-b", "acct-c"):
        with pytest.raises(QuotaBlockedError) as err:
            await _meter(redis, account=account).admit()
        assert err.value.code == "quota_exhausted"
    assert (await _meter(redis, account="acct-c").state()).status == "exhausted"
    assert redis.expiries[f"{POOL_YEAR_PREFIX}:402"] == 24 * 3600


async def test_402_in_another_application_pool_does_not_count() -> None:
    redis = FakeRedis()
    await _meter(redis, account="acct-a", application=APP).record(402)
    await _meter(redis, account="acct-b", application=OTHER_APP).record(402)
    await _meter(redis, account="acct-c", application=APP).admit()
    await _meter(redis, account="acct-c", application=OTHER_APP).admit()


async def test_402_accounts_set_is_bounded() -> None:
    redis = FakeRedis()
    key = f"{POOL_YEAR_PREFIX}:402accts"
    redis.sets[key] = {f"h{i}" for i in range(64)}
    await _meter(redis, account="acct-new").record(402)
    assert len(redis.sets[key]) == 64


async def test_user_mode_402_is_per_account_only() -> None:
    redis = FakeRedis()
    await _meter(redis, pool="user", account="acct-a").record(402)
    await _meter(redis, pool="user", account="acct-b").record(402)
    for account in ("acct-a", "acct-b"):
        with pytest.raises(QuotaBlockedError):
            await _meter(redis, pool="user", account=account).admit()
    await _meter(redis, pool="user", account="acct-c").admit()
    assert not [k for k in redis.sets if "402accts" in k]


async def test_app_store_latches_still_apply() -> None:
    redis = FakeRedis()
    kw: dict[str, Any] = {"distribution": "app_store"}
    await _meter(redis, account="acct-a", **kw).record(402)
    with pytest.raises(QuotaBlockedError):
        await _meter(redis, account="acct-a", **kw).admit()
    await _meter(redis, account="acct-b", **kw).admit()
    await _meter(redis, account="acct-b", **kw).record(402)
    with pytest.raises(QuotaBlockedError):
        await _meter(redis, account="acct-c", **kw).admit()
    state = await _meter(redis, account="acct-c", **kw).state()
    assert state.exhausted and state.distribution == "app_store"


async def test_latch_accounting_fails_open() -> None:
    class SetsBroken(FakeRedis):
        async def sadd(self, key: str, *members: str) -> int:
            raise RuntimeError("down")

    redis = SetsBroken()
    await _meter(redis, account="acct-a").record(402)
    with pytest.raises(QuotaBlockedError):
        await _meter(redis, account="acct-a").admit()  # the account latch still landed
    for broken in (BrokenRedis(), None):
        meter = _meter(broken)
        await meter.record(402)
        await meter.record(200)
        await meter.admit()
        assert (await meter.state()).used == 0


async def test_account_ledger_failure_does_not_lose_the_pool_count() -> None:
    class AccountBroken(FakeRedis):
        async def incr(self, key: str) -> int:
            if "%3Aaccount%3A" in key:
                raise RuntimeError("down")
            return await super().incr(key)

    redis = AccountBroken()
    await _meter(redis).record(200)
    assert redis.values[f"{POOL_YEAR_PREFIX}:{_year()}"] == "1"


# ------------------------------------------------------------ staff view

STAFF_ID = uuid.UUID("00000000-0000-0000-0000-00000000f00e")
STAFF_SUB = "staff-sub-quota"
STAFF_EMAIL = "staff-quota@solus.test"
URL = "/api/v1/staff/integrations/onshape/quota"


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience="authenticated",
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
        sync_inline=True,
        staff_user_ids=str(STAFF_ID),
        onshape_client_id="app-one",
        onshape_client_secret="shh-secret",
    )


@pytest.fixture
async def staff_app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    application = create_app(settings=settings, engine=engine)
    application.state.agent_runner = ScaffoldRunner()
    application.state.redis = FakeRedis()
    return application


@pytest.fixture
async def staff_client(staff_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=staff_app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def users(db: AsyncSession) -> None:
    db.add_all(
        [
            User(
                id=STAFF_ID,
                supabase_user_id=STAFF_SUB,
                email=STAFF_EMAIL,
                data_collection_consent=True,
            ),
            User(supabase_user_id=ALICE["sub"], email=ALICE["email"]),
        ]
    )
    await db.commit()


def _staff() -> dict[str, str]:
    headers: dict[str, str] = bearer(STAFF_SUB, STAFF_EMAIL)
    return headers


async def test_staff_route_requires_authentication(staff_client: AsyncClient) -> None:
    assert (await staff_client.get(URL)).status_code == 401


async def test_staff_route_refuses_non_staff(
    staff_client: AsyncClient, users: None, alice_headers: dict[str, str]
) -> None:
    resp = await staff_client.get(URL, headers=alice_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


async def test_staff_route_with_no_redis_is_empty_not_an_error(
    staff_app: FastAPI, staff_client: AsyncClient, users: None
) -> None:
    staff_app.state.redis = None
    resp = await staff_client.get(URL, headers=_staff())
    assert resp.status_code == 200
    assert resp.json()["data"]["pools"] == []


async def test_staff_sees_pool_totals_without_any_identifier(
    staff_app: FastAPI, staff_client: AsyncClient, users: None
) -> None:
    redis = staff_app.state.redis
    await _meter(redis, account="acct-secret-a", label="sync").record(200)
    await _meter(redis, account="acct-secret-a", label="sync").record(200)
    await _meter(redis, account="acct-secret-b", label="picker").record(200)
    await _meter(redis, account="acct-secret-b").observe_rate_limit(42)
    await _meter(redis, account="acct-secret-a").record(402)
    resp = await staff_client.get(URL, headers=_staff())
    assert resp.status_code == 200, resp.text
    [pool] = resp.json()["data"]["pools"]
    assert set(pool) == {
        "pool_scope_hash",
        "used",
        "allowance",
        "by_label",
        "latched",
        "latched_accounts_count",
        "rate_limit_remaining",
        "distribution",
    }
    assert pool["pool_scope_hash"] == hashlib.sha256(f"oauth-app:{APP}".encode()).hexdigest()
    assert pool["used"] == 3 and pool["allowance"] == 2500
    assert pool["by_label"] == {"sync": 2, "picker": 1}
    assert pool["latched"] is False and pool["latched_accounts_count"] == 1
    assert pool["rate_limit_remaining"] == 42 and pool["distribution"] == "private"
    blob = resp.text
    assert "acct-secret" not in blob and APP not in blob
    assert "email" not in blob


async def test_staff_view_reports_the_pool_latch_and_each_pool_separately(
    staff_app: FastAPI, staff_client: AsyncClient, users: None
) -> None:
    redis = staff_app.state.redis
    await _meter(redis, account="a", application=APP).record(402)
    await _meter(redis, account="b", application=APP).record(402)
    await _meter(redis, account="c", application=OTHER_APP).record(200)
    resp = await staff_client.get(URL, headers=_staff())
    pools = {p["pool_scope_hash"]: p for p in resp.json()["data"]["pools"]}
    assert len(pools) == 2
    latched = pools[hashlib.sha256(f"oauth-app:{APP}".encode()).hexdigest()]
    other = pools[hashlib.sha256(f"oauth-app:{OTHER_APP}".encode()).hexdigest()]
    assert latched["latched"] is True and latched["latched_accounts_count"] == 2
    assert other["latched"] is False and other["used"] == 1
