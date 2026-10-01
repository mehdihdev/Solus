"""Live change fan-out (SOLUSDEV-167; channel kinds added by SOLUSDEV-312 / ADR-037).

SOLUSDEV-312: subscribers are now keyed by CHANNEL — `project`, `team` or `user` — and one
subscription may span several (`subscribe_channels`). Everything below about project routing
holds for every kind: the channel decides delivery, never a frame body.

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
from collections.abc import Iterable
from typing import Any, NamedTuple

from solus_contracts.live_events import CHANNEL_KINDS, ChannelKind, channel_name

logger = logging.getLogger("solus.graph.live")

#: Pre-ADR-037 project channel prefix. The relay still reads it so a mixed-version
#: worker/API rollout (old worker publishing, new API relaying) loses nothing.
_LEGACY_PREFIX = "solus:graph"
_LIVE_PATTERN = "solus:live:*"
_LEGACY_PATTERN = f"{_LEGACY_PREFIX}:*"

#: Key under which `build_sessionmaker` stores the hub in every session's `info`, so the
#: publish-after-commit listeners (graph/live_publisher.py) can find it.
HUB_INFO_KEY = "solus.live_hub"

#: Per-subscriber queue depth. A client that stops reading (a laptop that slept)
#: must not grow a queue without bound, and must not slow anyone else down: past
#: this depth its frames are dropped. Dropping is safe precisely BECAUSE the
#: frame is a hint — the next one it does receive triggers the same refetch.
_QUEUE_DEPTH = 32


class Channel(NamedTuple):
    """One routing scope (ADR-037 §1). Structural: delivery is decided by this, never by a
    frame body."""

    kind: ChannelKind
    scope_id: uuid.UUID

    @classmethod
    def project(cls, scope_id: uuid.UUID) -> Channel:
        return cls("project", scope_id)

    @classmethod
    def team(cls, scope_id: uuid.UUID) -> Channel:
        return cls("team", scope_id)

    @classmethod
    def user(cls, scope_id: uuid.UUID) -> Channel:
        return cls("user", scope_id)

    @property
    def name(self) -> str:
        return channel_name(self.kind, self.scope_id)


def parse_channel(raw: str) -> Channel | None:
    """Strictly parse a Redis channel name (contract or legacy); None when malformed.

    Strict on purpose: the relay psubscribes to a wildcard, so anything else that publishes
    under the prefix reaches this parser. The id must round-trip as a canonical UUID.
    """
    parts = raw.split(":")
    if parts[:2] == ["solus", "live"] and len(parts) == 4 and parts[2] in CHANNEL_KINDS:
        kind: ChannelKind | None = next(k for k in CHANNEL_KINDS if k == parts[2])
        scope = parts[3]
    elif parts[:2] == ["solus", "graph"] and len(parts) == 3:
        kind, scope = "project", parts[2]
    else:
        return None
    try:
        scope_id = uuid.UUID(scope)
    except ValueError:
        return None
    if kind is None or str(scope_id) != scope:
        return None
    return Channel(kind, scope_id)


def channel(project_id: uuid.UUID) -> str:
    """The Redis channel name of a project (kept for existing callers)."""
    return Channel.project(project_id).name


class Subscription:
    """One consumer's live set of channels. `queue` yields `(Channel, payload)`."""

    __slots__ = ("channels", "closed", "queue")

    def __init__(self, channels: frozenset[Channel]) -> None:
        self.channels = channels
        self.closed = False
        self.queue: asyncio.Queue[tuple[Channel, str]] = asyncio.Queue(maxsize=_QUEUE_DEPTH)


