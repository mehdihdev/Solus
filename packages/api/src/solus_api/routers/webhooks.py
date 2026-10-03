"""Inbound provider change webhooks (SOLUSDEV-167).

`docs/api/API.md` §2.5 has specified this route since Week 0 —
"Inbound change webhooks (signature-verified, unauthenticated otherwise);
enqueues incremental sync. **Payload treated as untrusted input per §7**" — and
`SyncTrigger.WEBHOOK` has been a reserved, never-produced enum value ever since.
This builds it, and takes that last clause literally.

**The payload is a doorbell, not graph data.** Bounded Onshape identity fields
are retained only for deduplication and subscription health. The route resolves the source
from the URL, returns 204, and schedules the ordinary probe — which asks the
provider itself, with the source's own credentials, what actually changed. So a
forged notification costs one debounced probe of a source whose token the sender
already holds, and can write nothing.

That is also what makes an unsigned vendor workable. **Onshape publishes no
inbound signature scheme**, so the Stripe HMAC pattern does not transfer; the
per-source URL token carries the authorization instead, and a vendor signature
(GitHub's) is kept as an extra check where one genuinely exists.

Free, and that is the point: Onshape does not count webhook notifications against
the annual allowance. Every change that arrives by push is a probe not spent.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import (
    TRANSLATION_RECORD_TTL_SECONDS,
    translation_done_key,
    translation_pending_key,
)
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, token_matches
from solus_api.core.errors import APIError
from solus_api.deps import SessionDep, SettingsDep
from solus_api.models import Source, SourceStatus
from solus_api.services.connections import account_ref_for, invalidate_listing
from solus_api.services.onshape_webhooks import (
    DEFAULT_QUIET_SECONDS,
    TRANSLATION_COMPLETE_EVENT,
    claim_schedule,
    hint_state,
    save_state,
    state_for,
)

logger = logging.getLogger("solus.webhooks")

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

#: The body is never parsed, so this only has to be big enough not to reject a
#: legitimate delivery — and small enough that an attacker cannot make us buffer
#: anything interesting.
MAX_WEBHOOK_BYTES = 64 * 1024

#: Deliveries that may SCHEDULE WORK, per source, per DAY.
#:
#: A per-minute budget was wrong by two orders of magnitude, and the arithmetic
#: is worth writing down. One delivery does not cost "one probe": it schedules a
#: sync whose freshness probe loops PER TRACKED DOCUMENT, up to `_MAX_DOCUMENTS`
#: (50). So one delivery can cost up to 50 quota-counted calls, and six a minute
#: is up to 300/min against an allowance of 2,500 A YEAR — under ten minutes to
#: zero, available to anyone holding the URL.
#:
#: Onshape's allowance works out at ~6.8 calls/day, so any window finer than a
#: day is meaningless for this provider. A real change that arrives while the
#: budget is spent is not lost: the sweep picks it up.
WEBHOOK_DELIVERIES_PER_DAY = 24

#: Onshape deliveries of ANY kind a source may cause state work for, per minute. Separate
#: from (and far looser than) the scheduling budget above, which still counts only the
#: deliveries that schedule a sync. Generous: a busy document plus our own exports is a
#: handful a minute; this only stops a flood against one valid URL.
WEBHOOK_INGEST_PER_MINUTE = 120


def _require_bounded_length(request: Request) -> None:
    """A declared, valid, in-cap length — or refuse before reading anything."""
    declared = request.headers.get("content-length")
    if declared is None:
        raise APIError(411, "length_required", "Content-Length is required")
    try:
        declared_bytes = int(declared)
    except ValueError:
        raise APIError(411, "length_required", "Content-Length is invalid") from None
    if declared_bytes < 0 or declared_bytes > MAX_WEBHOOK_BYTES:
        raise APIError(413, "payload_too_large", "Webhook payload too large")


async def _drain_bounded(request: Request) -> bytes:
    """Consume the body in chunks, abandoning it the moment it exceeds the cap.

    Nothing is kept: this endpoint reads no field from the payload, so the body
    exists only to be counted and discarded.
    """
    seen = 0
    chunks = []
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > MAX_WEBHOOK_BYTES:
            raise APIError(413, "payload_too_large", "Webhook payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _defer_onshape_recovery(session: AsyncSession, source: Source) -> None:
    from datetime import timedelta

    from solus_api.models import utcnow

    if source.type.value == "onshape":
        await session.refresh(source, with_for_update=True)
        save_state(
            source,
            {**state_for(source), "recover_after": (utcnow() + timedelta(days=1)).isoformat()},
        )
        await session.commit()


@dataclasses.dataclass(frozen=True)
class _Hint:
    """What an accepted Onshape delivery asks of us."""

    schedule: bool


_NO_HINT = _Hint(schedule=False)
_TRANSLATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


async def _record_translation_complete(
    cache: IntegrationCache | None, source: Source, payload: dict[str, Any]
) -> None:
    """Note that a translation THIS source's account started has finished.

    The scope is the Source row's account, never anything in the payload, and only a
    translation the account itself announced can be recorded. Nothing else from the payload
    is kept: the export wait confirms with one authoritative status read."""
    translation = payload.get("translationId")
    if (
        cache is None
        or not isinstance(translation, str)
        or not _TRANSLATION_ID_RE.fullmatch(translation)
    ):
        return
    account = account_ref_for(source)
    if await cache.get(translation_pending_key(account, translation)) is None:
        return
    await cache.put(
        translation_done_key(account, translation),
        {"state": "complete"},
        TRANSLATION_RECORD_TTL_SECONDS,
    )


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise APIError(400, "invalid_payload", "Expected a JSON webhook object") from None
    if not isinstance(payload, dict):
        raise APIError(400, "invalid_payload", "Expected a JSON webhook object")
    return payload


def _event_identity(payload: dict[str, Any]) -> str | None:
    event_id = payload.get("messageId")
    if event_id is not None and (not isinstance(event_id, str) or len(event_id) > 256):
        raise APIError(400, "invalid_payload", "Invalid event identity")
    return event_id


async def _accept_onshape_hint(
    session: AsyncSession,
    source: Source,
    body: bytes,
    *,
    cache: IntegrationCache | None = None,
    quiet_seconds: int = DEFAULT_QUIET_SECONDS,
) -> _Hint:
    from solus_api.connectors.onshape import tracked_document_ids
    from solus_api.models import utcnow

    if source.status not in (SourceStatus.CONNECTED, SourceStatus.SYNCING):
        return _NO_HINT
    payload = _json_object(body)
    document = payload.get("documentId")
    if document is not None and document not in tracked_document_ids(source.config):
        return _NO_HINT
    state = state_for(source)
    event_id = _event_identity(payload)
    event = payload.get("event")
    event = event if isinstance(event, str) and len(event) <= 128 else None
    if document and state.get("subscriptions", {}).get(document) == payload.get("webhookId"):
        state["deliveries"] = {**state.get("deliveries", {}), document: utcnow().isoformat()}
    if event == "webhook.unregister":
        state["status"] = "failed"
    if event == TRANSLATION_COMPLETE_EVENT:
        # Our own export finishing is not a change to the document: record it, schedule nothing.
        await _record_translation_complete(cache, source, payload)
        save_state(source, state)
        await session.commit()
        return _NO_HINT
    previous_generation = state.get("generation", 0)
    if event not in ("webhook.register", "webhook.ping"):
        state = hint_state(state, event_id=event_id, quiet_seconds=quiet_seconds)
    if state.get("generation", 0) == previous_generation:
        save_state(source, state)
        await session.commit()
        return _NO_HINT
    state, should_enqueue = claim_schedule(state)
    save_state(source, state)
    await session.commit()

    return _Hint(schedule=should_enqueue)


@router.post("/{provider}/{source_id}/{token}", status_code=204)
async def provider_webhook(
    provider: str,
    source_id: uuid.UUID,
    token: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> Response:
    # Bound the untrusted body before ANY of it is buffered. This is
    # pre-authentication on the one internet-facing endpoint in the system, so
    # the naive version is a remote OOM: an earlier draft here checked
    # `content-length` only when it was present and numeric, then called
    # `request.body()` — which buffers the whole stream with no cap. Chunked
    # transfer-encoding (no header at all) and a malformed header BOTH skipped
    # the guard entirely.
    #
    # Same shape as the artifact upload path: require a valid, in-cap
    # Content-Length up front, then re-enforce while streaming so a client that
    # lies about a small one still cannot overshoot.
    _require_bounded_length(request)
    body = await _drain_bounded(request)
    # NOTE: the body is deliberately never PARSED, and after this point it is not
    # even retained. See the module docstring.

    source = await session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    # One response for "no such source", "wrong provider" and "bad token": a
    # distinguishable 404 would turn this into an oracle for which source ids
    # exist. Fails closed — a source that never registered has no digest and
    # `token_matches` rejects everything.
    if (
        source is None
        or source.type.value != provider
        or not token_matches(token, source.config.get(WEBHOOK_TOKEN_KEY))
    ):
        # `provider` is an unauthenticated, URL-decoded path segment: unbounded
        # and newline-capable, so logging it raw lets an anonymous caller forge
        # log records. Same %.Nr treatment the bridge gives unknown frame types.
        logger.info("webhook rejected provider=%.32r source=%s", provider, source_id)
        raise APIError(404, "not_found", "Unknown webhook endpoint")

    if provider == "onshape":
        # Bound the work an AUTHENTICATED source can cause before any of it (row lock,
        # commit, Redis write) is done, for deliveries that will not schedule a sync too.
        ingest = getattr(request.app.state, "webhook_ingest_limiter", None)
        if ingest is not None and ingest.bump(str(source_id)) > WEBHOOK_INGEST_PER_MINUTE:
            logger.warning("webhook ingest budget spent source=%s", source_id)
            return Response(status_code=204)
        hint = await _accept_onshape_hint(
            session,
            source,
            body,
            cache=getattr(request.app.state, "integration_cache", None),
            quiet_seconds=settings.onshape_quiet_period_seconds,
        )
        if not hint.schedule:
            return Response(status_code=204)

    # Rate-limit every AUTHORIZED delivery, before deciding what to do with it.
    # Ordering matters: a storm against a source that is mid-sync or errored must
    # be bounded too, and those paths exit early — so a limiter placed after them
    # would never see the traffic it exists to bound.
    # Fails CLOSED. A missing limiter means the budget cannot be enforced, and
    # on an unauthenticated endpoint that schedules third-party spend, silently
    # dropping the control is the wrong direction to fail.
    limiter = getattr(request.app.state, "webhook_limiter", None)
    if limiter is None:
        logger.error("webhook limiter is not configured; refusing to schedule work")
        await _defer_onshape_recovery(session, source)
        return Response(status_code=204)
    if limiter.bump(str(source_id)) > WEBHOOK_DELIVERIES_PER_DAY:
        logger.warning("webhook delivery budget spent source=%s", source_id)
        await _defer_onshape_recovery(session, source)
        return Response(status_code=204)

    if source.status is not SourceStatus.CONNECTED:
        # Not probed while disconnected, errored, or already syncing. Still a
        # 204: the provider has nothing useful to do with a failure here, and
        # retries would only cost us more.
        logger.info("webhook ignored for source=%s status=%s", source_id, source.status.value)
        return Response(status_code=204)

    logger.info("webhook accepted provider=%s source=%s", provider, source_id)
    # SOLUSDEV-241: other providers' deliveries can move the ACCOUNT's cached listing
    # without a user spending quota. Onshape's cannot: only model events are subscribed
    # (`EVENTS`), and a model edit never changes the document listing, so an Onshape
    # delivery no longer costs the next picker open a full re-walk.
    cache = getattr(request.app.state, "integration_cache", None)
    if cache is not None and provider != "onshape":
        await invalidate_listing(cache, provider=provider, account_ref=account_ref_for(source))
    background.add_task(_probe_source, request.app, source_id)
    return Response(status_code=204)


async def _probe_source(app: FastAPI, source_id: uuid.UUID) -> None:
    """Schedule the ordinary sync for this source.

    Deliberately the SAME path a manual trigger and the sweep take, so a webhook
    inherits the freshness gate (an already-current document costs one probe, not
    an export) and single-flight (a retry storm collapses) without either being
    reimplemented here.

    Onshape syncs are DEFERRED by the quiet period (ADR-038 §2): one job per source under a
    stable id (arq drops later enqueues while it is pending), or in-process when there is no
    worker, so a burst of edits becomes one sync after the last of them.
    """
    from solus_api.connectors import worker
    from solus_api.models import SyncTrigger

    state = app.state
    settings = state.settings
    try:
        pool = getattr(state, "arq_pool", None)
        if pool is None and settings.redis_url:
            from solus_api.routers.sources import _arq_pool

            pool = await _arq_pool(app)
        source_type = await _source_type(state.sessionmaker, source_id)
        if pool is not None and source_type == "onshape":
            await pool.enqueue_job(
                "sync_source",
                str(source_id),
                webhook=True,
                quiet=True,
                _job_id=worker.quiet_job_id(source_id),
                _defer_by=settings.onshape_quiet_period_seconds,
            )
            return
        if pool is not None:
            await pool.enqueue_job(
                "sync_source", str(source_id), _job_id=f"onshape-hint:{source_id}"
            )
            return

        async def run() -> None:
            try:
                await worker.execute_source_sync(
                    sessionmaker=state.sessionmaker,
                    registry=state.connector_registry,
                    secret_store=state.secret_store,
                    source_id=source_id,
                    trigger=SyncTrigger.WEBHOOK,
                    store=getattr(state, "integration_store", None),
                    hub=getattr(state, "graph_hub", None),
                    artifact_store=getattr(state, "artifact_store", None),
                    webhook_callback_base=settings.public_api_base_url,
                    label="webhook",
                )
            except Exception:  # noqa: BLE001 — a webhook must never surface an error
                logger.exception("webhook-triggered sync failed source=%s", source_id)

        if source_type == "onshape":
            worker.schedule_inline_quiet(
                source_id,
                sessionmaker=state.sessionmaker,
                quiet_seconds=settings.onshape_quiet_period_seconds,
                run=run,
            )
            return
        await run()
    except Exception:  # noqa: BLE001 — a webhook must never surface an error
        logger.exception("webhook-triggered sync failed source=%s", source_id)


async def _source_type(sessionmaker: Any, source_id: uuid.UUID) -> str | None:
    async with sessionmaker() as session:
        source = await session.get(Source, source_id)
        return source.type.value if source is not None else None
