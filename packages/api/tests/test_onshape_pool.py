"""ADR-038 §4: metering models the bill — owner pool, App Store mode, call labels,
rate-limit observation, the read-out, and tenant isolation."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Literal

import pytest
from conftest import TEST_JWT_SECRET
from solus_api.connectors.quota import CallMeter, QuotaBlockedError, QuotaState
from solus_api.connectors.registry import ConnectorContext, _onshape_meter
from solus_api.core.config import Settings
from test_connections import (  # noqa: F401 — the autouse fixture must be in this namespace
    _bind,
    _connect_account,
    _install_fakes,
    _project,
)
from test_connector_quota import BrokenRedis, FakeRedis

APP = hashlib.sha256(b"app-one").hexdigest()
OTHER_APP = hashlib.sha256(b"app-two").hexdigest()
THRESHOLD = 1750  # 70% of 2,500
POOL_ACCOUNT_A_PREFIX = f"solus:intq:onshape:acct:oauth-app%3A{APP}%3Aaccount%3Aacct-a"


def _settings(
    pool: Literal["owner", "user"] = "owner",
    distribution: Literal["private", "app_store"] = "private",
    client_id: str | None = "app-one",
) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        supabase_jwt_secret=TEST_JWT_SECRET,
        onshape_client_id=client_id,
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
    client_id: str | None = "app-one",
) -> CallMeter:
    return _onshape_meter(
        _settings(pool, distribution, client_id),
        redis,
        ConnectorContext(
            account_ref=account,
            onshape_application=application,
            purpose=purpose,
            label=label,
        ),
    )


# ------------------------------------------------------------ owner pool


async def test_owner_pool_shares_one_ledger_across_accounts() -> None:
    # ADR-038 amendment item 3: the POOL ledger is shared (admission) but each
    # account's read-out shows only its own usage.
    redis = FakeRedis()
    a = _meter(redis, account="acct-a")
    b = _meter(redis, account="acct-b")
    await a.record(200)
    await b.record(200)
    await b.record(200)
    assert redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{a._year}"] == "3"  # noqa: SLF001
    assert (await a.state()).used == 1
    assert (await b.state()).used == 2


async def test_owner_pool_year_key_format() -> None:
    redis = FakeRedis()
    meter = _meter(redis)
    await meter.record(200)
    year = meter._year  # noqa: SLF001
    assert f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}" in redis.values


async def test_owner_pool_degrade_at_seventy_percent_hits_every_account() -> None:
    redis = FakeRedis()
    meter_a = _meter(redis, account="acct-a", purpose="scheduled")
    meter_b = _meter(redis, account="acct-b", purpose="scheduled")
    year = meter_a._year  # noqa: SLF001
    redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}"] = str(THRESHOLD - 1)
    await meter_a.admit()
    await meter_b.admit()
    await meter_a.record(200)
    for blocked in (meter_a, meter_b):
        with pytest.raises(QuotaBlockedError) as err:
            await blocked.admit()
        assert err.value.code == "quota_degraded"
    # A human's explicit action still passes the degraded band.
    await _meter(redis, account="acct-c", purpose="user").admit()


async def test_owner_pool_402s_from_two_accounts_latch_every_account_in_the_pool() -> None:
    # ADR-038 amendment item 2: one 402 latches only its account; the pool
    # latches at two distinct accounts.
    redis = FakeRedis()
    await _meter(redis, account="acct-a").record(402)
    await _meter(redis, account="acct-b").admit()
    await _meter(redis, account="acct-b").record(402)
    with pytest.raises(QuotaBlockedError) as err:
        await _meter(redis, account="acct-c").admit()
    assert err.value.code == "quota_exhausted"
    assert (await _meter(redis, account="acct-c").state()).exhausted


async def test_owner_pool_does_not_cross_oauth_applications() -> None:
    redis = FakeRedis()
    await _meter(redis, application=APP).record(402)
    await _meter(redis, application=OTHER_APP).admit()


async def test_legacy_source_without_application_uses_hashed_client_id() -> None:
    redis = FakeRedis()
    legacy = _meter(redis, application=None, account="acct-a")
    bound = _meter(redis, application=APP, account="acct-b")
    await legacy.record(200)
    assert redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{bound._year}"] == "1", (  # noqa: SLF001
        "legacy fallback joins the app's pool"
    )
    assert all("app-one" not in k for k in redis.values), "raw client id never in a key"
    assert all("shh-secret" not in k for k in redis.values)


async def test_legacy_fallback_never_logs_raw_client_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = FakeRedis()
    with caplog.at_level(logging.DEBUG):
        meter = _meter(redis, application=None)
        await meter.record(402)
        await meter.state()
    assert "app-one" not in caplog.text
    assert "shh-secret" not in caplog.text


async def test_legacy_without_application_or_client_id_stays_per_account() -> None:
    redis = FakeRedis()
    await _meter(redis, application=None, client_id=None, account="acct-a").record(402)
    await _meter(redis, application=None, client_id=None, account="acct-b").admit()


# ------------------------------------------------------------- user mode


async def test_user_mode_keeps_per_account_scope_exactly() -> None:
    redis = FakeRedis()
    a = _meter(redis, pool="user", account="acct-a")
    b = _meter(redis, pool="user", account="acct-b")
    await a.record(200)
    assert (await a.state()).used == 1
    assert (await b.state()).used == 0
    year = a._year  # noqa: SLF001
    assert f"solus:intq:onshape:acct:oauth-app%3A{APP}%3Aaccount%3Aacct-a:{year}" in redis.values


async def test_user_mode_legacy_scope_is_the_bare_account() -> None:
    redis = FakeRedis()
    meter = _meter(redis, pool="user", application=None, account="acct-a")
    await meter.record(402)
    assert redis.values["solus:intq:onshape:acct:acct-a:402"] == "1"
    await _meter(redis, pool="user", application=None, account="acct-b").admit()


async def test_user_mode_402_latches_only_that_account() -> None:
    redis = FakeRedis()
    await _meter(redis, pool="user", account="acct-a").record(402)
    await _meter(redis, pool="user", account="acct-b").admit()
    with pytest.raises(QuotaBlockedError):
        await _meter(redis, pool="user", account="acct-a").admit()


# ------------------------------------------------------------ app store


async def test_app_store_never_degrades_or_blocks_deferrable_work() -> None:
    redis = FakeRedis()
    meter = _meter(redis, distribution="app_store", purpose="scheduled")
    year = meter._year  # noqa: SLF001
    redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}"] = "9999"
    await meter.admit()
    await _meter(redis, distribution="app_store", purpose="agent").admit()
    redis.values[f"{POOL_ACCOUNT_A_PREFIX}:{year}"] = "9999"
    state = await meter.state()
    assert state.used == 9999
    assert not state.degraded
    assert not state.exhausted
    assert state.status == "ok"


async def test_app_store_still_counts_calls() -> None:
    redis = FakeRedis()
    meter = _meter(redis, distribution="app_store")
    await meter.record(200)
    await meter.record(200)
    assert (await meter.state()).used == 2


async def test_app_store_observed_402_still_latches() -> None:
    redis = FakeRedis()
    meter = _meter(redis, distribution="app_store")
    await meter.record(402)
    with pytest.raises(QuotaBlockedError) as err:
        await meter.admit()
    assert err.value.code == "quota_exhausted"
    state = await meter.state()
    assert state.exhausted
    assert state.distribution == "app_store"


async def test_private_degrades_at_ratio() -> None:
    redis = FakeRedis()
    meter = _meter(redis, distribution="private", purpose="scheduled")
    year = meter._year  # noqa: SLF001
    redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}"] = str(THRESHOLD)
    with pytest.raises(QuotaBlockedError):
        await meter.admit()
    assert (await meter.state()).degraded


# ---------------------------------------------------------------- labels


async def test_label_counters_increment_per_label_in_the_pool() -> None:
    redis = FakeRedis()
    await _meter(redis, label="webhook", account="acct-a").record(200)
    await _meter(redis, label="webhook", account="acct-b").record(200)
    await _meter(redis, label="picker").record(200)
    # Amendment item 3: the read-out is the account's own; pool counters sit beside it.
    state = await _meter(redis).state()
    assert state.by_label == {"webhook": 1, "picker": 1}
    assert state.used == 2
    year = _meter(redis)._year  # noqa: SLF001
    assert redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}:webhook"] == "2"
    assert redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}"] == "3"


async def test_default_labels_derive_from_purpose() -> None:
    redis = FakeRedis()
    await _meter(redis, purpose="user").record(200)
    await _meter(redis, purpose="scheduled").record(200)
    await _meter(redis, purpose="scheduled").record(200)
    await _meter(redis, purpose="agent").record(200)
    await _meter(redis, purpose="webhook").record(200)
    assert (await _meter(redis).state()).by_label == {
        "sync": 1,
        "sweep": 2,
        "agent_read": 1,
        "webhook": 1,
    }


async def test_explicit_label_overrides_derivation() -> None:
    redis = FakeRedis()
    await _meter(redis, purpose="agent", label="agent_write").record(200)
    assert (await _meter(redis).state()).by_label == {"agent_write": 1}


async def test_failed_calls_do_not_move_label_counters() -> None:
    redis = FakeRedis()
    meter = _meter(redis, label="sync")
    for code in (404, 429, 500, 402):
        await meter.record(code)
    assert (await meter.state()).by_label == {}


async def test_label_counters_are_per_year_and_have_ttl() -> None:
    redis = FakeRedis()
    meter = _meter(redis, label="recovery")
    await meter.record(200)
    # Amendment item 1: one pool counter and one per-account counter.
    label_keys = [k for k in redis.values if "recovery" in k]
    assert len(label_keys) == 2
    for key in label_keys:
        assert key.endswith("recovery")
        assert str(meter._year) in key  # noqa: SLF001
        assert key in redis.expiries


async def test_user_mode_label_counters_stay_per_account() -> None:
    redis = FakeRedis()
    await _meter(redis, pool="user", account="acct-a", label="sync").record(200)
    assert (await _meter(redis, pool="user", account="acct-b").state()).by_label == {}


async def test_plain_meter_without_label_defaults_to_sync() -> None:
    redis = FakeRedis()
    meter = CallMeter(
        redis,
        provider="onshape",
        account_ref="x",
        year=2026,
        allowance=10,
        degrade_ratio=0.5,
    )
    await meter.record(200)
    assert (await meter.state()).by_label == {"sync": 1}


# --------------------------------------------------------- rate-limit API


async def test_observe_rate_limit_stores_latest_with_short_ttl() -> None:
    redis = FakeRedis()
    meter = _meter(redis)
    await meter.observe_rate_limit(120)
    await meter.observe_rate_limit(80, retry_after=3.0)
    state = await _meter(redis, account="acct-other").state()
    assert state.rate_limit_remaining == 80
    keys = [k for k in redis.values if k.endswith(":rl")]
    assert len(keys) == 1
    assert 0 < redis.expiries[keys[0]] <= 300


async def test_observe_rate_limit_warns_below_ten(caplog: pytest.LogCaptureFixture) -> None:
    meter = _meter(FakeRedis())
    with caplog.at_level(logging.WARNING, logger="solus.connectors.quota"):
        await meter.observe_rate_limit(10)
        assert "rate limit" not in caplog.text.lower()
        await meter.observe_rate_limit(9)
    assert "rate limit" in caplog.text.lower()
    assert "app-one" not in caplog.text


@pytest.mark.parametrize("bad", [-1, -500, 10**9, 2**40])
async def test_observe_rate_limit_ignores_out_of_bounds(bad: int) -> None:
    redis = FakeRedis()
    meter = _meter(redis)
    await meter.observe_rate_limit(60)
    await meter.observe_rate_limit(bad)
    assert (await meter.state()).rate_limit_remaining == 60


async def test_observe_rate_limit_ignores_non_integers_and_none() -> None:
    redis = FakeRedis()
    meter = _meter(redis)
    await meter.observe_rate_limit(None)
    await meter.observe_rate_limit(True)  # bool is not a count
    await meter.observe_rate_limit("5")  # type: ignore[arg-type]
    await meter.observe_rate_limit(5.5)  # type: ignore[arg-type]
    assert (await meter.state()).rate_limit_remaining is None
    assert not [k for k in redis.values if k.endswith(":rl")]


async def test_observe_rate_limit_zero_is_valid() -> None:
    meter = _meter(FakeRedis())
    await meter.observe_rate_limit(0)
    assert (await meter.state()).rate_limit_remaining == 0


async def test_observe_rate_limit_is_per_pool() -> None:
    redis = FakeRedis()
    await _meter(redis, application=APP).observe_rate_limit(40)
    assert (await _meter(redis, application=OTHER_APP).state()).rate_limit_remaining is None


# ---------------------------------------------------------------- fail open


async def test_everything_fails_open_when_redis_raises() -> None:
    class Exploding(FakeRedis):
        async def get(self, key: str) -> str | None:
            raise RuntimeError("down")

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            raise RuntimeError("down")

        async def incr(self, key: str) -> int:
            raise RuntimeError("down")

        async def expire(self, key: str, seconds: int) -> None:
            raise RuntimeError("down")

    for redis in (Exploding(), BrokenRedis(), None):
        meter = _meter(redis, label="sync")
        await meter.admit()
        await meter.record(200)
        await meter.record(402)
        await meter.observe_rate_limit(3)
        state = await meter.state()
        assert state.used == 0
        assert state.by_label == {}
        assert state.rate_limit_remaining is None


async def test_label_write_failure_does_not_lose_the_year_count() -> None:
    class LabelBroken(FakeRedis):
        async def incr(self, key: str) -> int:
            if "sync" in key:
                raise RuntimeError("down")
            return await super().incr(key)

    redis = LabelBroken()
    meter = _meter(redis, label="sync")
    await meter.record(200)
    assert (await meter.state()).used == 1


# ------------------------------------------------------------- the read-out


async def test_state_exposes_pool_distribution_and_defaults() -> None:
    bare = QuotaState(used=1, allowance=2, degraded=False, exhausted=False)
    assert bare.pool == "user"
    assert bare.distribution == "private"
    assert bare.by_label == {}
    assert bare.rate_limit_remaining is None
    state = await _meter(FakeRedis(), distribution="app_store").state()
    assert (state.pool, state.distribution) == ("owner", "app_store")
    assert (await _meter(FakeRedis(), pool="user").state()).pool == "user"


def test_readout_keeps_existing_fields_and_adds_new_ones() -> None:
    state = QuotaState(
        used=5,
        allowance=2500,
        degraded=False,
        exhausted=False,
        pool="owner",
        distribution="private",
        by_label={"sync": 5},
        rate_limit_remaining=77,
    )
    assert state.readout() == {
        "status": "ok",
        "used": 5,
        "allowance": 2500,
        "estimated": True,
        "pool": "owner",
        "distribution": "private",
        "by_label": {"sync": 5},
        "rate_limit_remaining": 77,
    }


def test_readout_by_label_is_a_copy() -> None:
    state = QuotaState(used=1, allowance=2, degraded=False, exhausted=False, by_label={"sync": 1})
    state.readout()["by_label"]["sync"] = 99
    assert state.by_label == {"sync": 1}


async def test_cross_tenant_user_mode_cannot_see_other_numbers() -> None:
    redis = FakeRedis()
    team_a = _meter(redis, pool="user", account="acct-a", application=APP, label="sync")
    team_b = _meter(redis, pool="user", account="acct-b", application=OTHER_APP, label="picker")
    for _ in range(3):
        await team_a.record(200)
    await team_b.record(200)
    await team_a.observe_rate_limit(50)
    a_state, b_state = await team_a.state(), await team_b.state()
    assert (a_state.used, a_state.by_label, a_state.rate_limit_remaining) == (
        3,
        {"sync": 3},
        50,
    )
    assert (b_state.used, b_state.by_label, b_state.rate_limit_remaining) == (
        1,
        {"picker": 1},
        None,
    )


async def test_owner_mode_readout_is_aggregate_only_no_tenant_identity() -> None:
    redis = FakeRedis()
    team_a = _meter(redis, account="acct-secret-a", label="sync")
    team_b = _meter(redis, account="acct-secret-b", label="sweep")
    await team_a.record(200)
    await team_b.record(200)
    payload = (await team_a.state()).readout()
    assert payload["used"] == 1  # amendment item 3: own usage, not the pool total
    assert payload["by_label"] == {"sync": 1}
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
    blob = repr(payload)
    assert "acct-secret" not in blob
    assert uuid.UUID(int=0).hex not in blob


# ------------------------------------------------- sources read-out (HTTP)


def _request(settings: Settings, redis: Any) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, redis=redis))
    )


def _source(application: str | None, account: str) -> Any:
    from datetime import UTC, datetime

    from solus_api.models import Source, SourceStatus, SourceType

    return Source(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        type=SourceType.ONSHAPE,
        name="cad",
        status=SourceStatus.CONNECTED,
        config={"_onshape_oauth_application": application} if application else {},
        account_external_id=account,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def test_sources_quota_states_user_mode_isolates_tenants() -> None:
    from solus_api.routers.sources import _quota_states

    redis = FakeRedis()
    team_a, team_b = _source(APP, "acct-a"), _source(OTHER_APP, "acct-b")
    settings = _settings(pool="user")
    await _meter(redis, pool="user", application=APP, account="acct-a", label="sync").record(200)
    await _meter(redis, pool="user", application=OTHER_APP, account="acct-b").record(402)
    a_states = await _quota_states(_request(settings, redis), [team_a])
    b_states = await _quota_states(_request(settings, redis), [team_b])
    assert set(a_states) == {team_a.id} and set(b_states) == {team_b.id}
    assert a_states[team_a.id].used == 1
    assert a_states[team_a.id].by_label == {"sync": 1}
    assert not a_states[team_a.id].exhausted
    assert b_states[team_b.id].used == 0
    assert b_states[team_b.id].exhausted
    assert b_states[team_b.id].by_label == {}


async def test_sources_quota_states_owner_mode_each_team_sees_only_own_usage() -> None:
    # Replaces the pre-amendment "every team sees pool totals" test (item 3).
    from solus_api.routers.sources import _quota_states

    redis = FakeRedis()
    mine, other_tenant = _source(APP, "acct-a"), _source(APP, "acct-b")
    settings = _settings(pool="owner")
    await _meter(redis, application=APP, account="acct-a", label="sync").record(200)
    for _ in range(3):
        await _meter(redis, application=APP, account="acct-b", label="sweep").record(200)
    states = await _quota_states(_request(settings, redis), [mine, other_tenant])
    assert states[mine.id].used == 1 and states[mine.id].by_label == {"sync": 1}
    assert states[other_tenant.id].used == 3
    assert states[other_tenant.id].by_label == {"sweep": 3}
    redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{_meter(redis)._year}"] = str(  # noqa: SLF001
        THRESHOLD
    )
    states = await _quota_states(_request(settings, redis), [mine, other_tenant])
    assert states[mine.id].status == states[other_tenant.id].status == "degraded"
    assert (states[mine.id].used, states[other_tenant.id].used) == (1, 3)
    for state in states.values():
        payload = state.readout()
        assert "acct-a" not in repr(payload) and "acct-b" not in repr(payload)
        assert payload["pool"] == "owner"


async def test_list_sources_route_carries_the_additive_quota_fields(
    app: Any, client: Any, alice_headers: dict[str, str]
) -> None:

    redis = FakeRedis()
    app.state.redis = redis
    app.state.settings = app.state.settings.model_copy(
        update={
            "onshape_quota_pool": "owner",
            "onshape_client_id": "app-one",
            "onshape_client_secret": "shh-secret",
        }
    )
    connected = await _connect_account(client, alice_headers)
    project_id = await _project(client, alice_headers, "Quota")
    await _bind(client, alice_headers, project_id, connected["connection"]["id"])
    await _onshape_meter(
        app.state.settings, redis, ConnectorContext(account_ref="42", label="picker")
    ).record(200)
    resp = await client.get(f"/api/v1/projects/{project_id}/sources", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["data"]
    quota = row["quota"]
    assert quota["estimated"] is True
    assert quota["pool"] == "owner" and quota["distribution"] == "private"
    assert quota["by_label"] == {"picker": 1}
    assert quota["rate_limit_remaining"] is None
    assert quota["used"] == 1 and quota["allowance"] == 2500 and quota["status"] == "ok"


async def test_registry_honours_agent_purpose_like_scheduled() -> None:
    redis = FakeRedis()
    agent = _meter(redis, purpose="agent")
    year = agent._year  # noqa: SLF001
    redis.values[f"solus:intq:onshape:acct:oauth-app%3A{APP}:{year}"] = str(THRESHOLD)
    with pytest.raises(QuotaBlockedError) as err:
        await agent.admit()
    assert err.value.code == "quota_degraded"
    await _meter(redis, purpose="user").admit()
