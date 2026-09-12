"""SOLUSDEV-167 acceptance #3 and #6: live propagation, and its tenant boundary.

#3 — a change reaches a second open session with nobody polling.
#6 — a subscriber can never receive another project's updates, and that is
     enforced structurally (routing by project) rather than by filtering frames.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from conftest import requires_occt
from solus_api.graph.live import LiveHub, channel, graph_changed_frame, hardware_devices_frame
from solus_api.routers.live import _frame_event_type


class _Counts:
    entities_created = 1
    entities_updated = 0
    entities_deleted = 0
    relations_created = 0
    relations_deleted = 0


def _frame(project_id: uuid.UUID) -> dict[str, Any]:
    return graph_changed_frame(
        project_id=project_id,
        source_id=uuid.uuid4(),
        sync_id=uuid.uuid4(),
        counts=_Counts(),
        at="2026-08-31T00:00:00+00:00",
    )


async def test_a_subscriber_receives_its_own_projects_change() -> None:
    hub = LiveHub()
    project = uuid.uuid4()
    queue = hub.subscribe(project)

    await hub.publish(project, _frame(project))

    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert "graph.changed" in payload


async def test_two_sessions_on_one_project_both_receive_it() -> None:
    """The teammate case: one engineer's sync reaches every open session."""
    hub = LiveHub()
    project = uuid.uuid4()
    alice = hub.subscribe(project)
    bob = hub.subscribe(project)

    await hub.publish(project, _frame(project))

    assert await asyncio.wait_for(alice.get(), timeout=1.0)
    assert await asyncio.wait_for(bob.get(), timeout=1.0)


async def test_a_frame_never_crosses_a_project() -> None:
    """AC#6. Proven with a SENTINEL rather than a sleep: publish to the other
    project, then to this one, and assert the first frame this subscriber sees
    is its own. A timeout-based test would pass just as well against a hub that
    delivers late, and a sleep-based one is a race.
    """
    hub = LiveHub()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    queue = hub.subscribe(mine)

    await hub.publish(theirs, _frame(theirs))  # must not arrive
    await hub.publish(mine, _frame(mine))  # the sentinel

    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert str(mine) in payload
    assert str(theirs) not in payload
    assert queue.empty(), "a foreign project's frame was delivered"


async def test_routing_is_by_channel_not_by_body() -> None:
    """The isolation argument is that the CHANNEL decides delivery. If a future
    change ever routes on `frame.project_id` instead, this catches it: the body
    here names another project, and it must still be delivered by channel."""
    hub = LiveHub()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    queue = hub.subscribe(mine)

    await hub.publish(mine, _frame(theirs))

    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert str(theirs) in payload


async def test_unsubscribing_stops_delivery() -> None:
    hub = LiveHub()
    project = uuid.uuid4()
    queue = hub.subscribe(project)
    hub.unsubscribe(project, queue)

    await hub.publish(project, _frame(project))

    assert queue.empty()
    assert hub.subscriber_count(project) == 0


async def test_a_subscriber_that_stops_reading_does_not_stall_the_others() -> None:
    """A slept laptop must not grow a queue without bound or slow anyone else.
    Dropping is safe precisely because the frame is a HINT — the next one the
    client does receive triggers the same refetch."""
    hub = LiveHub()
    project = uuid.uuid4()
    stalled = hub.subscribe(project)
    healthy = hub.subscribe(project)

    for _ in range(200):
        await hub.publish(project, _frame(project))

    assert stalled.full()
    assert not healthy.empty()
    assert await asyncio.wait_for(healthy.get(), timeout=1.0)


async def test_a_broken_redis_falls_back_to_local_delivery() -> None:
    """Fan-out must never be the reason a sync looks failed."""

    class Broken:
        async def publish(self, *a: object, **k: object) -> None:
            raise RuntimeError("down")

    hub = LiveHub(Broken())
    project = uuid.uuid4()
    queue = hub.subscribe(project)

    await hub.publish(project, _frame(project))

    assert await asyncio.wait_for(queue.get(), timeout=1.0)


def test_the_channel_is_project_scoped() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()

    assert channel(a) != channel(b)
    assert str(a) in channel(a)


def test_the_frame_carries_a_hint_not_a_payload() -> None:
    """It must stay small and contain no entity data: widgets refetch, they do
    not consume the frame (widget-contract.md)."""
    frame = _frame(uuid.uuid4())

    assert frame["type"] == "graph.changed"
    assert set(frame) == {"type", "project_id", "source_id", "sync_id", "counts", "at"}
    assert "entities" not in frame
    assert frame["counts"]["entities_deleted"] == 0


