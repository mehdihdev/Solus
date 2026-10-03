"""The project event stream (SOLUSDEV-167).

`GET /api/v1/projects/{project_id}/events` — a server-sent event stream carrying
`graph.changed`, so a teammate's sync reaches every open session with nobody
polling.

**SSE rather than the WebSocket API.md originally sketched, and the reason is
auth.** The only existing WS authentication in this repo reads an `Authorization`
header, which works solely because the companion is a Python client. No browser
`WebSocket` can set headers, and the renderer is Chromium — so WS here would mean
inventing a second credential path (subprotocol- or query-carried) plus reconnect
logic in the client, to buy a bidirectional channel nothing needs. SSE runs under
the ordinary `ProjectCtx` dependency: the same project-scoping query as every
other route, no new auth surface, and browsers reconnect on their own.

Authorization is therefore structural. It happens at subscribe time, via a query that
resolves membership — and the hub then routes by channel, so there is no per-frame
filtering step that could be forgotten.

SOLUSDEV-312 (ADR-037): two streams now. The PROJECT stream also carries the project's
layout/sources/jobs hints; the ACCOUNT stream (`/users/me/events`) carries the user's own
channel plus a team channel per membership. A stream outlives its request, so access is
RE-VERIFIED while open — immediately on an `access.revoked` / `membership.changed` hint and
at least every `REVERIFY_SECONDS` — and the stream ends when access does. Re-verification
opens a short session of its own: a streaming response never holds a DB connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from solus_contracts.live_events import (
    ACCOUNT_EVENT_TYPES,
    KEEPALIVE_SECONDS,
    PROJECT_EVENT_TYPES,
    AccessRevoked,
    AccountStreamReady,
    ProjectStreamReady,
)
from solus_contracts.live_events import (
    REVERIFY_SECONDS as _CONTRACT_REVERIFY_SECONDS,
)
from starlette.background import BackgroundTask

from solus_api.core.errors import APIError
from solus_api.deps import CurrentUser, LiveVerifierDep, ProjectCtx, SessionDep
from solus_api.graph.live import Channel, LiveHub, QueueItem, ResyncMarker, Subscription
from solus_api.graph.live_access import (
    LiveAccessVerifier,
    StreamLimiter,
    StreamPermit,
    account_channels,
    live_team_ids,
)

logger = logging.getLogger("solus.routers.live")

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["live"])
account_router = APIRouter(prefix="/api/v1/users/me", tags=["live"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

#: Sent when the stream idles, to keep proxies from reaping it and to let the
#: client notice a dead connection. A comment line, ignored by EventSource.
_KEEPALIVE_SECONDS = float(KEEPALIVE_SECONDS)
#: Upper bound between access re-verifications. A module global so tests can patch it.
REVERIFY_SECONDS = float(_CONTRACT_REVERIFY_SECONDS)

_EVENT_TYPE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")  # fullmatch: `$` would admit a trailing newline

#: User-channel frame types that mean "your access may have changed: re-verify now".
_REVERIFY_TRIGGERS = frozenset({"membership.changed", "access.revoked"})

_Tick = Literal["keepalive", "reverify"]


def _frame_dict(payload: str) -> dict[str, Any] | None:
    try:
        frame = json.loads(payload)
    except Exception:  # noqa: BLE001 — a payload we cannot parse is still a hint
        return None
    return frame if isinstance(frame, dict) else None


def _frame_type(payload: str) -> str | None:
    """The frame's `type` when it is a well-formed one (single-token, no newlines)."""
    frame = _frame_dict(payload)
    kind = frame.get("type") if frame is not None else None
    return kind if isinstance(kind, str) and _EVENT_TYPE.fullmatch(kind) else None


def _frame_event_type(payload: str) -> str:
    """The SSE `event:` name for a hub payload — its `type` when it is a well-formed one,
    `graph.changed` otherwise (the only type the stream carried before SOLUSDEV-250). The
    pattern keeps a payload from naming an event it cannot spell in one token."""
    return _frame_type(payload) or "graph.changed"


def _project_event_type(payload: str) -> str | None:
    """The SSE event name for a project-channel frame, or None to drop it. A typed frame must
    be a project event; an untyped/malformed one stays a legacy `graph.changed`."""
    kind = _frame_type(payload)
    if kind is None:
        return "graph.changed"
    return kind if kind in PROJECT_EVENT_TYPES else None


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _revoked_frame(*, user_id: uuid.UUID | None, project_id: uuid.UUID | None = None) -> str:
    frame = AccessRevoked(
        user_id=user_id,
        team_id=None,
        project_id=project_id,
        at=datetime.now(UTC).isoformat(),
    )
    return _sse("access.revoked", frame.model_dump_json())


