"""Durable Onshape hint generations never acknowledge a newer arrival."""

from unittest.mock import AsyncMock

import httpx
import pytest
from solus_api.services.onshape_webhooks import (
    acknowledge_state,
    healthy_subscription,
    hint_state,
    register_onshape_webhooks,
    revoke_onshape_webhooks,
    state_for,
)
from test_onshape_write_sync import scope as scope_fixture


@pytest.fixture
async def webhook_scope(engine):
    return await scope_fixture.__wrapped__(engine)


def test_duplicate_delivery_does_not_increment_generation():
    first = hint_state({}, event_id="event1")
    assert hint_state(first, event_id="event1")["generation"] == 1


def test_acknowledging_captured_generation_preserves_later_hint():
    first = hint_state({}, event_id="one")
    second = hint_state(first, event_id="two")
    acknowledged = acknowledge_state(second, 1)
    assert acknowledged["generation"] == 2
    assert acknowledged["acknowledged"] == 1


def test_unverified_subscription_cannot_disable_polling():
    assert not healthy_subscription(
        {"status": "registered", "subscriptions": {"doc": "id"}}, ["doc"]
    )


def test_dedup_storage_is_bounded_without_losing_dirty_generation():
    state = {}
    for index in range(300):
        state = hint_state(state, event_id=str(index))
    assert state["generation"] == 300
    assert len(state["events"]) <= 128


def test_callback_refuses_private_and_non_https_destinations():
    from solus_api.services.onshape_webhooks import public_callback

    for base in [
        "http://service.example",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://service.local",
        "https://user:pw@service.example",
    ]:
        assert not public_callback(base)
    assert public_callback("https://api.solus.example")


def test_dirty_generation_wins_over_healthy_subscription():
    from solus_api.connectors.worker import _onshape_disposition

    assert (
        _onshape_disposition(
            "onshape",
            {"documents": ["doc"], "_onshape_webhook": {"generation": 2, "acknowledged": 1}},
        )
        == "dirty"
    )


async def test_local_callback_never_calls_vendor(webhook_scope):
    maker, source, _ = webhook_scope
    connector = AsyncMock()
    async with maker() as db:
        row = await db.get(type(source), source.id)
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), "http://localhost:8000"
        )
    assert state["status"] == "unavailable"
    connector.request.assert_not_called()


async def test_registration_scoped_to_selected_documents_and_revocation(webhook_scope):
    maker, source, _ = webhook_scope
    connector = AsyncMock()
    connector.request.return_value = httpx.Response(200, json={"id": "webhook1"})
    async with maker() as db:
        row = await db.get(type(source), source.id)
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), "https://api.solus.example"
        )
        assert state["status"] == "registered"
        assert not healthy_subscription(state, ["doc1"])
        body = connector.request.call_args.kwargs["json_body"]
        assert body["documentId"] == "doc1"
        assert body["isTransient"] is False
        assert "token" not in str(state)
        await revoke_onshape_webhooks(db, row, connector, AsyncMock())
        assert state_for(row)["status"] == "revoked"
        assert "_webhook_token_sha256" not in row.config
        assert connector.request.call_args.args[1:3] == ("DELETE", "/api/v6/webhooks/webhook1")


async def test_registration_failure_never_claims_healthy(webhook_scope):
    maker, source, _ = webhook_scope
    connector = AsyncMock()
    connector.request.side_effect = RuntimeError("secret callback URL must not be logged")
    async with maker() as db:
        row = await db.get(type(source), source.id)
        result = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), "https://api.solus.example"
        )
        assert result["status"] == "failed"


def test_verified_idle_subscription_stays_healthy():
    from datetime import timedelta

    from solus_api.models import utcnow

    state = {
        "status": "registered",
        "subscriptions": {"doc": "id"},
        "deliveries": {"doc": (utcnow() - timedelta(days=30)).isoformat()},
    }
    assert healthy_subscription(state, ["doc"])
    assert not healthy_subscription(state, ["other"])
    state["deliveries"]["doc"] = "invalid"
    assert not healthy_subscription(state, ["doc"])


def test_debounce_lease_expires_and_malformed_value_recovers():
    from solus_api.services.onshape_webhooks import claim_schedule

    state, claimed = claim_schedule({})
    assert claimed
    assert not claim_schedule(state)[1]
    assert claim_schedule({"scheduled_until": "invalid"})[1]


async def test_registration_revocation_during_request_cannot_resurrect_scope(webhook_scope):
    maker, source, _ = webhook_scope
    connector = AsyncMock()

    async def revoked(*args, **kwargs):
        if args[1] == "DELETE":
            return httpx.Response(200, json={})
        async with maker() as other:
            row = await other.get(type(source), source.id)
            await revoke_onshape_webhooks(other, row)
        return httpx.Response(200, json={"id": "raced-webhook"})

    connector.request.side_effect = revoked
    async with maker() as db:
        row = await db.get(type(source), source.id)
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), "https://api.solus.example"
        )
        assert state["status"] == "revoked"
        assert "_webhook_token_sha256" not in row.config


async def test_account_revoked_during_old_subscription_delete_prevents_new_post(webhook_scope):
    from solus_api.models import ConnectionStatus
    from solus_api.services.onshape_webhooks import save_state

    maker, source, account = webhook_scope
    connector = AsyncMock()

    async def revoke_account(*args, **kwargs):
        assert args[1] == "DELETE"
        async with maker() as other:
            connection = await other.get(type(account), account.id)
            connection.status = ConnectionStatus.REVOKED
            await other.commit()
        return httpx.Response(200, json={})

    connector.request.side_effect = revoke_account
    async with maker() as db:
        row = await db.get(type(source), source.id)
        save_state(row, {"status": "failed", "subscriptions": {"doc1": "oldhook"}})
        await db.commit()
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), "https://api.solus.example"
        )
        assert state["status"] == "revoked"
        assert "_webhook_token_sha256" not in row.config
        assert connector.request.call_count == 1