# ------------------------------------------------------- end to end (AC#3)


@requires_occt  # type: ignore[untyped-decorator]
async def test_a_real_sync_reaches_a_subscriber(engine: Any) -> None:
    """AC#3 end to end: drive an actual sync and assert the frame arrives —
    without the subscriber polling anything."""
    import respx
    from fixtures.onshape_fake import FakeOnshape
    from solus_api.connectors.httpcache import InMemoryCacheStore
    from solus_api.connectors.onshape import OnshapeConnector
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.runtime import refresh_secret_ref
    from solus_api.connectors.secrets import InMemorySecretStore
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Project, Source, SourceStatus, SourceType, Team
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"source/{uuid.uuid4()}/onshape"
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={"documents": ["dA"]},
            secret_ref=secret_ref,
            account_external_id="acct-1",
        )
        db.add(source)
        await db.commit()
        project_id, source_id = project.id, source.id

    secrets = InMemorySecretStore()
    await secrets.put(secret_ref, "tok")
    await secrets.put(refresh_secret_ref(secret_ref), "rt")

    registry = ConnectorRegistry()
    registry.register(
        "onshape",
        lambda: OnshapeConnector(client_id="cid", client_secret="sec", poll_interval=0.0),
    )

    hub = LiveHub()
    queue = hub.subscribe(project_id)  # a teammate's session, already open

    async with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=FakeOnshape())
        await execute_source_sync(
            source_id=source_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=secrets,
            store=InMemoryCacheStore(),
            hub=hub,
        )

    payload = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert "graph.changed" in payload
    assert str(project_id) in payload


def test_a_no_op_sync_reports_no_change_so_nobody_is_woken() -> None:
    """`_commit_success` publishes only when `counts.changed`, so this property
    IS the gate — a sync that moved nothing must not wake every open session.

    (An earlier version of this test built a hub and wrote `if counts.changed:`
    after asserting it was False. mypy called the branch unreachable and was
    right: it exercised nothing. The property is the thing worth pinning.)
    """
    from solus_api.connectors.runtime import _Counts

    assert _Counts().changed is False


def test_every_kind_of_movement_counts_as_a_change() -> None:
    """The other direction: each counter must be able to trigger a frame on its
    own, or some real change would propagate to nobody."""
    from solus_api.connectors.runtime import _Counts

    for field in (
        "entities_created",
        "entities_updated",
        "entities_deleted",
        "relations_created",
        "relations_deleted",
    ):
        counts = _Counts()
        setattr(counts, field, 1)
        assert counts.changed is True, f"{field} alone did not count as a change"


async def test_a_delete_only_sync_still_counts_as_changed() -> None:
    from solus_api.connectors.runtime import _Counts

    counts = _Counts()
    counts.entities_deleted = 1

    assert counts.changed is True


# ------------------------------------------------------ the route's boundary
#
# Authorization failures DO complete over ASGITransport: `ProjectCtx` raises
# during dependency resolution, so no StreamingResponse is ever constructed and
# the response returns in milliseconds. An earlier version of this file claimed
# these would hang and skipped them — that was wrong, and it skipped exactly the
# §7-mandated "team A cannot read team B" proof. Only the HAPPY path hangs,
# because httpx buffers an open-ended stream; that one is genuinely absent and
# the reason is recorded below.


async def test_an_unauthenticated_request_cannot_subscribe(client: Any) -> None:

    # Any project id will do — the auth check precedes the lookup.
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/events")

    assert resp.status_code == 401


async def test_a_non_member_cannot_subscribe_to_another_teams_project(
    client: Any, alice_headers: Any, bob_headers: Any
) -> None:
    """AC#6 at the HTTP edge, and the §7 cross-tenant proof for this endpoint."""
    from conftest import create_project, create_team

    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    resp = await client.get(f"/api/v1/projects/{project['id']}/events", headers=bob_headers)

    assert resp.status_code in (403, 404), "a non-member opened another team's stream"


async def test_a_nonexistent_project_is_refused(client: Any, alice_headers: Any) -> None:
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/events", headers=alice_headers)

    assert resp.status_code in (403, 404)


