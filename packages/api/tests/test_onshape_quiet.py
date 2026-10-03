"""ADR-038 §2: the quiet period. A burst of Onshape change hints becomes ONE sync.

Time is a scripted clock (never a real sleep): the quiet loop reads `utcnow` from
the worker and the hint recorder reads it from `onshape_webhooks`, so one
`Clock` patched into both makes a three-minute editing burst run in milliseconds
and deterministically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from solus_api.connectors import worker
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, mint_webhook_token
from solus_api.models import Project, Source, SourceStatus, SourceType, SyncTrigger, Team
from solus_api.services import onshape_webhooks as hooks
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

QUIET = 90
START = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def at(self, seconds: float) -> None:
        self.now = START + timedelta(seconds=seconds)

    @property
    def elapsed(self) -> float:
        return (self.now - START).total_seconds()


def _call(mock: AsyncMock) -> Any:
    assert mock.await_args is not None
    return mock.await_args


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(hooks, "utcnow", fake)
    monkeypatch.setattr(worker, "utcnow", fake)
    return fake


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(maker: Any) -> tuple[uuid.UUID, str]:
    token, digest = mint_webhook_token()
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={WEBHOOK_TOKEN_KEY: digest, "documents": ["doc1"]},
        )
        db.add(source)
        await db.commit()
        return source.id, token


async def _hint(maker: Any, source_id: uuid.UUID, event_id: str) -> None:
    async with maker() as db:
        source = await db.get(Source, source_id, with_for_update=True)
        hooks.save_state(source, hooks.hint_state(hooks.state_for(source), event_id=event_id))
        await db.commit()


class ArqPool:
    """Enough of ArqRedis: a stable `_job_id` collapses duplicates, as arq does."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.accepted: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._ids: set[str] = set()

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> object | None:
        self.calls.append((args, kwargs))
        job_id = kwargs.get("_job_id")
        if job_id is not None:
            if job_id in self._ids:
                return None
            self._ids.add(job_id)
        self.accepted.append((args, kwargs))
        return object()


# ------------------------------------------------------------ pure arithmetic


def test_hint_stamps_last_and_first_hint_times(clock: Clock) -> None:
    state = hooks.hint_state({}, event_id="a")
    assert state["last_hint_at"] == START.isoformat()
    assert state["first_hint_at"] == START.isoformat()
    clock.at(30)
    later = hooks.hint_state(state, event_id="b")
    assert later["last_hint_at"] == (START + timedelta(seconds=30)).isoformat()
    assert later["first_hint_at"] == START.isoformat(), "the burst start does not move"


def test_a_gap_longer_than_the_quiet_period_starts_a_new_burst(clock: Clock) -> None:
    state = hooks.hint_state({}, event_id="a")
    clock.at(QUIET + 1)
    later = hooks.hint_state(state, event_id="b", quiet_seconds=QUIET)
    assert later["first_hint_at"] == later["last_hint_at"]


def test_a_duplicate_event_does_not_extend_the_quiet_period(clock: Clock) -> None:
    state = hooks.hint_state({}, event_id="a")
    clock.at(40)
    assert hooks.hint_state(state, event_id="a") == state


def test_quiet_remaining_waits_for_the_last_hint(clock: Clock) -> None:
    state = hooks.hint_state({}, event_id="a")
    clock.at(60)
    assert (
        hooks.quiet_remaining(state, now=clock(), quiet_seconds=QUIET, max_wait_seconds=600) == 30
    )
    clock.at(QUIET)
    assert hooks.quiet_remaining(state, now=clock(), quiet_seconds=QUIET, max_wait_seconds=600) == 0


def test_quiet_remaining_is_zero_without_a_recorded_hint(clock: Clock) -> None:
    assert hooks.quiet_remaining({}, now=clock(), quiet_seconds=QUIET, max_wait_seconds=600) == 0
    garbage = {"last_hint_at": "not-a-date"}
    assert (
        hooks.quiet_remaining(garbage, now=clock(), quiet_seconds=QUIET, max_wait_seconds=600) == 0
    )


def test_quiet_remaining_is_bounded_by_the_maximum_total_wait(clock: Clock) -> None:
    state: dict[str, Any] = {}
    for second in range(0, 700, 30):
        clock.at(second)
        state = hooks.hint_state(state, event_id=str(second), quiet_seconds=QUIET)
    clock.at(660)
    assert hooks.quiet_remaining(state, now=clock(), quiet_seconds=QUIET, max_wait_seconds=600) == 0


