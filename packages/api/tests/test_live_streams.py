"""ADR-037 §5-6 — the project and account SSE streams, end to end through the real app.

httpx's ASGITransport buffers a whole response, so an open-ended event stream would hang a
test. These tests therefore drive the ASGI app directly and read the body as it is sent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from conftest import ALICE, BOB, add_member, bearer, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.graph import live_publisher
from solus_api.graph.live import Channel, LiveHub
from solus_api.graph.live_access import LiveAccessVerifier
from solus_api.main import create_app
from solus_api.models import (
    Job,
    JobKind,
    Membership,
    Notification,
    NotificationType,
    ProjectMembership,
    Source,
    SourceType,
    utcnow,
)
from solus_api.routers import live as live_routes
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

TIMEOUT = 3.0
Event = tuple[str, Any]


class Stream:
    """One open SSE response, read incrementally."""

    def __init__(self, app: Any, path: str, headers: dict[str, str]) -> None:
        self.status = 0
        self.body = b""
        self.ready_data: Any = None
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._buffer = ""
        self._started = asyncio.Event()
        self._disconnect = asyncio.Event()
        self._task = asyncio.create_task(self._run(app, path, headers))

    async def _run(self, app: Any, path: str, headers: dict[str, str]) -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "server": ("test", 80),
            "client": ("127.0.0.1", 1),
            "scheme": "http",
            "root_path": "",
        }
        sent_request = False

        async def receive() -> dict[str, Any]:
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await self._disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self._started.set()
            elif message["type"] == "http.response.body":
                self.body += message.get("body", b"")
                await self._chunks.put(message.get("body", b""))

        try:
            await app(scope, receive, send)
        finally:
            self._started.set()
            await self._chunks.put(None)

    async def started(self) -> None:
        await asyncio.wait_for(self._started.wait(), TIMEOUT)
        if self.status != 200:  # an error response completes: wait for its whole body
            await asyncio.wait_for(asyncio.shield(self._task), TIMEOUT)

    async def next(self, *, keepalive: bool = False, timeout: float = TIMEOUT) -> Event:
        """The next event. Raises EOFError when the response has ended."""
        while True:
            record = self._pop_record()
            if record is not None:
                if record == ":" and not keepalive:
                    continue
                return self._parse(record)
            chunk = await asyncio.wait_for(self._chunks.get(), timeout)
            if chunk is None:
                raise EOFError("stream ended")
            self._buffer += chunk.decode()

    def _pop_record(self) -> str | None:
        if "\n\n" not in self._buffer:
            return None
        record, _, self._buffer = self._buffer.partition("\n\n")
        return ":" if record.startswith(":") else record

    @staticmethod
    def _parse(record: str) -> Event:
        if record == ":":
            return "keepalive", None
        name, data = "message", ""
        for line in record.split("\n"):
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        return name, json.loads(data)

    async def until(self, wanted: str, *, where: Callable[[Any], bool] = lambda _: True) -> Any:
        while True:
            name, data = await self.next()
            if name == wanted and where(data):
                return data

    async def collect(self, wanted: set[str]) -> dict[str, Any]:
        """Read until every event name in `wanted` has been seen; return the first of each."""
        seen: dict[str, Any] = {}
        while not wanted <= set(seen):
            name, data = await self.next()
            seen.setdefault(name, data)
        return seen

    async def ended(self, timeout: float = TIMEOUT) -> bool:
        """True once the response completes (draining anything still buffered)."""
        try:
            while True:
                await self.next(keepalive=True, timeout=timeout)
        except EOFError:
            return True
        except TimeoutError:
            return False

    async def close(self) -> None:
        self._disconnect.set()
        try:
            await asyncio.wait_for(self._task, TIMEOUT)
        except (TimeoutError, asyncio.CancelledError):
            self._task.cancel()


OpenStream = Callable[..., Awaitable[Stream]]


@pytest.fixture
async def open_stream(app: FastAPI) -> AsyncIterator[OpenStream]:
    opened: list[Stream] = []

    async def _open(path: str, headers: dict[str, str], *, ready: bool = True) -> Stream:
        stream = Stream(app, path, headers)
        opened.append(stream)
        await stream.started()
        if ready and stream.status == 200:
            name, data = await stream.next()
            assert name == "ready", name
            stream.ready_data = data
        return stream

    yield _open
    for stream in opened:
        await stream.close()


ACCOUNT = "/api/v1/users/me/events"


def project_path(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/events"


@pytest.fixture
def fast_reverify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_routes, "REVERIFY_SECONDS", 0.2)


async def team_with_member(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Alice owns a team and a project; bob is a plain member. Returns team, project, alice, bob."""
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    return team, project, await me(client, alice_headers), await me(client, bob_headers)