async def _wait(subscription: Subscription, reverify_at: float) -> QueueItem | _Tick:
    """The next frame, or the tick (keepalive / reverification) that came due first."""
    remaining = reverify_at - time.monotonic()
    if remaining <= 0:
        return "reverify"
    try:
        return await asyncio.wait_for(
            subscription.queue.get(), timeout=min(_KEEPALIVE_SECONDS, remaining)
        )
    except TimeoutError:
        return "reverify" if time.monotonic() >= reverify_at else "keepalive"


def _acquire_permit(request: Request, user_id: uuid.UUID) -> StreamPermit:
    limiter: StreamLimiter = request.app.state.live_stream_limiter
    permit = limiter.acquire(user_id)
    if permit is None:
        logger.warning("live stream refused: per-user cap user=%s", user_id)
        raise APIError(
            429,
            "rate_limited",
            "Too many open live streams for this account",
            headers={"Retry-After": "5"},
        )
    return permit


def _closer(
    hub: LiveHub, subscription: Subscription, permit: StreamPermit, label: str, **ids: object
) -> Callable[[str], None]:
    """Idempotent teardown shared by the generator's `finally` and the response's
    background hook (which covers a client that vanishes before the first byte)."""
    done = False

    def close(reason: str) -> None:
        nonlocal done
        if done:
            return
        done = True
        hub.unsubscribe_channels(subscription)
        permit.release()
        logger.info("events unsubscribe stream=%s %s reason=%s", label, ids, reason)

    return close


def _stream_response(stream: AsyncIterator[str], close: Callable[[str], None]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        background=BackgroundTask(close, "response_finished"),
    )


async def _project_frames(
    subscription: Subscription,
    verifier: LiveAccessVerifier,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: list[str],
) -> AsyncGenerator[str, None]:
    yield _sse("ready", ProjectStreamReady(project_id=project_id).model_dump_json())
    reverify_at = time.monotonic() + REVERIFY_SECONDS
    while True:
        item = await _wait(subscription, reverify_at)
        if item == "keepalive":
            yield ": keepalive\n\n"
            continue
        recheck = item == "reverify"
        resync = isinstance(item, ResyncMarker)
        if isinstance(item, tuple):
            target, payload = item
            if target not in subscription.channels:  # queued before a resubscribe removed it
                continue
            if target.kind == "project":
                kind = _project_event_type(payload)
                if kind is None:
                    continue
                yield _sse(kind, payload)
                frame = _frame_dict(payload) or {}
                recheck = kind == "access.revoked" and frame.get("project_id") == str(project_id)
            else:  # the user channel is a trigger only: its frames are never forwarded here
                recheck = _frame_type(payload) in _REVERIFY_TRIGGERS
        if not (recheck or resync):
            continue
        reverify_at = time.monotonic() + REVERIFY_SECONDS
        if not await verifier.project_access(project_id, user_id):
            reason.append("access_revoked")
            yield _revoked_frame(user_id=user_id, project_id=project_id)
            return
        if resync:  # hints may have been lost: the client revalidates everything
            yield _sse("ready", ProjectStreamReady(project_id=project_id).model_dump_json())