def test_acknowledging_moves_the_burst_start_to_the_unacknowledged_hint(clock: Clock) -> None:
    first = hooks.hint_state({}, event_id="a")
    clock.at(20)
    second = hooks.hint_state(first, event_id="b")
    acknowledged = hooks.acknowledge_state(second, 1)
    assert acknowledged["first_hint_at"] == second["last_hint_at"]
    assert "first_hint_at" not in hooks.acknowledge_state(second, 2)


# ------------------------------------------------------- the ARQ (worker) path


async def test_five_hints_over_a_minute_enqueue_one_deferred_job(
    client: AsyncClient, maker: Any, clock: Clock
) -> None:
    source_id, token = await _seed(maker)
    pool = ArqPool()
    client._transport.app.state.arq_pool = pool  # type: ignore[attr-defined]
    url = f"/api/v1/webhooks/onshape/{source_id}/{token}"

    for index in range(5):
        clock.at(index * 15)
        response = await client.post(
            url, json={"event": "onshape.model.lifecycle.changed", "messageId": f"m{index}"}
        )
        assert response.status_code == 204

    assert len(pool.accepted) == 1
    args, kwargs = pool.accepted[0]
    assert args == ("sync_source", str(source_id))
    assert kwargs["_job_id"] == f"onshape-quiet:{source_id}"
    assert kwargs["_defer_by"] == QUIET
    assert kwargs["quiet"] is True
    assert kwargs["webhook"] is True
    async with maker() as db:
        state = hooks.state_for(await db.get(Source, source_id))
    assert state["last_hint_at"] == (START + timedelta(seconds=60)).isoformat()
    assert state["generation"] == 5


def _ctx(maker: Any, **extra: Any) -> dict[str, Any]:
    return {"sessionmaker": maker, "registry": object(), "secret_store": object(), **extra}


async def test_the_queued_job_redefers_itself_until_the_burst_is_quiet(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arq import Retry

    source_id, _ = await _seed(maker)
    for index in range(5):
        clock.at(index * 15)
        await _hint(maker, source_id, f"m{index}")
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)

    clock.at(QUIET)  # the job fires 90 s after the FIRST hint; the last was at 60 s
    with pytest.raises(Retry) as redefer:
        await worker.sync_source(_ctx(maker), str(source_id), webhook=True, quiet=True)
    assert redefer.value.defer_score == pytest.approx(60 * 1000, abs=1)
    execute.assert_not_awaited()

    clock.at(60 + QUIET)
    await worker.sync_source(_ctx(maker), str(source_id), webhook=True, quiet=True)
    execute.assert_awaited_once()
    assert _call(execute).kwargs["trigger"] is SyncTrigger.WEBHOOK


async def test_continuous_editing_still_syncs_after_the_maximum_wait(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, _ = await _seed(maker)
    for second in range(0, 631, 30):
        clock.at(second)
        await _hint(maker, source_id, f"m{second}")
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)

    clock.at(631)  # the most recent hint is one second old, but the burst is >10 minutes
    await worker.sync_source(_ctx(maker), str(source_id), webhook=True, quiet=True)

    execute.assert_awaited_once()


async def test_sync_now_is_never_delayed(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, _ = await _seed(maker)
    await _hint(maker, source_id, "just-now")
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)

    await worker.sync_source(_ctx(maker), str(source_id), str(uuid.uuid4()), str(uuid.uuid4()))
    await worker.sync_source(
        _ctx(maker), str(source_id), str(uuid.uuid4()), str(uuid.uuid4()), quiet=True
    )

    assert execute.await_count == 2


async def test_a_plain_queued_job_without_the_quiet_flag_is_not_delayed(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, _ = await _seed(maker)
    await _hint(maker, source_id, "just-now")
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)

    await worker.sync_source(_ctx(maker), str(source_id))

    execute.assert_awaited_once()


async def test_the_configured_quiet_period_is_honoured(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arq import Retry

    source_id, _ = await _seed(maker)
    await _hint(maker, source_id, "a")
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)
    settings = type("S", (), {"onshape_quiet_period_seconds": 10, "public_api_base_url": ""})()

    clock.at(5)
    with pytest.raises(Retry):
        await worker.sync_source(
            _ctx(maker, settings=settings), str(source_id), webhook=True, quiet=True
        )
    clock.at(10)
    await worker.sync_source(
        _ctx(maker, settings=settings), str(source_id), webhook=True, quiet=True
    )
    execute.assert_awaited_once()


# ---------------------------------------------------- the inline (no Redis) path