# --------------------------------------- what is NOT here, and why
#
# No HAPPY-PATH streaming test: httpx's ASGITransport buffers a whole response
# before returning it, so an open-ended event stream never yields to the client
# and such a test HANGS rather than fails — worse than absent. (The bridge suite
# hits the same wall and reaches for a threaded TestClient; that is the tool if
# end-to-end stream coverage is ever needed.)
#
# Covered instead: fan-out, project isolation, backpressure and Redis fallback by
# the hub tests above, which exercise the exact code the route streams from; and
# a real sync reaching a subscriber by test_a_real_sync_reaches_a_subscriber.
#
# One thing the missing coverage cost, recorded so it is not re-learned: the
# route originally held its request-scoped DB session for the LIFE of the
# subscription, because FastAPI tears a yield-dependency down only after the
# response is fully sent. Every subscriber would have pinned a pooled connection
# `idle in transaction` for hours. It surfaced as a hanging test rather than a
# failing one; the fix is the explicit `await session.close()` in the route.


async def test_a_frame_containing_a_blank_line_is_dropped() -> None:
    """SSE frames are newline-delimited, so a payload with a blank line would END
    the frame and let everything after it be read as further events — arbitrary
    event injection into a subscriber's stream.

    `graph_changed_frame` + json.dumps cannot produce one, but the relay
    psubscribes to a WILDCARD and parses nothing, so any future publisher on that
    pattern would inherit the hole. Dropped rather than sanitised: a frame we
    cannot vouch for is worth losing, and the next one triggers the same refetch.
    """
    hub = LiveHub()
    project = uuid.uuid4()
    queue = hub.subscribe(project)

    hub._deliver(project, '{"type":"graph.changed"}\n\nevent: forged\ndata: {}')

    assert queue.empty(), "a newline-bearing payload reached a subscriber"


# ------------------------------------ SOLUSDEV-250: local-only device frames


async def test_publish_local_never_touches_redis_and_still_delivers() -> None:
    """One machine's device list must never fan out to another machine's session."""

    class Spy:
        calls = 0

        async def publish(self, *a: object, **k: object) -> None:
            self.calls += 1

    redis = Spy()
    hub = LiveHub(redis)
    project = uuid.uuid4()
    queue = hub.subscribe(project)

    hub.publish_local(project, {"type": "hardware.devices_changed"})

    assert redis.calls == 0
    assert "hardware.devices_changed" in await asyncio.wait_for(queue.get(), timeout=1.0)


def test_subscribed_project_ids_reflects_subscribe_and_unsubscribe() -> None:
    hub = LiveHub()
    a, b = uuid.uuid4(), uuid.uuid4()
    assert hub.subscribed_project_ids() == []

    qa, qb = hub.subscribe(a), hub.subscribe(b)
    assert set(hub.subscribed_project_ids()) == {a, b}

    hub.unsubscribe(a, qa)
    assert hub.subscribed_project_ids() == [b]
    hub.unsubscribe(b, qb)
    assert hub.subscribed_project_ids() == []


def test_hardware_devices_frame_shape() -> None:
    project = uuid.uuid4()
    devices: list[dict[str, Any]] = [{"device_ref": "usb:abc"}, {"device_ref": None}]

    frame = hardware_devices_frame(
        project_id=project, devices=devices, at="2026-09-07T00:00:00+00:00"
    )

    assert frame == {
        "type": "hardware.devices_changed",
        "project_id": str(project),
        "devices": devices,
        "at": "2026-09-07T00:00:00+00:00",
    }


def test_frame_event_type_passes_known_types_and_defaults_the_rest() -> None:
    assert _frame_event_type('{"type":"graph.changed"}') == "graph.changed"
    assert _frame_event_type('{"type":"hardware.devices_changed"}') == "hardware.devices_changed"
    for payload in (
        "not json",
        "{}",
        '{"type": 3}',
        "[1,2]",
        '"graph.changed"',
        '{"type":"Forged"}',
        '{"type":"a\\nevent: forged"}',
        '{"type":"' + "x" * 65 + '"}',
        '{"type":".hidden"}',
    ):
        assert _frame_event_type(payload) == "graph.changed", payload


def test_frame_event_type_rejects_a_trailing_newline_or_return() -> None:
    """`$` matches before a final newline, so a `type` of "graph.changed\\n" would have split its
    own SSE record; `fullmatch` closes that (review of Phase 1, SOLUSDEV-250)."""
    assert _frame_event_type('{"type":"graph.changed\\n"}') == "graph.changed"
    assert _frame_event_type('{"type":"hardware.devices_changed\\r"}') == "graph.changed"
    assert _frame_event_type('{"type":"x\\n\\nevent: forged"}') == "graph.changed"
