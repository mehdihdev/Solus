"""ADR-038 §2: a subscription made with other events or another session id is migrated."""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from solus_api.services import onshape_webhooks
from solus_api.services.onshape_webhooks import (
    EVENTS,
    events_digest,
    register_onshape_webhooks,
    save_state,
    state_for,
)
from test_onshape_write_sync import scope as scope_fixture

CALLBACK = "https://api.solus.example"


@pytest.fixture
async def webhook_scope(engine: Any) -> Any:
    return await scope_fixture.__wrapped__(engine)  # type: ignore[attr-defined]


def _connector() -> AsyncMock:
    connector = AsyncMock()
    connector.request.return_value = httpx.Response(200, json={"id": "webhook1"})
    return connector


def _verbs(connector: AsyncMock) -> list[str]:
    return [call.args[1] for call in connector.request.call_args_list]


async def test_registration_records_the_events_digest_and_session_id(webhook_scope: Any) -> None:
    maker, source, _ = webhook_scope
    connector = _connector()
    async with maker() as db:
        row = await db.get(type(source), source.id)
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="solus-prod"
        )
    assert state["events_digest"] == events_digest(EVENTS)
    assert state["session_id"] == "solus-prod"


async def test_an_old_state_subscription_is_migrated_exactly_once(webhook_scope: Any) -> None:
    maker, source, _ = webhook_scope
    connector = _connector()
    async with maker() as db:
        row = await db.get(type(source), source.id)
        await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="solus-prod"
        )
        # Make it look like a subscription registered before the digest/session were stored.
        old = {k: v for k, v in state_for(row).items() if k not in ("events_digest", "session_id")}
        save_state(row, old)
        await db.commit()
        connector.request.reset_mock()

        migrated = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="solus-prod"
        )
        assert _verbs(connector) == ["DELETE", "POST"]  # idempotent: old one removed first
        assert migrated["status"] == "registered"
        assert migrated["events_digest"] == events_digest(EVENTS)
        assert migrated["session_id"] == "solus-prod"

        connector.request.reset_mock()
        await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="solus-prod"
        )
        assert connector.request.call_count == 0  # settled: no vendor traffic


async def test_a_changed_session_id_re_registers(webhook_scope: Any) -> None:
    maker, source, _ = webhook_scope
    connector = _connector()
    async with maker() as db:
        row = await db.get(type(source), source.id)
        await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="one"
        )
        connector.request.reset_mock()
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="two"
        )
        assert _verbs(connector) == ["DELETE", "POST"]
        assert connector.request.call_args.kwargs["json_body"]["externalSessionId"] == "two"
        assert state["session_id"] == "two"


async def test_a_changed_event_list_re_registers(
    webhook_scope: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    maker, source, _ = webhook_scope
    connector = _connector()
    async with maker() as db:
        row = await db.get(type(source), source.id)
        await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="s"
        )
        connector.request.reset_mock()
        monkeypatch.setattr(onshape_webhooks, "EVENTS", [*EVENTS, "onshape.model.lifecycle.x"])
        state = await register_onshape_webhooks(
            db, row, connector, AsyncMock(), CALLBACK, external_session_id="s"
        )
        assert _verbs(connector) == ["DELETE", "POST"]
        assert state["events_digest"] == events_digest(onshape_webhooks.EVENTS)


def test_the_events_digest_ignores_order_and_detects_changes() -> None:
    assert events_digest(["a", "b"]) == events_digest(["b", "a"])
    assert events_digest(["a"]) != events_digest(["a", "b"])


@pytest.mark.parametrize("missing", ["events_digest", "session_id"])
def test_a_state_missing_either_field_is_not_settled(missing: str) -> None:
    from solus_api.services.onshape_webhooks import registration_current

    state = {"events_digest": events_digest(EVENTS), "session_id": "s"}
    assert registration_current(state, "s")
    assert not registration_current({k: v for k, v in state.items() if k != missing}, "s")