def graph_changed_frame(
    *,
    project_id: uuid.UUID,
    source_id: uuid.UUID | None,
    sync_id: uuid.UUID | None,
    counts: Any,
    at: str,
) -> dict[str, Any]:
    """~200 bytes. Counts are advisory — for a "3 parts changed" toast, never for
    reconstructing state."""
    return {
        "type": "graph.changed",
        "project_id": str(project_id),
        "source_id": str(source_id) if source_id else None,
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


def hardware_devices_frame(
    *, project_id: uuid.UUID, devices: list[dict[str, Any]], at: str
) -> dict[str, Any]:
    """SOLUSDEV-250 hot-detect. A FULL current list — a deliberate departure from the
    hint-only rule above: the data is small, ephemeral and machine-local (there is no server
    state to refetch), and absence from the list IS the removal. Delivered only through
    `publish_local`; it never rides Redis."""
    return {
        "type": "hardware.devices_changed",
        "project_id": str(project_id),
        "devices": devices,
        "at": at,
    }


class LiveHub:
    """Channel-scoped fan-out. Redis-optional, per the repo's convention."""

    def __init__(self, redis: Any | None = None) -> None:
        self._redis = redis
        self._subscriptions: dict[Channel, set[Subscription]] = {}
        # Pre-ADR-037 per-project queues, kept for `subscribe`/`unsubscribe` callers.
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[str]]] = {}
        self._reader: asyncio.Task[None] | None = None

    @property
    def fanout_mode(self) -> str:
        """`redis` fans out across processes; `local_only` reaches this process alone."""
        return "redis" if self._redis is not None else "local_only"

    # ------------------------------------------------------------ subscribing

    def subscribe_channels(self, channels: Iterable[Channel]) -> Subscription:
        subscription = Subscription(frozenset(channels))
        for target in subscription.channels:
            self._subscriptions.setdefault(target, set()).add(subscription)
        return subscription

    def resubscribe(self, subscription: Subscription, channels: Iterable[Channel]) -> None:
        """Replace the channel set in one synchronous step — no await point, so no frame is
        routed against a half-updated set. A no-op for an already-unsubscribed subscription."""
        if not self._is_active(subscription):
            return
        wanted = frozenset(channels)
        for target in subscription.channels - wanted:
            self._discard(target, subscription)
        for target in wanted - subscription.channels:
            self._subscriptions.setdefault(target, set()).add(subscription)
        subscription.channels = wanted

    def unsubscribe_channels(self, subscription: Subscription) -> None:
        for target in subscription.channels:
            self._discard(target, subscription)
        subscription.channels = frozenset()
        subscription.closed = True

    def _is_active(self, subscription: Subscription) -> bool:
        return not subscription.closed

    def _discard(self, target: Channel, subscription: Subscription) -> None:
        members = self._subscriptions.get(target)
        if members is None:
            return
        members.discard(subscription)
        if not members:
            del self._subscriptions[target]

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
        multi = len(self._subscriptions.get(Channel.project(project_id), ()))
        return multi + len(self._subscribers.get(project_id, ()))

    def subscribed_project_ids(self) -> list[uuid.UUID]:
        ids = dict.fromkeys(self._subscribers)
        ids.update(dict.fromkeys(c.scope_id for c in self._subscriptions if c.kind == "project"))
        return list(ids)

    # ------------------------------------------------------------- publishing

    async def publish_to(self, target: Channel, frame: dict[str, Any]) -> None:
        """Fan a frame out to one channel's subscribers.

        With Redis, publish ONLY — delivery happens in the reader loop, including
        for this process. That removes every "have I already delivered locally?"
        case, which is the kind of double-delivery bug that shows up once in
        production and never in a test.
        """
        payload = json.dumps(frame, separators=(",", ":"))
        if self._redis is not None:
            try:
                await self._redis.publish(target.name, payload)
                return
            except Exception:  # noqa: BLE001 — never fail a request or sync on fan-out
                logger.warning("redis publish failed; delivering locally instead")
        self._deliver(target, payload)

    async def publish(self, project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        """Fan a frame out to this project's subscribers (the pre-ADR-037 entry point)."""
        await self.publish_to(Channel.project(project_id), frame)

    def publish_local(self, project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        """Deliver to THIS process's subscribers only — never Redis. For frames that describe
        this machine (its enumerated devices): one machine's list must never reach another
        machine's session."""
        self._deliver(Channel.project(project_id), json.dumps(frame, separators=(",", ":")))

    def _deliver(self, target: Channel | uuid.UUID, payload: str) -> None:
        if isinstance(target, uuid.UUID):  # legacy callers name a project
            target = Channel.project(target)
        # SSE frames are newline-delimited, so a payload containing a blank line
        # would END the frame and let everything after it be read as further
        # events — arbitrary event injection into a subscriber's stream.
        # `json.dumps` cannot produce one today, but the relay psubscribes to a
        # WILDCARD and parses nothing in the body, so any future publisher on that
        # pattern would inherit the hole. Drop rather than sanitise: a frame we
        # cannot vouch for is a frame worth losing, and the next one triggers the
        # same refetch.
        if "\n" in payload:
            logger.warning("dropping a live frame containing a newline")
            return
        # Iterate SNAPSHOTS: a subscriber that disconnects mid-fan-out mutates
        # the sets, and a slow one must not stall its neighbours.
        for subscription in list(self._subscriptions.get(target, ())):
            try:
                subscription.queue.put_nowait((target, payload))
            except asyncio.QueueFull:
                logger.debug("dropping frame for a subscriber that is not reading")
        if target.kind != "project":
            return
        for queue in list(self._subscribers.get(target.scope_id, ())):
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
            await pubsub.psubscribe(_LIVE_PATTERN, _LEGACY_PATTERN)
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                raw_channel = message.get("channel")
                if isinstance(raw_channel, bytes):
                    raw_channel = raw_channel.decode()
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                target = parse_channel(str(raw_channel))
                if target is not None and isinstance(data, str):
                    self._deliver(target, data)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a dead relay must not kill the app
            logger.exception("live relay stopped")
        finally:
            with contextlib.suppress(Exception):
                await pubsub.close()
