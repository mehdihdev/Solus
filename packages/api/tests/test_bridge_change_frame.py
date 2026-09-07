"""SOLUSDEV-167: the local-bridge change producer.

A design change on the customer's machine had no way to reach the cloud. This is
the frame that closes it — and the frame is a HINT, so most of what matters here
is what it is NOT allowed to do.
"""

from __future__ import annotations

from solus_api.bridge.frames import (
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    FrameViolation,
    InboundFrame,
    parse_frame,
)

CAPS = {"control_cap": 16 * 1024, "tool_result_cap": 1024 * 1024}


def test_change_is_an_inbound_only_frame() -> None:
    """Companion -> cloud. The cloud never sends one; a change is something the
    machine observes, not something the cloud announces."""
    assert "change" in INBOUND_TYPES
    assert "change" not in OUTBOUND_TYPES


def test_an_empty_change_frame_parses() -> None:
    frame = parse_frame('{"type":"change","data":{}}', **CAPS)

    assert isinstance(frame, InboundFrame)
    assert frame.type == "change"
    assert frame.payload is None


def test_a_change_frame_carrying_data_is_a_violation() -> None:
    """The payload is empty BY DESIGN: the type is the whole message. It carries
    no digest (the connector's own detect_changes is the authority) and no server
    name (the sensor watches one workspace shared by both forks, so attributing
    kicad vs altium would be a guess). Rejecting a payload keeps that true rather
    than merely intended — otherwise a field nothing reads accretes and rots."""
    frame = parse_frame('{"type":"change","data":{"digest":"abc"}}', **CAPS)

    assert isinstance(frame, FrameViolation)
    assert "no data" in frame.reason


def test_the_protocol_version_is_not_bumped_by_this_addition() -> None:
    """Per the bridge contract's §4 extension rule, a NEW frame type does not
    bump protocol_version — an old peer logs and ignores it. Asserted so nobody
    'helpfully' bumps it later and strands every deployed companion."""
    from solus_api.bridge.frames import PROTOCOL_VERSION

    assert PROTOCOL_VERSION == 1


# --------------------------------------------------- the handler's boundaries
#
# The parse tests above cover the wire shape. These cover the part that can
# actually hurt: an untrusted companion asking the cloud to do work.

import asyncio  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any, cast  # noqa: E402

import pytest  # noqa: E402
from solus_api.bridge.registry import BridgeSession  # noqa: E402
from solus_api.bridge.service import TokenBucket  # noqa: E402
from solus_api.models import (  # noqa: E402
    Project,
    Source,
    SourceStatus,
    SourceType,
    Team,
)
from solus_api.routers.bridge import _handle_notification, _resync_local_sources  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402


def _session(*, project_id: uuid.UUID, may_write: bool = True) -> BridgeSession:
    async def _send(_: str) -> None: ...

    async def _close(_: int) -> None: ...

    return BridgeSession(
        session_id="s1",
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        project_id=project_id,
        companion_instance_id="c1",
        companion_version="1",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(),
        send=_send,
        close=_close,
        max_inflight=1,
        may_write=may_write,
    )


class _Bucket:
    def __init__(self, allow: bool = True) -> None:
        self._allow = allow
        self.calls = 0

    def allow(self) -> bool:
        self.calls += 1
        return self._allow


class _State:
    """Just enough app state for the resync path, with a recording registry."""

    def __init__(self, maker: Any) -> None:
        self.sessionmaker = maker
        self.connector_registry = None
        self.secret_store = None


def _change_frame() -> Any:
    from solus_api.bridge.frames import parse_frame

    return parse_frame('{"type":"change","data":{}}', control_cap=16 * 1024, tool_result_cap=1024)


def test_a_read_only_principal_cannot_trigger_a_resync(monkeypatch: Any) -> None:
    """THE gate. A bridge socket is authorized for reads by membership alone, but
    a change frame triggers a graph WRITE — including tombstones. Without this a
    viewer, or a share-only user whose membership is None, could wipe the team's
    local subtree with a degraded export."""
    scheduled: list[object] = []
    monkeypatch.setattr(
        "solus_api.routers.bridge._schedule_local_resync",
        lambda state, session: scheduled.append(session),
    )
    session = _session(project_id=uuid.uuid4(), may_write=False)

    violation = _handle_notification(
        object(), session, _change_frame(), frozenset(), cast(TokenBucket, _Bucket())
    )

    assert scheduled == [], "a read-only principal scheduled a graph write"
    assert violation is True


def test_a_member_does_trigger_a_resync(monkeypatch: Any) -> None:
    scheduled: list[object] = []
    monkeypatch.setattr(
        "solus_api.routers.bridge._schedule_local_resync",
        lambda state, session: scheduled.append(session),
    )
    session = _session(project_id=uuid.uuid4(), may_write=True)

    violation = _handle_notification(
        object(), session, _change_frame(), frozenset(), cast(TokenBucket, _Bucket())
    )

    assert len(scheduled) == 1
    assert violation is False


