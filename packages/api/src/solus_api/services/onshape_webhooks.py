"""Source-scoped durable Onshape webhook lifecycle and reconciliation generations."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import OnshapeConnector, tracked_document_ids
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, mint_webhook_token
from solus_api.models import AccountConnection, ConnectionStatus, Source, SourceStatus, utcnow

STATE_KEY = "_onshape_webhook"
EVENTS = [
    "onshape.model.lifecycle.changed",
    "onshape.model.lifecycle.changed.externalreferences",
    "onshape.model.lifecycle.createelement",
    "onshape.model.lifecycle.deleteelement",
    "onshape.model.lifecycle.metadata",
    "onshape.document.lifecycle.statechange",
]


def state_for(source: Source) -> dict[str, Any]:
    return dict(source.config.get(STATE_KEY, {}))


def save_state(source: Source, state: dict[str, Any]) -> None:
    source.config = {**source.config, STATE_KEY: state}


def hint_state(state: dict[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
    result = dict(state)
    events = list(result.get("events", []))
    digest = hashlib.sha256(event_id.encode()).hexdigest() if event_id else None
    if digest and digest in events:
        return result
    if digest:
        events.append(digest)
    result.update(
        generation=int(result.get("generation", 0)) + 1,
        events=events[-128:],
        dirty_at=utcnow().isoformat(),
    )
    return result


def acknowledge_state(state: dict[str, Any], generation: int) -> dict[str, Any]:
    return {**state, "acknowledged": max(int(state.get("acknowledged", 0)), generation)}


def dirty(state: dict[str, Any]) -> bool:
    return int(state.get("generation", 0)) > int(state.get("acknowledged", 0))


def active_write_holds(state: dict[str, Any]) -> dict[str, str]:
    """Only bounded, server-issued unexpired owners inhibit reconciliation."""
    holds = state.get("write_turn_holds", {})
    if not isinstance(holds, dict):
        return {}
    now = utcnow()
    result = {}
    for owner, expiry in holds.items():
        try:
            if str(uuid.UUID(owner)) == owner and datetime.fromisoformat(expiry) > now:
                result[owner] = expiry
        except (TypeError, ValueError, AttributeError):
            continue
    return result


def add_write_hold(
    state: dict[str, Any], owner: uuid.UUID, turn_deadline: datetime
) -> dict[str, Any]:
    now = utcnow()
    if not isinstance(owner, uuid.UUID) or turn_deadline.tzinfo is None:
        raise ConnectorError("config_invalid", "Invalid CAD turn hold")
    expiry = turn_deadline + timedelta(seconds=30)
    if expiry <= now or expiry > now + timedelta(seconds=330):
        raise ConnectorError("config_invalid", "CAD turn hold deadline exceeds its bound")
    holds = active_write_holds(state)
    if str(owner) not in holds:
        if len(holds) >= 32:
            raise ConnectorError("unavailable", "Too many active CAD write turns")
        holds[str(owner)] = expiry.isoformat()
    return {**state, "write_turn_holds": holds}


def release_write_hold(state: dict[str, Any], owner: uuid.UUID) -> dict[str, Any]:
    holds = active_write_holds(state)
    holds.pop(str(owner), None)
    return {**state, "write_turn_holds": holds}


def recovery_due(state: dict[str, Any]) -> bool:
    if active_write_holds(state):
        return False
    try:
        return dirty(state) and datetime.fromisoformat(state.get("recover_after", "")) <= utcnow()
    except (TypeError, ValueError):
        return dirty(state)


def claim_schedule(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """A short durable debounce lease; expiry recovers failed enqueue attempts."""
    if active_write_holds(state):
        return state, False
    try:
        if datetime.fromisoformat(state.get("scheduled_until", "")) > utcnow():
            return state, False
    except (TypeError, ValueError):
        pass
    return {**state, "scheduled_until": (utcnow() + timedelta(seconds=30)).isoformat()}, True


def healthy_subscription(state: dict[str, Any], documents: list[str]) -> bool:
    subscriptions = state.get("subscriptions", {})
    deliveries = state.get("deliveries", {})
    if state.get("status") != "registered" or not documents:
        return False
    try:
        return all(
            subscriptions.get(doc) and datetime.fromisoformat(deliveries[doc]) <= utcnow()
            for doc in documents
        )
    except (KeyError, TypeError, ValueError):
        return False


def public_callback(base: str) -> bool:
    try:
        url = urlsplit(base)
        host = url.hostname or ""
        if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
            return False
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


async def _authorized_registration(session: AsyncSession, source: Source) -> bool:
    if source.status != SourceStatus.CONNECTED or not source.secret_ref:
        return False
    if source.connection_id is None:
        return True
    account = await session.get(AccountConnection, source.connection_id, populate_existing=True)
    return bool(
        account is not None
        and account.status == ConnectionStatus.CONNECTED
        and account.provider == source.type
        and account.secret_ref == source.secret_ref
    )


def _registration_in_progress(state: dict[str, Any]) -> bool:
    if state.get("status") != "registering":
        return False
    try:
        return datetime.fromisoformat(state.get("registration_started", "")) > utcnow() - timedelta(
            minutes=10
        )
    except (TypeError, ValueError):
        return False


async def register_onshape_webhooks(
    session: AsyncSession,
    source: Source,
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    callback_base: str,
) -> dict[str, Any]:
    """Caller supplies owner-scoped pinned transport; no token is persisted or returned."""
    await session.refresh(source, with_for_update=True)
    state = state_for(source)
    if not await _authorized_registration(session, source):
        return state
    if not public_callback(callback_base):
        state.update(status="unavailable", reason="public_https_callback_required")
        save_state(source, state)
        await session.commit()
        return state
    documents = tracked_document_ids(source.config)
    if (
        set(state.get("subscriptions", {})) == set(documents)
        and state.get("status") == "registered"
    ):
        return state
    if _registration_in_progress(state):
        return state
    if state.get("subscriptions"):
        await revoke_onshape_webhooks(session, source, connector, client)
        await session.refresh(source, with_for_update=True)
        state = state_for(source)
        if not await _authorized_registration(session, source):
            return state
        documents = tracked_document_ids(source.config)
    # Invalidate the previous URL first; incomplete registration is never healthy.
    token, digest = mint_webhook_token()
    source.config = {**source.config, WEBHOOK_TOKEN_KEY: digest}
    state.update(
        status="registering",
        subscriptions={},
        deliveries={},
        registration_started=utcnow().isoformat(),
    )
    save_state(source, state)
    await session.commit()
    if not await _register_documents(
        session, source, connector, client, callback_base, documents, token, digest
    ):
        return state_for(source)
    await session.refresh(source, with_for_update=True)
    state = state_for(source)
    if source.config.get(WEBHOOK_TOKEN_KEY) != digest or not await _authorized_registration(
        session, source
    ):
        return state
    state.update(status="registered", reason=None)
    save_state(source, state)
    await session.commit()
    return state


async def _register_documents(
    session: AsyncSession,
    source: Source,
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    callback_base: str,
    documents: list[str],
    token: str,
    digest: str,
) -> bool:
    for document in documents:
        try:
            response = await connector.request(
                client,
                "POST",
                "/api/v6/webhooks",
                what="register webhook",
                json_body={
                    "documentId": document,
                    "events": EVENTS,
                    "isTransient": False,
                    "options": {"collapseEvents": True},
                    "url": (
                        f"{callback_base.rstrip('/')}/api/v1/webhooks/onshape/{source.id}/{token}"
                    ),
                },
            )
            identifier = response.json().get("id")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[a-zA-Z0-9_-]{1,128}", identifier
            ):
                raise ValueError("invalid webhook response")
            await session.refresh(source, with_for_update=True)
            state = state_for(source)
            if source.config.get(WEBHOOK_TOKEN_KEY) != digest or not await _authorized_registration(
                session, source
            ):
                await _discard_registration(session, source, connector, client, identifier)
                return False
            if document not in tracked_document_ids(source.config):
                await _discard_registration(session, source, connector, client, identifier)
                return False
            state["subscriptions"] = {**state.get("subscriptions", {}), document: identifier}
            save_state(source, state)
            await session.commit()
        except Exception:  # noqa: BLE001 — remote errors may contain callback credentials
            await session.rollback()
            await session.refresh(source, with_for_update=True)
            state = state_for(source)
            if source.config.get(WEBHOOK_TOKEN_KEY) != digest or not await _authorized_registration(
                session, source
            ):
                return False
            state.update(status="failed", reason="registration_failed")
            save_state(source, state)
            await session.commit()
            return False
    return True


async def _discard_registration(
    session: AsyncSession,
    source: Source,
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    identifier: str,
) -> None:
    try:
        await connector.request(
            client, "DELETE", f"/api/v6/webhooks/{identifier}", what="remove stale registration"
        )
    except Exception:  # noqa: BLE001 — local revocation remains authoritative
        save_state(source, {**state_for(source), "cleanup_failed": True})
        await session.commit()


async def revoke_onshape_webhooks(
    session: AsyncSession,
    source: Source,
    connector: OnshapeConnector | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    await session.refresh(source, with_for_update=True)
    state = state_for(source)
    subscriptions = list(state.get("subscriptions", {}).values())
    source.config = {key: value for key, value in source.config.items() if key != WEBHOOK_TOKEN_KEY}
    state.update(status="revoked", deliveries={})
    save_state(source, state)
    await session.commit()
    failed = False
    for identifier in subscriptions:
        if connector is None or client is None:
            failed = True
            continue
        try:
            await connector.request(
                client, "DELETE", f"/api/v6/webhooks/{identifier}", what="remove webhook"
            )
        except Exception:  # noqa: BLE001 — authority already revoked locally
            failed = True
    await session.refresh(source, with_for_update=True)
    save_state(source, {**state_for(source), "cleanup_failed": failed})
    await session.commit()
