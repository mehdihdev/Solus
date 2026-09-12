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

Authorization is therefore structural. It happens ONCE, here, at subscribe time,
via a query that resolves membership — and the hub then routes by project, so
there is no per-frame filtering step that could be forgotten.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from solus_api.deps import ProjectCtx, SessionDep

logger = logging.getLogger("solus.routers.live")

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["live"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

#: Sent when the stream idles, to keep proxies from reaping it and to let the
#: client notice a dead connection. A comment line, ignored by EventSource.
_KEEPALIVE_SECONDS = 25.0

_EVENT_TYPE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")  # fullmatch: `$` would admit a trailing newline


def _frame_event_type(payload: str) -> str:
    """The SSE `event:` name for a hub payload — its `type` when it is a well-formed one,
    `graph.changed` otherwise (the only type the stream carried before SOLUSDEV-250). The
    pattern keeps a payload from naming an event it cannot spell in one token."""
    try:
        frame = json.loads(payload)
    except Exception:  # noqa: BLE001 — a payload we cannot parse is still a hint
        return "graph.changed"
    kind = frame.get("type") if isinstance(frame, dict) else None
    return kind if isinstance(kind, str) and _EVENT_TYPE.fullmatch(kind) else "graph.changed"


@router.get("/events")
async def project_events(
    request: Request, ctx: ProjectCtx, session: SessionDep
) -> StreamingResponse:
    """Subscribe to this project's change stream.

    Yields `graph.changed` frames — an invalidation hint the client answers by
    refetching the one thing it is already showing — and, on the local API only,
    `hardware.devices_changed` (SOLUSDEV-250, `hardware/device_watch.py`).
    """
    hub = request.app.state.graph_hub
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
    # id below is a plain UUID copied out before the close.
    await session.close()
    queue = hub.subscribe(project_id)
    logger.info(
        "events subscribe project=%s user=%s subscribers=%d",
        project_id,
        user_id,
        hub.subscriber_count(project_id),
    )

    async def stream() -> AsyncIterator[str]:
        # `ready` lets a client (and a test) know the subscription is live
        # before anything is published, which removes an unfixable race between
        # "subscribed" and "publish happened".
        yield f"event: ready\ndata: {json.dumps({'project_id': str(project_id)})}\n\n"
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {_frame_event_type(payload)}\ndata: {payload}\n\n"
        finally:
            hub.unsubscribe(project_id, queue)
            logger.info("events unsubscribe project=%s user=%s", project_id, user_id)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
