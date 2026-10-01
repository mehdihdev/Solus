"""ADR-037 §1/§4 — LiveHub channel kinds, multi-channel subscriptions and the Redis relay."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from solus_api.graph.live import Channel, LiveHub, parse_channel
from solus_contracts.live_events import channel_name

FRAME: dict[str, Any] = {"type": "team.updated", "at": "2026-09-30T00:00:00+00:00"}


class _Redis:
    """Records publishes; can be told to fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, name: str, payload: str) -> None:
        if self.fail:
            raise RuntimeError("down")
        self.published.append((name, payload))


class _PubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self.patterns: tuple[str, ...] = ()
        self.closed = False

    async def psubscribe(self, *patterns: str) -> None:
        self.patterns = patterns

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        for message in self.messages:
            yield message
        await asyncio.sleep(3600)  # stay open like a real subscription
        yield {}  # pragma: no cover

    async def close(self) -> None:
        self.closed = True


class _RelayRedis:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.pubsub_obj = _PubSub(messages)

    def pubsub(self) -> _PubSub:
        return self.pubsub_obj


def _pmessage(name: str | bytes, data: str | bytes) -> dict[str, Any]:
    return {"type": "pmessage", "channel": name, "data": data}


# ------------------------------------------------------------------ Channel


def test_channel_helpers_build_each_kind() -> None:
    scope = uuid.uuid4()
    assert Channel.project(scope) == Channel("project", scope)
    assert Channel.team(scope).kind == "team"
    assert Channel.user(scope).kind == "user"
    assert Channel.team(scope) != Channel.user(scope)
    assert Channel.team(scope).name == channel_name("team", scope)


def test_parse_channel_accepts_contract_and_legacy_names() -> None:
    scope = uuid.uuid4()
    assert parse_channel(f"solus:live:team:{scope}") == Channel.team(scope)
    assert parse_channel(f"solus:live:user:{scope}") == Channel.user(scope)
    assert parse_channel(f"solus:live:project:{scope}") == Channel.project(scope)
    assert parse_channel(f"solus:graph:{scope}") == Channel.project(scope)


def test_parse_channel_rejects_malformed_names() -> None:
    scope = uuid.uuid4()
    for raw in (
        "",
        "garbage",
        f"solus:live:galaxy:{scope}",
        f"solus:live:team:{scope}:extra",
        "solus:live:team:not-a-uuid",
        f"solus:live:team:{{{scope}}}",
        f"solus:live:team:{scope.hex}",
        f"other:live:team:{scope}",
        f"solus:graph:{scope}:x",
        f"solus:live:{scope}",
    ):
        assert parse_channel(raw) is None, raw


# ------------------------------------------------------- multi-channel subscriptions


async def test_a_subscription_receives_frames_from_each_of_its_channels() -> None:
    hub = LiveHub()
    project, team, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sub = hub.subscribe_channels([Channel.project(project), Channel.team(team)])

    await hub.publish_to(Channel.project(project), FRAME)
    await hub.publish_to(Channel.team(team), FRAME)
    await hub.publish_to(Channel.user(user), FRAME)  # not subscribed

    first = await asyncio.wait_for(sub.queue.get(), timeout=1)
    second = await asyncio.wait_for(sub.queue.get(), timeout=1)
    assert first[0] == Channel.project(project)
    assert second[0] == Channel.team(team)
    assert json.loads(first[1])["type"] == "team.updated"
    assert sub.queue.empty()


async def test_same_scope_id_on_different_kinds_never_crosses() -> None:
    hub = LiveHub()
    scope = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.user(scope)])

    await hub.publish_to(Channel.team(scope), FRAME)

    assert sub.queue.empty()


async def test_resubscribe_replaces_the_channel_set() -> None:
    hub = LiveHub()
    keep, drop, add = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sub = hub.subscribe_channels([Channel.team(keep), Channel.team(drop)])

    hub.resubscribe(sub, [Channel.team(keep), Channel.team(add)])
    await hub.publish_to(Channel.team(drop), FRAME)
    await hub.publish_to(Channel.team(add), FRAME)
    await hub.publish_to(Channel.team(keep), FRAME)

    got = [sub.queue.get_nowait()[0] for _ in range(2)]
    assert got == [Channel.team(add), Channel.team(keep)]
    assert sub.queue.empty()
    assert sub.channels == frozenset({Channel.team(keep), Channel.team(add)})


async def test_resubscribe_keeps_the_same_queue() -> None:
    hub = LiveHub()
    sub = hub.subscribe_channels([Channel.team(uuid.uuid4())])
    queue = sub.queue

    hub.resubscribe(sub, [Channel.team(uuid.uuid4())])

    assert sub.queue is queue


async def test_unsubscribe_channels_stops_delivery_and_cleans_up() -> None:
    hub = LiveHub()
    project = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.project(project)])
    assert hub.subscriber_count(project) == 1

    hub.unsubscribe_channels(sub)
    hub.unsubscribe_channels(sub)  # idempotent
    await hub.publish_to(Channel.project(project), FRAME)

    assert sub.queue.empty()
    assert hub.subscriber_count(project) == 0
    assert hub.subscribed_project_ids() == []


