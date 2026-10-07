"""Source-scoped durable Onshape webhook lifecycle and reconciliation generations."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import (
    OnshapeConnector,
    onshape_session_id,
    tracked_document_ids,
)
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, mint_webhook_token
from solus_api.models import AccountConnection, ConnectionStatus, Source, SourceStatus, utcnow

STATE_KEY = "_onshape_webhook"
#: Mirrors `Settings.onshape_quiet_period_seconds` when a caller has no settings.
DEFAULT_QUIET_SECONDS = 90
#: ADR-038 §2: the three events the mirror needs. Edits and new versions are
#: change hints; `translation.complete` replaces status polling for our own exports.
TRANSLATION_COMPLETE_EVENT = "onshape.model.translation.complete"
EVENTS = [
    "onshape.model.lifecycle.changed",
    TRANSLATION_COMPLETE_EVENT,
    "onshape.model.lifecycle.createversion",
]
#: How often a healthy subscription is confirmed to still exist (one cheap call each).
SUBSCRIPTION_CHECK_INTERVAL = timedelta(days=1)
#: Recovery re-enqueue backoff for a dirty source whose syncs keep failing.
RECOVERY_BACKOFF_BASE_SECONDS = 60
RECOVERY_BACKOFF_MAX_SECONDS = 3600


def events_digest(events: list[str]) -> str:
    """Order-independent fingerprint of an event list, stored with the subscription."""
    return hashlib.sha256("\n".join(sorted(events)).encode()).hexdigest()


def registration_current(state: dict[str, Any], session_id: str) -> bool:
    """Whether the stored subscription was made with TODAY's events and session id.

    A state written before these were recorded has neither, so it is never current and is
    migrated once (DELETE + POST) the next time registration runs."""
    return (
        state.get("events_digest") == events_digest(EVENTS)
        and state.get("session_id") == session_id
    )


def state_for(source: Source) -> dict[str, Any]:
    return dict(source.config.get(STATE_KEY, {}))


def save_state(source: Source, state: dict[str, Any]) -> None:
    source.config = {**source.config, STATE_KEY: state}


def _stamp_hint(state: dict[str, Any], now: datetime, quiet_seconds: int | None) -> dict[str, Any]:
    """Record WHEN a hint arrived. `first_hint_at` is the start of the current burst: it
    only moves when the gap since the previous hint outlasted the quiet period, so the
    maximum total wait bounds continuous editing rather than any single hint."""
    result = dict(state)
    gap = quiet_seconds if quiet_seconds is not None else DEFAULT_QUIET_SECONDS
    previous = _parse(result.get("last_hint_at"))
    first = _parse(result.get("first_hint_at"))
    if first is None or previous is None or (now - previous).total_seconds() >= gap:
        first = now
    result.update(last_hint_at=now.isoformat(), first_hint_at=first.isoformat())
    return result


def note_hint(
    state: dict[str, Any], *, now: datetime | None = None, quiet_seconds: int | None = None
) -> dict[str, Any]:
    """A hint with no new dirty generation (the sweep's own detection): the quiet period
    applies, but the evidence the sweep just cached is left alone."""
    return _stamp_hint(state, now or utcnow(), quiet_seconds)


def hint_state(
    state: dict[str, Any],
    *,
    event_id: str | None = None,
    now: datetime | None = None,
    quiet_seconds: int | None = None,
) -> dict[str, Any]:
    result = dict(state)
    events = list(result.get("events", []))
    digest = hashlib.sha256(event_id.encode()).hexdigest() if event_id else None
    if digest and digest in events:
        return result
    if digest:
        events.append(digest)
    stamp = now or utcnow()
    result = _stamp_hint(result, stamp, quiet_seconds)
    result.update(
        generation=int(result.get("generation", 0)) + 1,
        events=events[-128:],
        dirty_at=stamp.isoformat(),
    )
    return result


def acknowledge_state(state: dict[str, Any], generation: int) -> dict[str, Any]:
    """Acknowledge a captured generation, reset the recovery backoff (the source just
    succeeded) and move the burst start to the first hint nobody has acknowledged."""
    result = {k: v for k, v in state.items() if k not in ("recovery_attempts", "recover_after")}
    result["acknowledged"] = max(int(state.get("acknowledged", 0)), generation)
    if dirty(result) and result.get("last_hint_at"):
        result["first_hint_at"] = result["last_hint_at"]
    else:
        result.pop("first_hint_at", None)
    return result


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def quiet_remaining(
    state: dict[str, Any], *, now: datetime, quiet_seconds: int, max_wait_seconds: int
) -> float:
    """Seconds until the quiet period is over: `quiet_seconds` after the LAST hint, but
    never later than `max_wait_seconds` after the burst's FIRST hint."""
    last = _parse(state.get("last_hint_at"))
    if last is None:
        return 0.0
    first = _parse(state.get("first_hint_at")) or last
    due = min(last + timedelta(seconds=quiet_seconds), first + timedelta(seconds=max_wait_seconds))
    return max(0.0, (due - now).total_seconds())


def note_recovery_attempt(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """A recovery enqueue that actually queued a job: back off exponentially (1 min,
    doubling, capped at 1 h) until a sync acknowledges the generation."""
    attempts = int(state.get("recovery_attempts", 0))
    delay = min(RECOVERY_BACKOFF_BASE_SECONDS * 2**attempts, RECOVERY_BACKOFF_MAX_SECONDS)
    return {
        **state,
        "recovery_attempts": attempts + 1,
        "recover_after": ((now or utcnow()) + timedelta(seconds=delay)).isoformat(),
    }


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


def subscription_check_due(state: dict[str, Any], now: datetime) -> bool | None:
    """True when a healthy subscription has gone a day without confirmation; None when no
    baseline was ever recorded (an old state: the caller stamps one without a call)."""
    checked = _parse(state.get("health_checked_at"))
    if checked is None:
        return None
    return now - checked >= SUBSCRIPTION_CHECK_INTERVAL


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
    *,
    external_session_id: str | None = None,
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
    session_id = external_session_id or onshape_session_id()
    if (
        set(state.get("subscriptions", {})) == set(documents)
        and state.get("status") == "registered"
        and registration_current(state, session_id)
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
        session, source, connector, client, callback_base, documents, token, digest, session_id
    ):
        return state_for(source)
    await session.refresh(source, with_for_update=True)
    state = state_for(source)
    if source.config.get(WEBHOOK_TOKEN_KEY) != digest or not await _authorized_registration(
        session, source
    ):
        return state
    state.update(
        status="registered",
        reason=None,
        health_checked_at=utcnow().isoformat(),
        events_digest=events_digest(EVENTS),
        session_id=session_id,
    )
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
    session_id: str,
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
                    # ADR-038 §2: Solus's own writes carry this as X-Session-ID, so
                    # Onshape can tell their echoes apart from a person's edits.
                    "externalSessionId": session_id,
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


async def verify_subscriptions(
    session: AsyncSession,
    source: Source,
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
) -> bool:
    """The bounded daily health check: one cheap GET per subscription.

    A subscription Onshape no longer has (404) is dropped and the state stops being
    healthy, which re-enables the hourly sweep probe and makes the next sync register
    afresh. Any other failure (network, quota, auth) proves nothing about the
    subscription, so it is kept; the attempt is still stamped so a down provider is not
    asked again every hour. Returns whether every subscription was confirmed.
    """
    await session.refresh(source)
    subscriptions = dict(state_for(source).get("subscriptions", {}))
    missing: list[str] = []
    confirmed = True
    for document, identifier in subscriptions.items():
        try:
            await connector.request(
                client, "GET", f"/api/v6/webhooks/{identifier}", what="check webhook"
            )
        except ConnectorError as exc:
            confirmed = False
            if exc.code == "not_found":
                missing.append(document)
        except Exception:  # noqa: BLE001 — a failed check never changes health
            confirmed = False
    await session.refresh(source, with_for_update=True)
    state = state_for(source)
    state["health_checked_at"] = utcnow().isoformat()
    if missing:
        state.update(
            status="failed",
            reason="subscription_missing",
            subscriptions={
                doc: ident
                for doc, ident in state.get("subscriptions", {}).items()
                if doc not in missing
            },
            deliveries={},
        )
    save_state(source, state)
    await session.commit()
    return confirmed
