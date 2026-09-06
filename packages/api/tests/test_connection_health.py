"""HOME H4 (SOLUSDEV-244) — health and quota per connected account.

One person consumed most of an Onshape allowance while testing; the meter
(SOLUSDEV-167) counted it and nothing surfaced it. Home's account card now
carries, per grant, a derived HEALTH (healthy / token_expired / degraded) and,
for metered providers, the meter's ESTIMATED position — read from the ledger,
never inferred from a sync error, never probed live (a probe would spend the
allowance the card protects). Each state transition into the degraded band or
the wall is recorded once as a data event (CLAUDE.md §7 abuse detection).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from conftest import BOB, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.quota import QuotaState
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    DataEvent,
    SourceType,
)
from solus_api.services.connection_health import connection_health
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_connections import (  # noqa: F401 — the autouse fixture must be in this namespace
    _bind,
    _connect_account,
    _connections,
    _install_fakes,
    _project,
)
from test_connector_quota import FakeRedis

ALLOWANCE = 1800  # settings.onshape_annual_call_allowance
LEDGER = f"solus:intq:onshape:acct:42:{datetime.now(UTC).year}"  # FakeGitHub external_id "42"
LATCH = "solus:intq:onshape:acct:42:402"


def _connection(status: ConnectionStatus = ConnectionStatus.CONNECTED) -> AccountConnection:
    return AccountConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider=SourceType.ONSHAPE,
        status=status,
        account_external_id="42",
        secret_ref="connection/x/onshape",
        config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ------------------------------------------------------------ the derivation


def test_health_is_derived_never_probed() -> None:
    ok = QuotaState(used=10, allowance=ALLOWANCE, degraded=False, exhausted=False)
    degraded = QuotaState(used=1440, allowance=ALLOWANCE, degraded=True, exhausted=False)
    exhausted = QuotaState(used=1440, allowance=ALLOWANCE, degraded=True, exhausted=True)
    assert connection_health(_connection(), quota=None, source_error_codes=()) == "healthy"
    assert connection_health(_connection(), quota=ok, source_error_codes=()) == "healthy"
    assert connection_health(_connection(), quota=degraded, source_error_codes=()) == "degraded"
    assert connection_health(_connection(), quota=exhausted, source_error_codes=()) == "degraded"
    # A failed handshake, or a bound source the provider rejected, means the
    # token is gone — and that outranks quota: re-auth comes first.
    assert (
        connection_health(
            _connection(ConnectionStatus.ERROR), quota=degraded, source_error_codes=()
        )
        == "token_expired"
    )
    assert (
        connection_health(_connection(), quota=ok, source_error_codes=("invalid_credentials",))
        == "token_expired"
    )
    # Other sync failures are the source's problem, not the grant's.
    assert (
        connection_health(_connection(), quota=ok, source_error_codes=("api_unreachable",))
        == "healthy"
    )


# ------------------------------------------------------------------ the route


async def _consent(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"data_collection_consent": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def _events(db: AsyncSession, event_type: str) -> list[DataEvent]:
    return list(
        (await db.scalars(select(DataEvent).where(DataEvent.event_type == event_type))).all()
    )


async def test_a_healthy_account_with_no_ledger_carries_health_and_no_quota(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """No Redis ⇒ the position is unknowable; a quota block that said "ok" would
    be a fiction. Health still derives from what the row knows."""
    app.state.redis = None
    await _connect_account(client, alice_headers)
    [row] = await _connections(client, alice_headers)
    assert row["health"] == "healthy"
    assert "quota" not in row
    assert row["needs_reauth"] is None


async def test_an_account_at_eighty_percent_is_flagged_and_recorded_once(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Acceptance: an account at 80% is visibly flagged — from the meter, labelled
    an estimate — and the transition is one data event, not one per Home load."""
    redis = FakeRedis()
    app.state.redis = redis
    await _consent(client, alice_headers)
    connected = await _connect_account(client, alice_headers)
    redis.values[LEDGER] = str(int(ALLOWANCE * 0.8))

    [row] = await _connections(client, alice_headers)
    assert row["health"] == "degraded"
    assert row["quota"] == {
        "status": "degraded",
        "used": 1440,
        "allowance": ALLOWANCE,
        "estimated": True,
    }
    [event] = await _events(db, "integration.quota_degraded")
    assert event.payload["provider"] == "onshape"
    assert event.payload["connection_id"] == connected["connection"]["id"]
    assert event.payload["used"] == 1440 and event.payload["estimated"] is True

    await _connections(client, alice_headers)
    single = await client.get(
        f"/api/v1/users/me/connections/{connected['connection']['id']}", headers=alice_headers
    )
    assert single.status_code == 200 and single.json()["data"]["health"] == "degraded"
    assert len(await _events(db, "integration.quota_degraded")) == 1