async def test_a_resubscribe_after_unsubscribe_does_not_revive_the_subscription() -> None:
    hub = LiveHub()
    scope = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.team(scope)])
    hub.unsubscribe_channels(sub)

    hub.resubscribe(sub, [Channel.team(scope)])
    await hub.publish_to(Channel.team(scope), FRAME)

    assert sub.queue.empty()


async def test_queue_depth_is_32_and_overflow_is_dropped_without_stalling_neighbours() -> None:
    hub = LiveHub()
    scope = uuid.uuid4()
    stalled = hub.subscribe_channels([Channel.team(scope)])
    healthy = hub.subscribe_channels([Channel.team(scope)])

    for _ in range(200):
        await hub.publish_to(Channel.team(scope), FRAME)
        healthy.queue.get_nowait()

    assert stalled.queue.full()
    assert stalled.queue.qsize() == 32
    assert healthy.queue.empty()


async def test_a_newline_bearing_payload_is_dropped_on_every_channel_kind() -> None:
    hub = LiveHub()
    scope = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.user(scope)])

    hub._deliver(Channel.user(scope), '{"type":"x"}\n\nevent: forged\ndata: {}')

    assert sub.queue.empty()


# ------------------------------------------------------------------- publishing


async def test_publish_to_with_redis_only_publishes_and_uses_the_contract_channel() -> None:
    redis = _Redis()
    hub = LiveHub(redis)
    team = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.team(team)])

    await hub.publish_to(Channel.team(team), FRAME)

    assert [name for name, _ in redis.published] == [channel_name("team", team)]
    assert json.loads(redis.published[0][1]) == FRAME
    assert sub.queue.empty(), "delivery belongs to the relay when Redis is configured"


async def test_publish_to_falls_back_to_local_delivery_when_redis_fails() -> None:
    hub = LiveHub(_Redis(fail=True))
    team = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.team(team)])

    await hub.publish_to(Channel.team(team), FRAME)

    assert (await asyncio.wait_for(sub.queue.get(), timeout=1))[0] == Channel.team(team)


async def test_publish_to_without_redis_delivers_locally() -> None:
    hub = LiveHub()
    user = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.user(user)])

    await hub.publish_to(Channel.user(user), FRAME)

    assert not sub.queue.empty()


async def test_legacy_publish_is_a_project_channel_publish() -> None:
    redis = _Redis()
    hub = LiveHub(redis)
    project = uuid.uuid4()

    await hub.publish(project, FRAME)

    assert [name for name, _ in redis.published] == [channel_name("project", project)]


async def test_legacy_and_multi_channel_subscribers_both_receive_project_frames() -> None:
    hub = LiveHub()
    project = uuid.uuid4()
    legacy = hub.subscribe(project)
    multi = hub.subscribe_channels([Channel.project(project)])
    assert hub.subscriber_count(project) == 2
    assert hub.subscribed_project_ids() == [project]

    await hub.publish(project, FRAME)

    assert "team.updated" in legacy.get_nowait()
    assert multi.queue.get_nowait()[0] == Channel.project(project)
    hub.unsubscribe(project, legacy)
    hub.unsubscribe_channels(multi)
    assert hub.subscribed_project_ids() == []


async def test_publish_local_never_touches_redis_and_reaches_project_subscribers() -> None:
    redis = _Redis()
    hub = LiveHub(redis)
    project = uuid.uuid4()
    sub = hub.subscribe_channels([Channel.project(project)])

    hub.publish_local(project, {"type": "hardware.devices_changed"})

    assert redis.published == []
    assert "hardware.devices_changed" in sub.queue.get_nowait()[1]


def test_fanout_mode_reports_redis_or_local_only() -> None:
    assert LiveHub().fanout_mode == "local_only"
    assert LiveHub(_Redis()).fanout_mode == "redis"


# ------------------------------------------------------------------------ relay


async def test_the_relay_subscribes_both_patterns_and_delivers_by_parsed_channel() -> None:
    project, team, user, legacy = (uuid.uuid4() for _ in range(4))
    messages = [
        _pmessage(channel_name("team", team), json.dumps(FRAME)),
        _pmessage(channel_name("user", user).encode(), json.dumps(FRAME).encode()),
        _pmessage(f"solus:graph:{legacy}", json.dumps({"type": "graph.changed"})),
        _pmessage(channel_name("project", project), json.dumps({"type": "graph.changed"})),
        {"type": "psubscribe"},
        _pmessage("solus:live:team:garbage", json.dumps(FRAME)),
        _pmessage("solus:live:moon:" + str(team), json.dumps(FRAME)),
    ]
    redis = _RelayRedis(messages)
    hub = LiveHub(redis)
    subs = {
        "team": hub.subscribe_channels([Channel.team(team)]),
        "user": hub.subscribe_channels([Channel.user(user)]),
        "legacy": hub.subscribe_channels([Channel.project(legacy)]),
        "project": hub.subscribe_channels([Channel.project(project)]),
    }

    await hub.start()
    try:
        for name, sub in subs.items():
            channel, _payload = await asyncio.wait_for(sub.queue.get(), timeout=1)
            assert channel.kind == (name if name != "legacy" else "project")
        await asyncio.sleep(0.05)
        assert all(sub.queue.empty() for sub in subs.values()), "malformed channel was delivered"
        assert set(redis.pubsub_obj.patterns) == {"solus:live:*", "solus:graph:*"}
    finally:
        await hub.stop()
    assert redis.pubsub_obj.closed