@router.get("/events")
async def project_events(
    request: Request, ctx: ProjectCtx, session: SessionDep, verifier: LiveVerifierDep
) -> StreamingResponse:
    """Subscribe to this project's change stream.

    Yields the project channel's frames — `graph.changed`, `layout.changed`,
    `sources.changed`, `project.updated`, `job.updated`, `access.revoked` and, on the local
    API only, `hardware.devices_changed` (SOLUSDEV-250). Ends with `access.revoked` when
    the caller loses access.
    """
    hub: LiveHub = request.app.state.graph_hub
    project_id = ctx.project.id
    user_id = ctx.user.id
    # Release the request-scoped DB session BEFORE streaming.
    #
    # FastAPI tears a yield-dependency down only after the response is fully
    # sent, and this response never finishes — so without this the session (and
    # its connection-pool slot) is held open, in a transaction, for the entire
    # life of the subscription. A handful of subscribers would exhaust the pool,
    # and the symptom would be unrelated queries hanging. Found by a test that
    # hung rather than failed; the surviving evidence was an `idle in
    # transaction` backend per stream.
    #
    # Safe: authorization already happened above, this generator touches no ORM
    # object, and close() is idempotent so the later teardown is a no-op. Every
    # id below is a plain UUID copied out before the close. Re-verification opens
    # its own short sessions through `verifier`.
    await session.close()
    permit = _acquire_permit(request, user_id)
    subscription = hub.subscribe_channels([Channel.project(project_id), Channel.user(user_id)])
    logger.info(
        "events subscribe stream=project project=%s user=%s subscribers=%d",
        project_id,
        user_id,
        hub.subscriber_count(project_id),
    )
    close = _closer(hub, subscription, permit, "project", project=project_id, user=user_id)

    async def stream() -> AsyncIterator[str]:
        reason = ["client_disconnected"]
        try:
            # `ready` lets a client (and a test) know the subscription is live before
            # anything is published, which removes an unfixable race between
            # "subscribed" and "publish happened".
            async for chunk in _project_frames(subscription, verifier, project_id, user_id, reason):
                yield chunk
        except Exception:
            reason.append("error")
            logger.exception("project stream failed project=%s user=%s", project_id, user_id)
            raise
        finally:
            close(reason[-1])

    return _stream_response(stream(), close)


def _account_hint(
    subscription: Subscription, target: Channel, payload: str
) -> tuple[str | None, bool]:
    """(SSE chunk to forward or None, whether to re-verify) for one account-stream frame."""
    if target not in subscription.channels:  # queued before a resubscribe removed it
        return None, False
    kind = _frame_type(payload)
    chunk = _sse(kind, payload) if kind in ACCOUNT_EVENT_TYPES else None  # else dropped
    return chunk, kind in _REVERIFY_TRIGGERS


async def _account_frames(
    hub: LiveHub,
    subscription: Subscription,
    verifier: LiveAccessVerifier,
    user_id: uuid.UUID,
    team_ids: list[uuid.UUID],
    reason: list[str],
) -> AsyncGenerator[str, None]:
    def ready() -> str:
        return _sse(
            "ready", AccountStreamReady(user_id=user_id, team_ids=team_ids).model_dump_json()
        )

    yield ready()
    reverify_at = time.monotonic() + REVERIFY_SECONDS
    while True:
        item = await _wait(subscription, reverify_at)
        if item == "keepalive":
            yield ": keepalive\n\n"
            continue
        recheck = item == "reverify"
        resync = isinstance(item, ResyncMarker)
        if isinstance(item, tuple):
            chunk, recheck = _account_hint(subscription, *item)
            if chunk is not None:
                yield chunk
        if not (recheck or resync):
            continue
        reverify_at = time.monotonic() + REVERIFY_SECONDS
        current = await verifier.account_teams(user_id)
        if current is None:
            reason.append("access_revoked")
            yield _revoked_frame(user_id=user_id)
            return
        changed = current != team_ids
        if changed:
            team_ids = current
            hub.resubscribe(subscription, account_channels(user_id, team_ids))
        if changed or resync:
            yield ready()  # the client revalidates everything it holds


@account_router.get("/events")
async def account_events(
    request: Request, user: CurrentUser, session: SessionDep, verifier: LiveVerifierDep
) -> StreamingResponse:
    """Subscribe to the caller's own channel and every team channel they belong to.

    First event `ready` names the teams; it is sent again whenever membership changes the
    set. Ends with `access.revoked` if the account or token stops being valid.
    """
    hub: LiveHub = request.app.state.graph_hub
    user_id = user.id
    team_ids = await live_team_ids(session, user_id)
    await session.close()  # see project_events: a stream never holds a DB session
    permit = _acquire_permit(request, user_id)
    subscription = hub.subscribe_channels(account_channels(user_id, team_ids))
    logger.info("events subscribe stream=account user=%s teams=%d", user_id, len(team_ids))
    close = _closer(hub, subscription, permit, "account", user=user_id)

    async def stream() -> AsyncIterator[str]:
        reason = ["client_disconnected"]
        try:
            async for chunk in _account_frames(
                hub, subscription, verifier, user_id, team_ids, reason
            ):
                yield chunk
        except Exception:
            reason.append("error")
            logger.exception("account stream failed user=%s", user_id)
            raise
        finally:
            close(reason[-1])

    return _stream_response(stream(), close)
