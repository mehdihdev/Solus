"""Live graph-change fan-out (SOLUSDEV-167).

One engineer's sync must reach every teammate's open session without anyone
polling. This is the fan-out half of that:

    change detected -> graph updated -> hub.publish() -> every open session

**Routing is structural, not filtered.** Subscribers are held in a dict keyed by
PROJECT, and Redis pub/sub uses one channel per project. So the channel a frame
travels on — never anything in the frame's body — decides who receives it. There
is no per-subscriber authorization step to get wrong, because authorization
happened once, at subscribe time, against the same project-scoping query every
other route uses.

**The frame is an invalidation HINT, not a delta.** It says "this project's graph
moved", and the client refetches the one thing it is already showing. That is
deliberate:

  * `docs/contracts/widget-contract.md` forbids N mounted lenses becoming N
    requests. The host already owns exactly one fetch behind one cache key, so a
    hint becomes one refetch however many widgets are open. A payload frame would
    need a merge path, and would tempt every widget to consume it directly.
  * A delta cannot express a deletion cheaply — the client would need the removed
    ids too. An absence after a refetch expresses it for free.
  * It carries nothing a project member cannot already read, so a frame leaking
    to the wrong subscriber would be a routing bug rather than a data breach.
    Belt and braces, but the cheap kind.

**One class, not a Protocol with two backends.** Local delivery is identical
whether Redis is present; only the hop between processes differs. Without Redis
the hub still works within one process and says so, rather than pretending to
fan out across them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger("solus.graph.live")

_CHANNEL_PREFIX = "solus:graph"

#: Per-subscriber queue depth. A client that stops reading (a laptop that slept)
#: must not grow a queue without bound, and must not slow anyone else down: past
#: this depth its frames are dropped. Dropping is safe precisely BECAUSE the
#: frame is a hint — the next one it does receive triggers the same refetch.
_QUEUE_DEPTH = 32


def channel(project_id: uuid.UUID) -> str:
    return f"{_CHANNEL_PREFIX}:{project_id}"


def graph_changed_frame(
    *,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    sync_id: uuid.UUID | None,
    counts: Any,
    at: str,
) -> dict[str, Any]:
    """~200 bytes. Counts are advisory — for a "3 parts changed" toast, never for
    reconstructing state."""
    return {
        "type": "graph.changed",
        "project_id": str(project_id),
        "source_id": str(source_id),
        "sync_id": str(sync_id) if sync_id else None,
        "counts": {
            "entities_created": counts.entities_created,
            "entities_updated": counts.entities_updated,
            "entities_deleted": counts.entities_deleted,
            "relations_created": counts.relations_created,
            "relations_deleted": counts.relations_deleted,
        },
        "at": at,
    }


class LiveHub:
    """Project-scoped fan-out. Redis-optional, per the repo's convention."""

    def __init__(self, redis: Any | None = None) -> None:
        self._redis = redis
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[str]]] = {}
        self._reader: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ subscribing

    def subscribe(self, project_id: uuid.UUID) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_DEPTH)
        self._subscribers.setdefault(project_id, set()).add(queue)
        return queue

    def unsubscribe(self, project_id: uuid.UUID, queue: asyncio.Queue[str]) -> None:
        queues = self._subscribers.get(project_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            del self._subscribers[project_id]

    def subscriber_count(self, project_id: uuid.UUID) -> int:
        return len(self._subscribers.get(project_id, ()))

    # ------------------------------------------------------------- publishing

    async def publish(self, project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        """Fan a frame out to this project's subscribers.

        With Redis, publish ONLY — delivery happens in the reader loop, including
        for this process. That removes every "have I already delivered locally?"
        case, which is the kind of double-delivery bug that shows up once in
        production and never in a test.
        """
        payload = json.dumps(frame, separators=(",", ":"))
        if self._redis is not None:
            try:
                await self._redis.publish(channel(project_id), payload)
                return
            except Exception:  # noqa: BLE001 — never fail a sync on fan-out
                logger.warning("redis publish failed; delivering locally instead")
        self._deliver(project_id, payload)

    def _deliver(self, project_id: uuid.UUID, payload: str) -> None:
        # SSE frames are newline-delimited, so a payload containing a blank line
        # would END the frame and let everything after it be read as further
        # events — arbitrary event injection into a subscriber's stream.
        # `graph_changed_frame` + json.dumps cannot produce one today, but the
        # relay psubscribes to a WILDCARD and parses nothing, so any future
        # publisher on that pattern would inherit the hole. Drop rather than
        # sanitise: a frame we cannot vouch for is a frame worth losing, and the
        # next one triggers the same refetch.
        if "\n" in payload:
            logger.warning("dropping a graph frame containing a newline")
            return
        # Iterate a SNAPSHOT: a subscriber that disconnects mid-fan-out mutates
        # the set, and a slow one must not stall its neighbours.
        for queue in list(self._subscribers.get(project_id, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.debug("dropping frame for a subscriber that is not reading")

    # ------------------------------------------------------- cross-process leg

    async def start(self) -> None:
        """Begin relaying Redis frames into local queues. No-op without Redis."""
        if self._redis is None or self._reader is not None:
            return
        self._reader = asyncio.create_task(self._relay())

    async def stop(self) -> None:
        if self._reader is None:
            return
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        self._reader = None

    async def _relay(self) -> None:
        redis = self._redis
        if redis is None:  # unreachable: `start` guards it. Narrows for mypy.
            return
        pubsub = redis.pubsub()
        try:
            await pubsub.psubscribe(f"{_CHANNEL_PREFIX}:*")
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                raw_channel = message.get("channel")
                if isinstance(raw_channel, bytes):
                    raw_channel = raw_channel.decode()
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                project_id = _project_of(str(raw_channel))
                if project_id is not None and isinstance(data, str):
                    self._deliver(project_id, data)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a dead relay must not kill the app
            logger.exception("graph live relay stopped")
        finally:
            with contextlib.suppress(Exception):
                await pubsub.close()


def _project_of(raw_channel: str) -> uuid.UUID | None:
    _, _, tail = raw_channel.rpartition(":")
    try:
        return uuid.UUID(tail)
    except ValueError:
        return None
