"""SOLUSDEV-167 acceptance #5: quota accounting and degradation.

ADR-019 as amended 2026-08-30 — a SECOND budget, separate from credits, because
a provider's annual call allowance is a unit Solus neither buys nor can convert.
"""

from __future__ import annotations

from typing import Any

import pytest
from solus_api.connectors.quota import CallMeter, QuotaBlockedError


class FakeRedis:
    """Just the four commands the meter uses."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def incr(self, key: str) -> int:
        nxt = int(self.values.get(key, 0)) + 1
        self.values[key] = str(nxt)
        return nxt

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


class BrokenRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        raise RuntimeError("down")

    async def incr(self, key: str) -> int:
        raise RuntimeError("down")


def _meter(
    redis: Any,
    *,
    purpose: Any = "user",
    allowance: int = 100,
    used: int = 0,
    account: str = "acct-A",
) -> CallMeter:
    meter = CallMeter(
        redis,
        provider="onshape",
        account_ref=account,
        year=2026,
        allowance=allowance,
        degrade_ratio=0.6,
        purpose=purpose,
    )
    if redis is not None and used:
        redis.values[f"solus:intq:onshape:acct:{account}:2026"] = str(used)
    return meter


# ------------------------------------------------------------------ counting


async def test_only_2xx_and_3xx_move_the_ledger() -> None:
    """The provider's own rule. A 429 or a 404 is FREE, which is why the retry
    ladders cost wall-clock rather than quota — getting that wrong would make
    every rate-limit storm look like budget spend."""
    redis = FakeRedis()
    meter = _meter(redis)

    for code in (200, 201, 302):
        await meter.record(code)
    for code in (404, 429, 500):
        await meter.record(code)

    assert redis.values["solus:intq:onshape:acct:acct-A:2026"] == "3"


async def test_the_ledger_gets_a_ttl_on_first_use() -> None:
    redis = FakeRedis()
    await _meter(redis).record(200)

    assert redis.expiries["solus:intq:onshape:acct:acct-A:2026"] > 365 * 24 * 3600


# ---------------------------------------------------------------- admission


async def test_below_the_threshold_everything_is_admitted() -> None:
    redis = FakeRedis()
    for purpose in ("user", "scheduled", "agent"):
        await _meter(redis, purpose=purpose, used=10).admit()  # no raise


async def test_the_degraded_band_pauses_deferrable_work_only() -> None:
    """Above the ratio, sweeps and agent turns wait; a human's explicit click
    still reaches the provider. Refusing a deliberate action to protect a budget
    the user owns is worse than spending the call."""
    redis = FakeRedis()

    await _meter(redis, purpose="user", used=70).admit()  # allowed

    for purpose in ("scheduled", "agent"):
        with pytest.raises(QuotaBlockedError) as caught:
            await _meter(redis, purpose=purpose, used=70).admit()
        assert caught.value.code == "quota_degraded"


async def test_a_degraded_refusal_is_no_signal_never_a_change() -> None:
    """HOME H4 (SOLUSDEV-244): the degraded band's refusal must classify as
    "could not ask", exactly like exhaustion — otherwise the hourly sweep turns
    the refusal into a full sync that is itself refused (the amplifier)."""
    from solus_api.connectors.contracts import NO_SIGNAL_CODES

    with pytest.raises(QuotaBlockedError) as caught:
        await _meter(FakeRedis(), purpose="scheduled", used=60).admit()
    assert caught.value.code == "quota_degraded"
    assert caught.value.code in NO_SIGNAL_CODES
    assert "quota_exhausted" in NO_SIGNAL_CODES


async def test_past_the_allowance_even_a_user_action_is_refused() -> None:
    redis = FakeRedis()

    with pytest.raises(QuotaBlockedError) as caught:
        await _meter(redis, purpose="user", used=100).admit()

    assert caught.value.code == "quota_exhausted"


async def test_an_observed_402_latches_and_blocks_everything() -> None:
    """The provider's 402 is the only AUTHORITATIVE exhaustion signal — our own
    count is a floor, since it starts when the counter does. So a real 402 must
    stop spend even when the ledger reads zero."""
    redis = FakeRedis()
    meter = _meter(redis)

    await meter.record(402)

    with pytest.raises(QuotaBlockedError) as caught:
        await _meter(redis, purpose="user").admit()
    assert caught.value.code == "quota_exhausted"


async def test_a_402_does_not_count_itself_as_spend() -> None:
    redis = FakeRedis()
    await _meter(redis).record(402)

    assert "solus:intq:onshape:acct:acct-A:2026" not in redis.values


# ------------------------------------------------------------- tenant safety


async def test_two_accounts_never_share_a_ledger() -> None:
    redis = FakeRedis()

    await _meter(redis, account="acct-A").record(200)
    await _meter(redis, account="acct-B").record(200)

    assert redis.values["solus:intq:onshape:acct:acct-A:2026"] == "1"
    assert redis.values["solus:intq:onshape:acct:acct-B:2026"] == "1"


async def test_one_accounts_402_does_not_latch_another() -> None:
    """The collision that would let one tenant deny service to another."""
    redis = FakeRedis()

    await _meter(redis, account="acct-A").record(402)

    await _meter(redis, account="acct-B", purpose="user").admit()  # must not raise


# -------------------------------------------------------------- failing open


async def test_no_redis_means_no_enforcement_and_that_is_deliberate() -> None:
    """ADR-024: an accounting write never fails a user's request. A silently
    fail-CLOSED meter would take every integration down the moment Redis
    hiccupped, which is far worse than not counting."""
    meter = _meter(None, purpose="scheduled")

    await meter.admit()  # must not raise
    await meter.record(200)  # must not raise


async def test_a_broken_redis_fails_open_too() -> None:
    meter = _meter(BrokenRedis(), purpose="scheduled")

    await meter.admit()
    await meter.record(200)


# -------------------------------------------------------------------- state


async def test_the_reported_state_is_always_flagged_estimated() -> None:
    """We count only our own calls from whenever the counter started, so the
    number is a floor on our spend and never a remaining balance. The UI must not
    be able to present it as one."""
    redis = FakeRedis()
    state = await _meter(redis, used=70).state()

    assert state.estimated is True
    assert state.used == 70
    assert state.degraded is True
    assert state.exhausted is False
    assert state.status == "degraded"


async def test_a_latched_account_reports_exhausted() -> None:
    redis = FakeRedis()
    await _meter(redis).record(402)

    assert (await _meter(redis).state()).status == "exhausted"


# ------------------------------------------------ the visible state (AC#5 UI)


def test_the_source_payload_carries_the_quota_block() -> None:
    """Acceptance #5's VISIBLE half. Read from the meter, never inferred from
    `last_error` — that is written only when a SYNC fails, so a team pushed into
    the degraded band by SOL tool traffic and picker opens alone would otherwise
    report healthy."""
    import uuid
    from datetime import UTC, datetime

    from solus_api.connectors.quota import QuotaState
    from solus_api.models import Source, SourceStatus, SourceType
    from solus_api.schemas import serialize_source

    source = Source(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        type=SourceType.ONSHAPE,
        name="onshape",
        status=SourceStatus.CONNECTED,
        config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    plain = serialize_source(source)
    assert "quota" not in plain, "no block at all beats a fictional one"

    degraded = serialize_source(
        source, quota=QuotaState(used=1400, allowance=1800, degraded=True, exhausted=False)
    )
    assert degraded["quota"] == {
        "status": "degraded",
        "used": 1400,
        "allowance": 1800,
        "estimated": True,
    }


def test_the_surfaced_position_is_never_presented_as_a_balance() -> None:
    """We count only our own calls from whenever the counter started, so the
    number is a floor on OUR spend — never what the provider has left. The flag
    is not optional and the UI must render it."""
    from solus_api.connectors.quota import QuotaState

    assert QuotaState(used=0, allowance=1800, degraded=False, exhausted=False).estimated is True


# --------------------------------------- the picker: metered AND role-gated


def test_a_route_connector_is_metered_by_default() -> None:
    """CRIT-1. The meter used to be opt-in, and `_resolve_connector` called the
    PLAIN factory — so `GET /sources/{id}/selectable`, which walks up to 10
    quota-counted pages per open, spent an annual allowance unmetered and
    unlatched: a 402 could not even stop it.

    An opt-in meter that most construction sites skip is not a budget, so the
    default is now scoped-and-metered. This pins that: given a source and a
    context, the connector comes back carrying a meter.
    """
    import uuid
    from dataclasses import dataclass
    from datetime import UTC, datetime

    from solus_api.models import Source, SourceStatus, SourceType
    from solus_api.routers.sources import _resolve_connector

    @dataclass
    class _Ctx:
        project: object
        team: object
        user: object

    @dataclass
    class _Id:
        id: uuid.UUID

    from solus_api.connectors.registry import build_registry

    # A minimal settings stand-in: `build_registry` reads only the provider
    # credentials and the quota knobs off it.
    @dataclass
    class _Settings:
        github_client_id: str = ""
        github_client_secret: str = ""
        gitlab_client_id: str = ""
        gitlab_client_secret: str = ""
        gitlab_base_url: str = "https://gitlab.com"
        onshape_client_id: str = "cid"
        onshape_client_secret: str = "sec"
        onshape_annual_call_allowance: int = 1800
        integration_degrade_ratio: float = 0.7
        integration_signal_ttl_seconds: int = 3600
        integration_signal_sweep_reuse_seconds: int = 300

    registry = build_registry(_Settings(), redis=FakeRedis())  # type: ignore[arg-type]
    source = Source(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        type=SourceType.ONSHAPE,
        name="onshape",
        status=SourceStatus.CONNECTED,
        config={},
        account_external_id="acct-A",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    ctx = _Ctx(project=_Id(uuid.uuid4()), team=_Id(uuid.uuid4()), user=_Id(uuid.uuid4()))

    connector = _resolve_connector(registry, "onshape", source=source, ctx=ctx)

    assert connector._meter is not None, "a route-built connector reached Onshape unmetered"


async def test_a_viewer_cannot_open_the_document_picker(
    client: Any, alice_headers: Any, bob_headers: Any
) -> None:
    """The other half of CRIT-1: the picker had no `require_role`, unlike every
    sibling route in that file — so the lowest-privilege principal in the system
    could spend the account's annual allowance ten calls at a time."""
    from conftest import BOB, add_member, create_project, create_team

    team = await create_team(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="viewer")
    project = await create_project(client, alice_headers, team["id"])
    created = await client.post(
        f"/api/v1/projects/{project['id']}/sources",
        json={"type": "onshape", "name": "cad"},
        headers=alice_headers,
    )
    if created.status_code != 201:  # pragma: no cover - connect flow varies
        pytest.skip(f"could not create a source: {created.text}")
    source_id = created.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/projects/{project['id']}/sources/{source_id}/selectable",
        headers=bob_headers,
    )

    assert resp.status_code == 403, "a viewer opened the quota-spending picker"