async def test_at_the_wall_the_account_reads_exhausted_not_errored(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Acceptance: at the wall the card explains cache-only mode rather than an
    error — so the grant stays CONNECTED, health is `degraded`, and the quota
    block says `exhausted`; a fresh transition records its own event."""
    redis = FakeRedis()
    app.state.redis = redis
    await _consent(client, alice_headers)
    await _connect_account(client, alice_headers)
    redis.values[LEDGER] = str(int(ALLOWANCE * 0.8))
    await _connections(client, alice_headers)
    redis.values[LATCH] = "1"

    [row] = await _connections(client, alice_headers)
    assert row["status"] == "connected" and row["needs_reauth"] is None
    assert row["health"] == "degraded"
    assert row["quota"]["status"] == "exhausted"
    assert len(await _events(db, "integration.quota_degraded")) == 1
    assert len(await _events(db, "integration.quota_exhausted")) == 1
    await _connections(client, alice_headers)
    assert len(await _events(db, "integration.quota_exhausted")) == 1


async def test_a_rejected_token_on_a_bound_source_means_token_expired(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    app.state.redis = None
    project_id = await _project(client, alice_headers)
    connected = await _connect_account(client, alice_headers)
    source = await _bind(client, alice_headers, project_id, connected["connection"]["id"])
    from solus_api.models import Source

    row = await db.get(Source, uuid.UUID(source["id"]))
    assert row is not None
    row.last_error = {"code": "invalid_credentials", "message": "Onshape rejected the credentials"}
    await db.commit()

    [listed] = await _connections(client, alice_headers)
    assert listed["health"] == "token_expired"


async def test_a_failed_handshake_is_token_expired_and_offers_reauth(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    app.state.redis = None
    connected = await _connect_account(client, alice_headers)
    row = await db.get(AccountConnection, uuid.UUID(connected["connection"]["id"]))
    assert row is not None
    row.status = ConnectionStatus.ERROR
    row.last_error = {"code": "token_error", "message": "token revoked"}
    await db.commit()

    [listed] = await _connections(client, alice_headers)
    assert listed["health"] == "token_expired"
    assert listed["needs_reauth"] == "token_error"


async def test_an_unmetered_provider_carries_health_only(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """GitHub has no ledger: nothing about quota is said — empty beats invented."""
    app.state.redis = FakeRedis()
    await _connect_account(client, alice_headers, provider="github")
    [row] = await _connections(client, alice_headers)
    assert row["provider"] == "github"
    assert row["health"] == "healthy"
    assert "quota" not in row


async def test_health_and_quota_are_owner_only(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Cross-tenant: Bob never sees Alice's grant, its health, or its position."""
    redis = FakeRedis()
    app.state.redis = redis
    await _connect_account(client, alice_headers)
    redis.values[LEDGER] = str(ALLOWANCE)
    from conftest import bearer

    bob = bearer(BOB["sub"], BOB["email"])
    await me(client, bob)
    assert await _connections(client, bob) == []