# ------------------------------------------------------------------- auth edge


async def test_account_stream_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get(ACCOUNT)).status_code == 401


async def test_account_stream_rejects_a_garbage_token(client: AsyncClient) -> None:
    resp = await client.get(ACCOUNT, headers={"Authorization": "Bearer garbage"})

    assert resp.status_code == 401


async def test_account_stream_rejects_an_expired_token(client: AsyncClient) -> None:
    resp = await client.get(ACCOUNT, headers=bearer(ALICE["sub"], ALICE["email"], expires_in=-5))

    assert resp.status_code == 401


async def test_a_non_member_project_stream_is_404_and_leaks_nothing(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    stream = await open_stream(project_path(project["id"]), bob_headers, ready=False)

    assert stream.status == 404
    assert json.loads(stream.body)["error"]["code"] == "not_found"


# ---------------------------------------------------------------- account stream


async def test_account_stream_ready_names_the_user_and_their_teams(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    alice = await me(client, alice_headers)

    stream = await open_stream(ACCOUNT, alice_headers)

    assert stream.ready_data["user_id"] == alice["id"]
    assert team["id"] in stream.ready_data["team_ids"]
    assert len(stream.ready_data["team_ids"]) == 2  # the team plus the personal team
    assert set(stream.ready_data) == {"user_id", "team_ids"}


async def test_a_members_change_reaches_the_other_members_account_stream(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    alice_stream = await open_stream(ACCOUNT, alice_headers)

    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    seen = await alice_stream.collect(
        {"team.members_changed", "team.activity", "team.invites_changed"}
    )
    assert seen["team.members_changed"]["team_id"] == team["id"]
    assert seen["team.activity"]["team_id"] == team["id"]
    assert "email" not in json.dumps(seen) and "token" not in json.dumps(seen)


async def test_accepting_an_invite_gives_the_acceptor_a_fresh_ready_with_the_new_team(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    bob_stream = await open_stream(ACCOUNT, bob_headers)
    assert team["id"] not in bob_stream.ready_data["team_ids"]

    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    ready = await bob_stream.until("ready", where=lambda d: team["id"] in d["team_ids"])
    assert ready["user_id"] == (await me(client, bob_headers))["id"]


async def test_after_resync_the_new_teams_frames_reach_the_account_stream(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    bob_stream = await open_stream(ACCOUNT, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    await bob_stream.until("ready", where=lambda d: team["id"] in d["team_ids"])

    await create_project(client, alice_headers, team["id"], name="Fresh")

    got = await bob_stream.until("team.projects_changed")
    assert got["team_id"] == team["id"]


async def test_a_member_of_team_b_never_receives_team_a_frames(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team_a = await create_team(client, alice_headers, "A")
    team_b = await create_team(client, bob_headers, "B")
    bob_stream = await open_stream(ACCOUNT, bob_headers)

    await create_project(client, alice_headers, team_a["id"])  # team A noise
    resp = await client.patch(
        f"/api/v1/teams/{team_a['id']}", json={"name": "A2"}, headers=alice_headers
    )
    assert resp.status_code == 200
    await create_project(client, bob_headers, team_b["id"])  # the sentinel, published after

    events: list[Event] = []
    while True:
        event = await bob_stream.next()
        events.append(event)
        if event[0] == "team.projects_changed" and event[1]["team_id"] == team_b["id"]:
            break

    assert team_a["id"] not in json.dumps(events), "team A's frames reached team B's member"


async def test_only_account_event_types_are_forwarded(
    open_stream: OpenStream, app: FastAPI, client: AsyncClient, alice_headers: Any
) -> None:
    alice = await me(client, alice_headers)
    stream = await open_stream(ACCOUNT, alice_headers)
    hub = app.state.graph_hub
    uid = uuid.UUID(alice["id"])
    for bad in (
        {"type": "graph.changed", "at": "t"},
        {"type": "Forged\nevent: x", "at": "t"},
        {"no_type": True},
    ):
        await hub.publish_to(Channel.user(uid), bad)
    await hub.publish_to(
        Channel.user(uid),
        {"type": "notification.created", "user_id": alice["id"], "at": "t"},
    )

    name, _ = await stream.next()

    assert name == "notification.created"


async def test_a_notification_reaches_only_its_recipients_account_stream(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
) -> None:
    alice, bob = await me(client, alice_headers), await me(client, bob_headers)
    alice_stream = await open_stream(ACCOUNT, alice_headers)
    bob_stream = await open_stream(ACCOUNT, bob_headers)
    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker

    async with maker() as s:
        s.add(
            Notification(
                user_id=uuid.UUID(alice["id"]), type=NotificationType.MEMBER_LEFT, title="a"
            )
        )
        await s.commit()
    async with maker() as s:  # the sentinel for bob, committed after alice's
        s.add(
            Notification(user_id=uuid.UUID(bob["id"]), type=NotificationType.MEMBER_LEFT, title="b")
        )
        await s.commit()

    assert (await alice_stream.until("notification.created"))["user_id"] == alice["id"]
    assert (await bob_stream.until("notification.created"))["user_id"] == bob["id"]
    with pytest.raises(TimeoutError):
        await alice_stream.next(timeout=0.3)
    with pytest.raises(TimeoutError):
        await bob_stream.next(timeout=0.3)


async def test_a_removed_member_account_stream_resyncs_without_the_team(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team, _project, _alice, bob = await team_with_member(client, alice_headers, bob_headers)
    bob_stream = await open_stream(ACCOUNT, bob_headers)
    assert team["id"] in bob_stream.ready_data["team_ids"]

    resp = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}", headers=alice_headers
    )
    assert resp.status_code == 204

    ready = await bob_stream.until("ready")
    assert team["id"] not in ready["team_ids"]
    # ...and the team's later frames no longer reach him.
    await create_project(client, alice_headers, team["id"], name="After")
    with pytest.raises(TimeoutError):
        await bob_stream.until("team.projects_changed", where=lambda d: d["team_id"] == team["id"])


async def test_an_expired_token_ends_the_account_stream_at_reverification(
    open_stream: OpenStream, client: AsyncClient, fast_reverify: None
) -> None:
    short = bearer(ALICE["sub"], ALICE["email"], expires_in=1)
    await me(client, bearer(ALICE["sub"], ALICE["email"]))

    stream = await open_stream(ACCOUNT, short)
    revoked = await stream.until("access.revoked")

    assert revoked["user_id"] is not None
    assert await stream.ended()


async def test_account_deletion_ends_that_users_streams(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    await me(client, alice_headers)
    stream = await open_stream(ACCOUNT, alice_headers)

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204

    assert (await stream.until("access.revoked"))["user_id"] is not None
    assert await stream.ended()


async def test_reverification_keeps_a_still_valid_stream_open(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    fast_reverify: None,
) -> None:
    alice = await me(client, alice_headers)
    stream = await open_stream(ACCOUNT, alice_headers)

    await asyncio.sleep(0.7)  # several reverification rounds, nothing changed
    await app.state.graph_hub.publish_to(
        Channel.user(uuid.UUID(alice["id"])),
        {"type": "notification.created", "user_id": alice["id"], "at": "t"},
    )

    assert (await stream.until("notification.created"))["user_id"] == alice["id"]


async def test_the_stream_sends_keepalive_comments_when_idle(
    open_stream: OpenStream,
    client: AsyncClient,
    alice_headers: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_routes, "_KEEPALIVE_SECONDS", 0.1)
    await me(client, alice_headers)
    stream = await open_stream(ACCOUNT, alice_headers)

    name, _ = await stream.next(keepalive=True)

    assert name == "keepalive"


# ---------------------------------------------------------------- project stream


async def test_project_stream_ready_and_graph_frames_keep_working(
    open_stream: OpenStream, app: FastAPI, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    stream = await open_stream(project_path(project["id"]), alice_headers)
    assert stream.ready_data == {"project_id": project["id"]}

    pid = uuid.UUID(project["id"])
    await app.state.graph_hub.publish(pid, {"type": "graph.changed", "project_id": project["id"]})
    await app.state.graph_hub.publish(pid, {"counts": 1})  # no type: legacy default name

    assert (await stream.next())[0] == "graph.changed"
    assert (await stream.next())[0] == "graph.changed"


async def test_workspace_layout_save_reaches_the_project_stream(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    stream = await open_stream(project_path(project["id"]), alice_headers)

    resp = await client.put(
        f"/api/v1/projects/{project['id']}/workspace-layout",
        json={"version": 0, "positions": {}},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text

    frame = await stream.until("layout.changed")
    assert frame["project_id"] == project["id"]
    assert frame["version"] == resp.json()["data"]["version"]


async def test_project_rename_reaches_the_project_and_team_streams(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    project_stream = await open_stream(project_path(project["id"]), alice_headers)
    account_stream = await open_stream(ACCOUNT, alice_headers)

    resp = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "Renamed"}, headers=alice_headers
    )
    assert resp.status_code == 200, resp.text

    updated = await project_stream.until("project.updated")
    assert updated["team_id"] == team["id"]
    changed = await account_stream.until("team.projects_changed")
    assert changed["project_id"] == project["id"]
    assert "Renamed" not in json.dumps([updated, changed])


async def test_user_channel_frames_are_not_forwarded_on_the_project_stream(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team, project, _alice, _bob = await team_with_member(client, alice_headers, bob_headers)
    stream = await open_stream(project_path(project["id"]), bob_headers)

    # A share row for bob raises `membership.changed` on HIS user channel...
    me_bob = await me(client, bob_headers)
    resp = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{me_bob['id']}",
        json={"role": "admin"},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    # ...then a project frame is the sentinel.
    await client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "Sentinel"}, headers=alice_headers
    )

    name, _ = await stream.next()
    assert name == "project.updated"


async def test_removing_a_member_ends_their_project_stream_immediately(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team, project, _alice, bob = await team_with_member(client, alice_headers, bob_headers)
    stream = await open_stream(project_path(project["id"]), bob_headers)
    assert live_routes.REVERIFY_SECONDS >= 30, "the periodic path must not be what ended it"

    resp = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}", headers=alice_headers
    )
    assert resp.status_code == 204

    revoked = await stream.until("access.revoked")
    assert revoked["project_id"] == project["id"]
    assert await stream.ended()


async def test_the_periodic_reverification_ends_a_stream_even_with_no_frame(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
    engine: AsyncEngine,
    fast_reverify: None,
) -> None:
    team, project, _alice, bob = await team_with_member(client, alice_headers, bob_headers)
    stream = await open_stream(project_path(project["id"]), bob_headers)

    # A plain session has no hub, so this publishes NOTHING: only the timer can notice.
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(
            update(Membership)
            .where(Membership.team_id == uuid.UUID(team["id"]))
            .where(Membership.user_id == uuid.UUID(bob["id"]))
            .values(deleted_at=utcnow())
        )
        # Team members are seeded with project shares (ADR-025); the REST route revokes both.
        await s.execute(
            update(ProjectMembership)
            .where(ProjectMembership.user_id == uuid.UUID(bob["id"]))
            .values(deleted_at=utcnow())
        )
        await s.commit()

    revoked = await stream.until("access.revoked")
    assert revoked["project_id"] == project["id"]
    assert await stream.ended()


async def test_a_project_share_keeps_a_non_member_stream_open_until_it_is_revoked(
    open_stream: OpenStream,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
    engine: AsyncEngine,
    fast_reverify: None,
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    bob = await me(client, bob_headers)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(ProjectMembership(project_id=uuid.UUID(project["id"]), user_id=uuid.UUID(bob["id"])))
        await s.commit()
    stream = await open_stream(project_path(project["id"]), bob_headers)

    await asyncio.sleep(0.6)  # a few reverifications: the share still grants access
    async with maker() as s:
        await s.execute(update(ProjectMembership).values(deleted_at=utcnow()))
        await s.commit()

    assert (await stream.until("access.revoked"))["project_id"] == project["id"]
    assert await stream.ended()


async def test_an_expired_token_ends_the_project_stream_at_reverification(
    open_stream: OpenStream, client: AsyncClient, fast_reverify: None
) -> None:
    long_lived = bearer(ALICE["sub"], ALICE["email"])
    team = await create_team(client, long_lived)
    project = await create_project(client, long_lived, team["id"])
    short = bearer(ALICE["sub"], ALICE["email"], expires_in=1)

    stream = await open_stream(project_path(project["id"]), short)

    assert (await stream.until("access.revoked"))["project_id"] == project["id"]
    assert await stream.ended()


async def test_deleting_the_project_ends_its_stream(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    stream = await open_stream(project_path(project["id"]), alice_headers)

    resp = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=alice_headers
    )
    assert resp.status_code == 204

    assert (await stream.until("access.revoked"))["project_id"] == project["id"]
    assert await stream.ended()


async def test_deleting_the_team_ends_member_streams_and_tells_the_team_channel(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team, project, _alice, _bob = await team_with_member(client, alice_headers, bob_headers)
    project_stream = await open_stream(project_path(project["id"]), bob_headers)
    account_stream = await open_stream(ACCOUNT, bob_headers)

    resp = await client.delete(f"/api/v1/teams/{team['id']}?confirm=true", headers=alice_headers)
    assert resp.status_code == 204

    assert await project_stream.until("access.revoked")
    assert await project_stream.ended()
    ready = await account_stream.until("ready")
    assert team["id"] not in ready["team_ids"]


# ------------------------------------------------------------------- stream cap


async def test_the_ninth_concurrent_stream_for_a_user_is_429_across_both_routes(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    streams = [await open_stream(ACCOUNT, alice_headers) for _ in range(4)]
    streams += [await open_stream(project_path(project["id"]), alice_headers) for _ in range(4)]

    refused = await open_stream(ACCOUNT, alice_headers, ready=False)
    refused_project = await open_stream(project_path(project["id"]), alice_headers, ready=False)

    assert refused.status == 429
    assert json.loads(refused.body)["error"]["code"] == "rate_limited"
    assert refused_project.status == 429

    await streams[0].close()
    await asyncio.sleep(0.1)
    reopened = await open_stream(ACCOUNT, alice_headers)
    assert reopened.status == 200


async def test_the_stream_cap_is_per_user(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    for _ in range(8):
        await open_stream(ACCOUNT, alice_headers)

    bob_stream = await open_stream(ACCOUNT, bob_headers)

    assert bob_stream.status == 200


async def test_a_refused_stream_does_not_consume_a_slot(
    open_stream: OpenStream, client: AsyncClient, alice_headers: Any
) -> None:
    streams = [await open_stream(ACCOUNT, alice_headers) for _ in range(8)]
    for _ in range(3):
        assert (await open_stream(ACCOUNT, alice_headers, ready=False)).status == 429

    await streams[0].close()
    await streams[1].close()
    await asyncio.sleep(0.1)

    assert (await open_stream(ACCOUNT, alice_headers)).status == 200
    assert (await open_stream(ACCOUNT, alice_headers)).status == 200


# --------------------------------------------------------------------- readiness


async def test_readyz_reports_local_only_fanout_without_redis(client: AsyncClient) -> None:
    resp = await client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json()["data"]["checks"]["live_fanout"] == "local_only"


async def test_readyz_reports_redis_fanout_when_redis_is_configured(
    settings: Settings, engine: AsyncEngine
) -> None:
    from httpx import ASGITransport

    configured = create_app(
        settings=settings.model_copy(update={"redis_url": "redis://localhost:6399/0"}),
        engine=engine,
    )
    async with AsyncClient(transport=ASGITransport(app=configured), base_url="http://t") as c:
        resp = await c.get("/readyz")

    assert resp.status_code == 200
    assert resp.json()["data"]["checks"]["live_fanout"] == "redis"


def test_startup_warns_that_fanout_is_process_local_without_redis(
    settings: Settings, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="solus.main"):
        create_app(settings=settings, engine=engine)

    assert any(
        r.levelno == logging.WARNING and "live fan-out is process-local" in r.getMessage()
        for r in caplog.records
    )


# --------------------------------------------------- Phase 4 fixes (SOLUSDEV-312)


async def test_frames_queued_before_a_revoke_never_reach_the_removed_member(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A team frame queued while re-verification is in flight is dropped at dequeue once
    the resubscribe has removed the team channel."""
    team, _project, _alice, bob = await team_with_member(client, alice_headers, bob_headers)
    stream = await open_stream(ACCOUNT, bob_headers)
    original = LiveAccessVerifier.account_teams
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(self: LiveAccessVerifier, user_id: uuid.UUID) -> Any:
        entered.set()
        await release.wait()
        return await original(self, user_id)

    monkeypatch.setattr(LiveAccessVerifier, "account_teams", slow)
    resp = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}", headers=alice_headers
    )
    assert resp.status_code == 204
    await asyncio.wait_for(entered.wait(), TIMEOUT)  # re-verification is now in flight

    hub = app.state.graph_hub
    await hub.publish_to(
        Channel.team(uuid.UUID(team["id"])),
        {"type": "team.updated", "team_id": team["id"], "at": "t"},
    )
    release.set()
    await stream.until("ready")  # the resubscribe without the team has happened
    await hub.publish_to(
        Channel.user(uuid.UUID(bob["id"])),
        {"type": "notification.created", "user_id": bob["id"], "at": "t"},
    )

    seen: list[Event] = []
    while True:
        event = await stream.next()
        seen.append(event)
        if event[0] == "notification.created":
            break
    assert all(name != "team.updated" for name, _ in seen), seen


class _AlwaysAllow:
    async def project_access(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return True

    async def account_teams(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        return []


async def _drain_one(frames: Any) -> str:
    return await asyncio.wait_for(frames.__anext__(), TIMEOUT)


async def test_project_stream_skips_frames_for_channels_no_longer_subscribed() -> None:
    hub = LiveHub()
    project, user, removed = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    subscription = hub.subscribe_channels([Channel.project(project), Channel.user(user)])
    frames = live_routes._project_frames(subscription, _AlwaysAllow(), project, user, [])  # type: ignore[arg-type]
    assert "event: ready" in await _drain_one(frames)

    subscription.queue.put_nowait((Channel.project(removed), '{"type":"graph.changed"}'))
    subscription.queue.put_nowait((Channel.project(project), '{"type":"layout.changed"}'))

    out = await _drain_one(frames)
    assert "layout.changed" in out and str(removed) not in out
    await frames.aclose()


async def test_project_stream_forwards_only_project_event_types() -> None:
    hub = LiveHub()
    project, user = uuid.uuid4(), uuid.uuid4()
    subscription = hub.subscribe_channels([Channel.project(project), Channel.user(user)])
    frames = live_routes._project_frames(subscription, _AlwaysAllow(), project, user, [])  # type: ignore[arg-type]
    await _drain_one(frames)

    for payload in (
        '{"type":"team.updated","team_id":"x"}',  # a typed frame the contract says is not ours
        '{"type":"notification.created"}',
        '{"type":"graph.changed","project_id":"p"}',
    ):
        subscription.queue.put_nowait((Channel.project(project), payload))

    out = await _drain_one(frames)
    assert out.startswith("event: graph.changed\n") and "team.updated" not in out
    await frames.aclose()


async def test_project_stream_keeps_forwarding_an_untyped_legacy_frame_as_graph_changed() -> None:
    hub = LiveHub()
    project, user = uuid.uuid4(), uuid.uuid4()
    subscription = hub.subscribe_channels([Channel.project(project), Channel.user(user)])
    frames = live_routes._project_frames(subscription, _AlwaysAllow(), project, user, [])  # type: ignore[arg-type]
    await _drain_one(frames)

    subscription.queue.put_nowait((Channel.project(project), '{"counts":1}'))

    assert (await _drain_one(frames)).startswith("event: graph.changed\n")
    await frames.aclose()


async def test_project_stream_sends_a_fresh_ready_on_resync_and_never_serializes_the_marker() -> (
    None
):
    hub = LiveHub()
    project, user = uuid.uuid4(), uuid.uuid4()
    subscription = hub.subscribe_channels([Channel.project(project), Channel.user(user)])
    frames = live_routes._project_frames(subscription, _AlwaysAllow(), project, user, [])  # type: ignore[arg-type]
    await _drain_one(frames)

    hub._notify_resync()

    out = await _drain_one(frames)
    assert out.startswith("event: ready\n") and str(project) in out
    assert "Resync" not in out and "object at" not in out
    await frames.aclose()


async def test_account_stream_sends_a_fresh_ready_with_current_teams_on_resync(
    open_stream: OpenStream, app: FastAPI, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    stream = await open_stream(ACCOUNT, alice_headers)

    app.state.graph_hub._notify_resync()

    ready = await stream.until("ready")
    assert team["id"] in ready["team_ids"]


async def test_a_project_stream_ends_at_resync_when_access_was_lost_without_a_hint(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
    engine: AsyncEngine,
) -> None:
    _team, project, _alice, bob = await team_with_member(client, alice_headers, bob_headers)
    stream = await open_stream(project_path(project["id"]), bob_headers)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:  # a bulk UPDATE raises no hint: the stream cannot know
        await s.execute(
            update(Membership)
            .where(Membership.user_id == uuid.UUID(bob["id"]))
            .values(deleted_at=utcnow())
        )
        await s.execute(  # team members are seeded with project shares (ADR-025)
            update(ProjectMembership)
            .where(ProjectMembership.user_id == uuid.UUID(bob["id"]))
            .values(deleted_at=utcnow())
        )
        await s.commit()

    app.state.graph_hub._notify_resync()

    assert (await stream.until("access.revoked"))["project_id"] == project["id"]
    assert await stream.ended()


async def test_a_project_stream_never_receives_another_projects_frames(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
) -> None:
    team_a = await create_team(client, alice_headers, "A")
    project_a = await create_project(client, alice_headers, team_a["id"])
    team_b = await create_team(client, bob_headers, "B")
    project_b = await create_project(client, bob_headers, team_b["id"])
    stream = await open_stream(project_path(project_b["id"]), bob_headers)
    pa = uuid.UUID(project_a["id"])

    await client.put(
        f"/api/v1/projects/{project_a['id']}/workspace-layout",
        json={"version": 0, "positions": {}},
        headers=alice_headers,
    )
    await client.patch(
        f"/api/v1/projects/{project_a['id']}", json={"name": "PA2"}, headers=alice_headers
    )
    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    async with maker() as s:  # the app's sessionmaker carries the hub: these publish
        s.add(Source(project_id=pa, team_id=pa_team(team_a), type=SourceType.GITHUB, name="s"))
        s.add(Job(project_id=pa, team_id=pa_team(team_a), kind=next(iter(JobKind))))
        await s.commit()
    await live_publisher.drain_pending_publishes()
    await client.patch(
        f"/api/v1/projects/{project_b['id']}", json={"name": "Sentinel"}, headers=bob_headers
    )

    seen: list[Event] = []
    while True:
        event = await stream.next()
        seen.append(event)
        if event[0] == "project.updated" and event[1]["project_id"] == project_b["id"]:
            break
    assert project_a["id"] not in json.dumps(seen), "project A's frames reached project B's stream"
    assert team_a["id"] not in json.dumps(seen)


def pa_team(team: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(team["id"])


async def test_a_share_only_user_gets_no_team_frames_from_the_shared_projects_team(
    open_stream: OpenStream,
    app: FastAPI,
    client: AsyncClient,
    alice_headers: Any,
    bob_headers: Any,
    engine: AsyncEngine,
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    bob = await me(client, bob_headers)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(ProjectMembership(project_id=uuid.UUID(project["id"]), user_id=uuid.UUID(bob["id"])))
        await s.commit()

    stream = await open_stream(ACCOUNT, bob_headers)

    assert team["id"] not in stream.ready_data["team_ids"]
    await create_project(client, alice_headers, team["id"])  # team noise
    await client.patch(
        f"/api/v1/teams/{team['id']}", json={"name": "Renamed"}, headers=alice_headers
    )
    await app.state.graph_hub.publish_to(
        Channel.user(uuid.UUID(bob["id"])),
        {"type": "notification.created", "user_id": bob["id"], "at": "t"},
    )

    seen: list[Event] = []
    while True:
        event = await stream.next()
        seen.append(event)
        if event[0] == "notification.created":
            break
    assert team["id"] not in json.dumps(seen), "a share-only user received team frames"