def test_the_rate_limit_stops_scheduling(monkeypatch: Any) -> None:
    scheduled: list[object] = []
    monkeypatch.setattr(
        "solus_api.routers.bridge._schedule_local_resync",
        lambda state, session: scheduled.append(session),
    )
    session = _session(project_id=uuid.uuid4())

    violation = _handle_notification(
        object(), session, _change_frame(), frozenset(), cast(TokenBucket, _Bucket(allow=False))
    )

    assert scheduled == [], "a frame past the budget still scheduled work"
    assert violation is False  # dropped, not punished — the companion may be busy


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_sources(maker: Any) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """One project with a KiCad AND an Onshape source, plus a second project."""
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        mine = Project(team_id=team.id, name="mine")
        theirs = Project(team_id=team.id, name="theirs")
        db.add_all([mine, theirs])
        await db.flush()
        ids = {}
        for name, project, kind in (
            ("kicad", mine, SourceType.KICAD),
            ("onshape", mine, SourceType.ONSHAPE),
            ("other_project_kicad", theirs, SourceType.KICAD),
        ):
            src = Source(
                project_id=project.id,
                team_id=team.id,
                type=kind,
                name=name,
                status=SourceStatus.CONNECTED,
                config={},
            )
            db.add(src)
            await db.flush()
            ids[name] = src.id
        await db.commit()
        return mine.id, theirs.id, ids


async def test_a_change_frame_never_syncs_a_cloud_api_source(maker: Any, monkeypatch: Any) -> None:
    """The single most security-load-bearing line in this feature. A companion
    frame must not be able to trigger an Onshape sync — that would let software
    on a customer machine spend the account's ANNUAL API allowance."""
    project_id, _, ids = await _seed_sources(maker)
    synced: list[uuid.UUID] = []

    async def _fake(**kwargs: Any) -> None:
        synced.append(kwargs["source_id"])

    monkeypatch.setattr("solus_api.connectors.worker.execute_source_sync", _fake)
    await _resync_local_sources(_State(maker), _session(project_id=project_id))

    assert ids["onshape"] not in synced, "a companion frame reached a cloud-API source"
    assert synced == [ids["kicad"]]


async def test_a_change_frame_cannot_reach_another_project(maker: Any, monkeypatch: Any) -> None:
    """Scope comes from the SESSION, bound server-side at connect — never from
    the frame, which carries nothing."""
    project_id, _, ids = await _seed_sources(maker)
    synced: list[uuid.UUID] = []

    async def _fake(**kwargs: Any) -> None:
        synced.append(kwargs["source_id"])

    monkeypatch.setattr("solus_api.connectors.worker.execute_source_sync", _fake)
    await _resync_local_sources(_State(maker), _session(project_id=project_id))

    assert ids["other_project_kicad"] not in synced


async def test_the_resync_passes_the_companions_user_not_the_source_creator(
    maker: Any, monkeypatch: Any
) -> None:
    """Without this the acquirer's exact (user, team, project) lookup misses, it
    declines, and the read falls through to the STALE committed export —
    producing a "changed" notification containing no change."""
    project_id, _, _ = await _seed_sources(maker)
    seen: list[uuid.UUID | None] = []

    async def _fake(**kwargs: Any) -> None:
        seen.append(kwargs["acting_user_id"])

    monkeypatch.setattr("solus_api.connectors.worker.execute_source_sync", _fake)
    session = _session(project_id=project_id)
    await _resync_local_sources(_State(maker), session)

    assert seen == [session.user_id]


async def test_frames_arriving_during_a_resync_do_not_stack(maker: Any, monkeypatch: Any) -> None:
    """One in-flight resync per session.

    Without this, every accepted frame spawned another fan-out over all of the
    project's local sources — and single-flight does NOT collapse them, since a
    loser waits up to 30s per source and then does the work anyway. At 12
    frames/min across 10 sessions per team that is ~120 concurrent fan-outs in
    the shared API process: one tenant starving the rest.

    A frame arriving mid-resync is not lost: the running pass re-reads the
    workspace, so it already covers the change that just landed.
    """
    import solus_api.routers.bridge as bridge_mod

    project_id, _, _ = await _seed_sources(maker)
    session = _session(project_id=project_id)
    release = asyncio.Event()
    started = 0

    async def _slow(state: Any, sess: Any, **_: Any) -> None:
        nonlocal started
        started += 1
        await release.wait()

    monkeypatch.setattr(bridge_mod, "_resync_local_sources", _slow)
    bridge_mod._INFLIGHT_RESYNC.clear()

    for _ in range(10):
        bridge_mod._schedule_local_resync(_State(maker), session)
    await asyncio.sleep(0.05)

    assert started == 1, f"{started} resyncs ran concurrently for one session"

    release.set()
    await asyncio.sleep(0.05)
    assert session.session_id not in bridge_mod._INFLIGHT_RESYNC, "the slot was never released"