class Timeline:
    """A fake `sleep` that replays scripted hints while 'time passes'."""

    def __init__(self, maker: Any, source_id: uuid.UUID, clock: Clock, hints: list[int]) -> None:
        self.maker, self.source_id, self.clock = maker, source_id, clock
        self.pending = list(hints)
        self.sleeps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        target = self.clock.elapsed + seconds
        while self.pending and self.pending[0] <= target:
            moment = self.pending.pop(0)
            self.clock.at(moment)
            await _hint(self.maker, self.source_id, f"scripted-{moment}")
        self.clock.at(target)


async def _run_inline_quiet(
    maker: Any,
    source_id: uuid.UUID,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    hints: list[int],
) -> tuple[Timeline, list[float]]:
    await _hint(maker, source_id, "scripted-0")
    timeline = Timeline(maker, source_id, clock, hints)
    monkeypatch.setattr(worker, "_quiet_sleep", timeline)
    ran: list[float] = []

    async def run() -> None:
        ran.append(clock.elapsed)

    assert worker.schedule_inline_quiet(source_id, sessionmaker=maker, quiet_seconds=QUIET, run=run)
    await worker._INLINE_QUIET[source_id]
    return timeline, ran


async def test_inline_five_hints_over_a_minute_run_one_sync_ninety_seconds_after_the_last(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, _ = await _seed(maker)

    timeline, ran = await _run_inline_quiet(
        maker, source_id, clock, monkeypatch, hints=[15, 30, 45, 60]
    )

    assert ran == [60 + QUIET]
    assert timeline.sleeps == [QUIET, 60]


async def test_inline_continuous_hints_are_bounded_by_the_maximum_wait(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, _ = await _seed(maker)

    _, ran = await _run_inline_quiet(
        maker, source_id, clock, monkeypatch, hints=list(range(30, 5000, 30))
    )

    assert len(ran) == 1
    assert ran[0] <= worker._QUIET_MAX_WAIT_SECONDS + 1


async def test_inline_keeps_one_pending_task_per_source(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    source_id, _ = await _seed(maker)
    gate = asyncio.Event()

    async def blocked(_: float) -> None:
        await gate.wait()

    monkeypatch.setattr(worker, "_quiet_sleep", blocked)
    run = AsyncMock()
    try:
        assert worker.schedule_inline_quiet(
            source_id, sessionmaker=maker, quiet_seconds=QUIET, run=run
        )
        assert not worker.schedule_inline_quiet(
            source_id, sessionmaker=maker, quiet_seconds=QUIET, run=run
        )
        other = uuid.uuid4()
        assert worker.schedule_inline_quiet(other, sessionmaker=maker, quiet_seconds=QUIET, run=run)
    finally:
        gate.set()
        for key in (source_id, other):
            await worker._INLINE_QUIET[key]
    assert source_id not in worker._INLINE_QUIET, "a finished task frees its slot"
    assert run.await_count == 2


async def test_inline_webhook_defers_instead_of_syncing_immediately(
    client: AsyncClient, maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, token = await _seed(maker)
    scheduled: list[dict[str, Any]] = []

    def fake_schedule(source: uuid.UUID, **kwargs: Any) -> bool:
        scheduled.append({"source": source, **kwargs})
        return True

    monkeypatch.setattr(worker, "schedule_inline_quiet", fake_schedule)
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_source_sync", execute)

    response = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}",
        json={"event": "onshape.model.lifecycle.changed", "messageId": "m1"},
    )

    assert response.status_code == 204
    assert len(scheduled) == 1 and scheduled[0]["source"] == source_id
    assert scheduled[0]["quiet_seconds"] == QUIET
    execute.assert_not_awaited()
    await scheduled[0]["run"]()
    execute.assert_awaited_once()
    assert _call(execute).kwargs["trigger"] is SyncTrigger.WEBHOOK
    assert _call(execute).kwargs["label"] == "webhook"


async def test_a_busy_source_still_surfaces_single_flight_to_arq(
    maker: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing lease semantics: a quiet job that is past its quiet period behaves
    exactly like any other queued sync when the source is busy."""
    from arq import Retry

    source_id, _ = await _seed(maker)
    await _hint(maker, source_id, "a")
    clock.at(QUIET + 1)
    execute = AsyncMock(side_effect=ConnectorError("single_flight_busy", "busy"))
    monkeypatch.setattr(worker, "execute_source_sync", execute)

    with pytest.raises(Retry):
        await worker.sync_source(_ctx(maker), str(source_id), webhook=True, quiet=True)
