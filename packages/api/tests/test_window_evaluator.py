"""SOLUSDEV-321 P2-T3 — the window evaluator (`livebench/findings/window_evaluator.py`): a robot
session's own ticker that judges its parts' samples by event time and raises findings, one
transaction per tick. Real samples, the fake arm (P1-T2) in the real database and the real
`raise_finding`; fakes only for the wall clock (`now`, `sleep`) and, where a test is about the
evaluator rather than a rule, the rules."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from fixtures.fake_arm import DEVICE_REF, FakeArm, seed_fake_arm
from httpx import AsyncClient
from pydantic import ValidationError
from solus_api.checkers.interface import Severity
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.core.config import Settings
from solus_api.graph import kinds
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.codec import to_wire
from solus_api.graph.packet import RecentSample, TelemetryPacket
from solus_api.hardware.config import part_ref
from solus_api.livebench.bench_router import BenchEventRing, ObserverEventIn
from solus_api.livebench.findings.envelopes import EnvelopeCache
from solus_api.livebench.findings.rules import SIGNAL_RULES
from solus_api.livebench.findings.rules.rule_base import Needs, RuleHit, SignalRule, WindowContext
from solus_api.livebench.findings.rules.sensor_rules import StreamGap
from solus_api.livebench.findings.window_evaluator import (
    PRECEDENCE,
    WindowEvaluator,
    coalesce,
    window_ends,
)
from solus_api.livebench.sessions import SessionView
from solus_api.main import create_app
from solus_api.models import Domain, GraphEntity, Project, Source, SourceType
from solus_api.orchestration.config import ObserverConfig
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.services.solus_graph import lock_project
from solus_contracts.relations import MatrixCell
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from test_solus_layer import _project

#: Event time: a recording's epoch, two days before the evaluator's wall clock.
T0: Final = datetime(2026, 10, 25, tzinfo=UTC)
WALL: Final = datetime(2026, 10, 27, 12, tzinfo=UTC)
HZ: Final = 20.0
TRACKING: Final = ("position", "commanded_position", "current")
_LOGGER: Final = "solus.livebench.findings.window_evaluator"
Maker = async_sessionmaker[AsyncSession]


def _event_time(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class _Clock:
    """The evaluator's wall clock, moved by hand or by a test's `sleep`."""

    def __init__(self) -> None:
        self.at = WALL

    def __call__(self) -> datetime:
        return self.at


class _CountingBuffer(InMemoryTelemetryBuffer):
    """The in-memory telemetry buffer, with room for a replayed minute, counting its reads; the
    next `failures` reads find it unreachable."""

    def __init__(self) -> None:
        super().__init__(capacity=4096)
        self.reads = 0
        self.failures = 0

    async def recent(
        self,
        project_id: uuid.UUID,
        entity_id: uuid.UUID,
        signal: str,
        *,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[RecentSample]:
        self.reads += 1
        if self.failures:
            self.failures -= 1
            raise ConnectionError("telemetry buffer unreachable")
        return await super().recent(project_id, entity_id, signal, limit=limit, since=since)


class _Counted:
    """A rule double that counts its runs, spending `cost` seconds of CPU on each — or, `breaks`,
    raising like a rule with a bug."""

    matrix_cell: MatrixCell | None = None
    needs = Needs()

    def __init__(self, rule_id: str, cost: float = 0.0, *, breaks: bool = False) -> None:
        self.rule_id, self.cost, self.breaks, self.runs = rule_id, cost, breaks, 0

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        self.runs += 1
        if self.breaks:
            raise RuntimeError("a rule bug")
        time.sleep(self.cost)
        return []


class _Seen(_Counted):
    """A rule double that keeps every window it is shown and, window by window, each sample shown
    as new: past the window's `judged_through` for its channel."""

    def __init__(self) -> None:
        super().__init__("seen")
        self.windows: list[WindowContext] = []
        self.new: list[datetime] = []
        self.per_window: list[int] = []

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        fresh = [
            sample.timestamp
            for channel, samples in ctx.samples.items()
            for sample in samples
            if (cut := ctx.judged_through.get(channel)) is None or sample.timestamp > cut
        ]
        self.windows.append(ctx)
        self.new.extend(fresh)
        self.per_window.append(len(fresh))
        return []


class _Scripted(_Counted):
    """A rule double whose runs cost `costs` seconds in turn, the last one repeating."""

    def __init__(self, rule_id: str, costs: Sequence[float]) -> None:
        super().__init__(rule_id)
        self.costs = costs

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        self.cost = self.costs[min(self.runs, len(self.costs) - 1)]
        return super().evaluate(ctx)


class _CountingMaker(async_sessionmaker[AsyncSession]):
    """A sessionmaker that counts the sessions it opens and the commits they make."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine, expire_on_commit=False)
        self.opened = 0
        self.commits = 0

    def __call__(self, **local_kw: Any) -> AsyncSession:
        session = super().__call__(**local_kw)
        self.opened += 1
        event.listen(session.sync_session, "after_commit", self._committed)
        return session

    def _committed(self, session: Session) -> None:
        self.commits += 1


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _arm(maker: Maker) -> tuple[uuid.UUID, FakeArm]:
    """A project holding the fake arm: servo n is `arm.parts[n - 1]`, its channels
    `servo<n>.<quantity>`, its current rated 2.0 A (warn 1.6 A), positions in deg."""
    project = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        await db.commit()
    return project, arm


async def _findings(maker: Maker, project: uuid.UUID) -> list[GraphEntity]:
    async with maker() as db:
        rows = await db.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project,
                GraphEntity.kind == kinds.FINDING,
                GraphEntity.deleted_at.is_(None),
            )
            .order_by(GraphEntity.created_at)
        )
        return list(rows)


async def _bare_part(maker: Maker, project: uuid.UUID) -> uuid.UUID:
    """A part with no limits anywhere: no config, definition, scene or baseline."""
    async with maker() as db:
        bare = GraphEntity(
            project_id=project,
            kind=kinds.PART,
            domain=Domain.ELECTRICAL,
            origin="manual",
            name="bare servo",
        )
        db.add(bare)
        await db.commit()
        return bare.id


async def _entity_row(maker: Maker, entity_id: uuid.UUID) -> GraphEntity:
    async with maker() as db:
        row = await db.get(GraphEntity, entity_id)
        assert row is not None
        return row


async def _feed(
    buffer: InMemoryTelemetryBuffer,
    project: uuid.UUID,
    part: uuid.UUID,
    channel: str,
    unit: str | None,
    values: Sequence[float],
    *,
    start: float,
    hz: float = HZ,
) -> None:
    """One sample per value on `channel`, `hz` apart from `start` seconds of event time."""
    for index, value in enumerate(values):
        timestamp = _event_time(start + index / hz)
        await buffer.append(project, part, channel, timestamp, value, unit=unit)


async def _stall(
    buffer: InMemoryTelemetryBuffer,
    project: uuid.UUID,
    arm: FakeArm,
    n: int,
    *,
    start: float,
    seconds: float,
    held: bool = True,
) -> None:
    """Servo `n` drawing 2.4 A against a 40 deg command: held at 10 deg (a stall), or following
    its command (an over-current that is no stall)."""
    count = round(seconds * HZ)
    position = 10.0 if held else 40.0
    units, values = ("deg", "deg", "A"), (position, 40.0, 2.4)
    for quantity, unit, value in zip(TRACKING, units, values, strict=True):
        channel = f"servo{n}.{quantity}"
        await _feed(buffer, project, arm.parts[n - 1], channel, unit, [value] * count, start=start)


def _streams(n: int, *, start: float = 0.0) -> dict[str, datetime]:
    """What a session's tap records of servo `n` streaming its tracking channels from `start`."""
    return {f"servo{n}.{quantity}": _event_time(start) for quantity in TRACKING}


def _session_view(
    project: uuid.UUID,
    arm: FakeArm,
    parts: Mapping[uuid.UUID, Mapping[str, datetime]],
    *,
    owner: uuid.UUID | None = None,
) -> SessionView:
    return SessionView(project, uuid.uuid4(), arm.robot, owner, parts)


def _evaluator(
    maker: Maker,
    buffer: InMemoryTelemetryBuffer,
    *,
    rules: Sequence[SignalRule] = SIGNAL_RULES,
    ring: BenchEventRing | None = None,
    **over: Any,
) -> WindowEvaluator:
    """An evaluator over the real rules, a fresh envelope cache and event ring, on `_Clock`."""
    return WindowEvaluator(
        buffer,
        maker,
        EnvelopeCache(InMemoryCacheStore()),
        rules,
        ring if ring is not None else BenchEventRing(),
        **{"now": _Clock(), **over},
    )


# ---------------------------------------------------------------------------- the nine


async def test_ticker_runs_once_per_second_even_when_stream_is_silent(engine: AsyncEngine) -> None:
    """A silent stream closes no event-time window, so the ticker wakes every `tick_seconds`
    anyway; `stream_gap` tells servo 3's gap once past its timeout (max(3 x 50 ms, 1 s)), once."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer = _CountingBuffer()
    await _feed(buffer, project, servo, "servo3.position", "deg", [10.0] * 20, start=0.0)
    clock, slept, ticked = _Clock(), list[float](), asyncio.Event()

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.at += timedelta(seconds=seconds)
        if len(slept) > 4:  # four ticks have run: park until cancelled
            ticked.set()
            await asyncio.Event().wait()

    view = _session_view(project, arm, {servo: {"servo3.position": _event_time(0)}})
    evaluator = _evaluator(maker, buffer, rules=(StreamGap(),), now=clock, sleep=sleep)
    task = evaluator.start(view)
    await asyncio.wait_for(ticked.wait(), 30)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert slept == [1.0] * 5
    assert buffer.reads == 4  # a read every tick, though only the first found anything
    (gap,) = await _findings(maker, project)
    assert (gap.attrs["rule_id"], gap.attrs["count"]) == ("stream_gap", 1)
    evidence = gap.attrs["evidence"]
    assert evidence["channel"] == "servo3.position"
    assert (evidence["last_seen_seconds"], evidence["timeout"]) == (2.0, 1.0)


async def test_same_subject_hits_coalesce_within_a_tick(engine: AsyncEngine) -> None:
    """Servo 3 stalls over its rating: the stall and the over-rating fold into ONE finding, the
    stall's, `also` naming the other; servo 2's over-current is its own. Every rule is ranked."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo2, servo3 = arm.parts[1], arm.parts[2]
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    await _stall(buffer, project, arm, 2, start=0.0, seconds=1.5, held=False)
    view = _session_view(project, arm, {servo3: _streams(3), servo2: _streams(2)})

    raised = await _evaluator(maker, buffer).tick(view)

    rows = {row.attrs["rule_id"]: row for row in await _findings(maker, project)}
    assert sorted(rows) == ["current_over_rating", "tracking_error_stall"]
    assert sorted(raised) == sorted(row.id for row in rows.values())
    stall, over = rows["tracking_error_stall"], rows["current_over_rating"]
    assert stall.attrs["subjects"][0] == str(servo3)
    assert stall.attrs["evidence"]["also"] == ["current_over_rating"]
    assert over.attrs["subjects"][0] == str(servo2)
    assert "also" not in over.attrs["evidence"]

    part = uuid.uuid4()
    every = [
        (
            part,
            RuleHit(
                rule_id=rule,
                severity=Severity.WARNING,
                headline=rule,
                subjects=(part,),
                evidence={},
            ),
        )
        for rule in reversed(PRECEDENCE)
    ]
    ((_, winner, also),) = coalesce(every)
    assert (winner.rule_id, also) == ("tracking_error_stall", PRECEDENCE[1:])
    assert set(PRECEDENCE) == {rule.rule_id for rule in SIGNAL_RULES}


async def test_on_raised_called_after_commit(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """`on_raised(robot_id, finding_ids)` — the narration's hook — runs after the tick's commit: a
    session of its own already reads every finding it is told of. A hook that fails is logged and
    swallowed, and the tick still returns what it raised."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    heard: list[tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]] = []

    async def on_raised(robot_id: uuid.UUID, finding_ids: list[uuid.UUID]) -> None:
        async with maker() as db:  # its own session: it reads only what is committed
            committed = await db.scalars(
                select(GraphEntity.id).where(GraphEntity.id.in_(finding_ids))
            )
            heard.append((robot_id, finding_ids, list(committed)))
        if len(heard) > 1:
            raise RuntimeError("narration is down")

    view = _session_view(project, arm, {servo: _streams(3)})
    evaluator = _evaluator(maker, buffer, on_raised=on_raised)
    first = await evaluator.tick(view)
    await _stall(buffer, project, arm, 3, start=1.5, seconds=1.0)
    caplog.set_level(logging.ERROR, logger=_LOGGER)
    second = await evaluator.tick(view)

    assert len(first) == 1 and second == first  # the stall, raised again
    assert heard == [(arm.robot, first, first), (arm.robot, first, first)]
    (failed,) = [r for r in caplog.records if "on_raised failed" in r.getMessage()]
    assert str(view.session_id) in failed.getMessage() and failed.exc_info is not None


async def test_wire_events_cannot_carry_finding_id(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """A finding id rides only a ring record the server attached it to: the ingest route's event
    model forbids the key (the whole batch is refused, 422), and the events route shows no id but
    the server's."""
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = (await create_project(client, alice_headers, team["id"]))["id"]
    url = f"/api/v1/projects/{project}/bench"
    marker = {
        "kind": "threshold_breach",
        "device_id": "usb:ARM/3",
        "signal": "servo3.current",
        "at": T0.isoformat(),
    }
    packet = to_wire(
        TelemetryPacket(device_id="usb:ARM/3", timestamp=T0, values={"servo3.current": 2.4})
    )

    forged = {**marker, "finding_id": str(uuid.uuid4())}
    refused = await client.post(
        f"{url}/telemetry", headers=alice_headers, json={"packets": [packet], "events": [forged]}
    )
    honest = await client.post(
        f"{url}/telemetry", headers=alice_headers, json={"packets": [packet], "events": [marker]}
    )
    attached = uuid.uuid4()
    ring: BenchEventRing = app.state.bench_events
    ring.append(uuid.UUID(project), ObserverEventIn.model_validate(marker), finding_id=attached)
    events = (await client.get(f"{url}/events", headers=alice_headers)).json()["data"]

    assert refused.status_code == 422
    assert honest.status_code == 200, honest.text
    assert [record.get("finding_id") for record in events] == [None, str(attached)]


async def test_cpu_budget_skips_and_logs(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Rules run until a window has spent its CPU budget (measured with `time.perf_counter`); the
    rest are skipped and the tick says how many, and what the budget was, in ONE log line. The
    next tick starts with a fresh budget — and with the first rule skipped (m3)."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.0)
    slow = [_Counted(f"slow {index}", cost=0.03) for index in range(3)]
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    view = _session_view(project, arm, {servo: _streams(3)})
    evaluator = _evaluator(maker, buffer, rules=slow, cpu_budget_ms=20, cpu_budget_ms_per_part=0)

    for _ in slow:
        await evaluator.tick(view)
    await _evaluator(maker, buffer, rules=slow, cpu_budget_ms=1000).tick(view)

    assert [rule.runs for rule in slow] == [2, 2, 2]  # one a tick, each in turn; then all
    lines = [r.getMessage() for r in caplog.records if "cpu budget" in r.getMessage()]
    assert len(lines) == 3  # one a tick, none for the roomy one
    for line in lines:
        assert "budget of 20 ms: skipped 2 rule runs" in line and str(view.session_id) in line


async def test_budget_scales_with_the_sessions_parts(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """A window's budget is `cpu_budget_ms` (20 ms) or, when more, `cpu_budget_ms_per_part` (10 ms)
    for each part the session streams: six parts get 60 ms, where the floor would cut their rules
    short; one part gets the floor; with no share per part every session does. The over-budget
    line names the budget the window had."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    buffer = _CountingBuffer()
    six = _session_view(project, arm, {p: _streams(n) for n, p in enumerate(arm.parts, start=1)})
    one = _session_view(project, arm, {arm.parts[2]: _streams(3)})
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    async def judged(
        view: SessionView, count: int, cost: float, **over: Any
    ) -> tuple[list[int], list[str]]:
        """One tick of `count` rules costing `cost` seconds a run: each one's runs, and the
        over-budget lines."""
        caplog.clear()
        rules = [_Counted(f"rule {index}", cost=cost) for index in range(count)]
        await _evaluator(maker, buffer, rules=rules, **over).tick(view)
        said = [record.getMessage() for record in caplog.records]
        return [rule.runs for rule in rules], [line for line in said if "cpu budget" in line]

    runs, lines = await judged(six, 1, 0.007)  # six runs of 7 ms: 35 ms pass before the last
    assert (runs, lines) == ([6], [])
    runs, lines = await judged(six, 2, 0.08)  # 80 ms is more than any budget here
    assert runs == [1, 0] and "budget of 60 ms: skipped 11 rule runs" in lines[0]
    runs, lines = await judged(six, 1, 0.007, cpu_budget_ms_per_part=0)
    assert runs == [3] and "budget of 20 ms: skipped 3 rule runs" in lines[0]
    runs, lines = await judged(one, 6, 0.007)  # a part's 10 ms is under the floor
    assert runs == [1, 1, 1, 0, 0, 0] and "budget of 20 ms: skipped 3 rule runs" in lines[0]


def test_models_yaml_carries_the_observer_section() -> None:
    """`observer:` ships the spec's 20 ms floor and 10 ms a part, and is bounded like its siblings:
    a floor above zero, a per-part share not below it, no unknown knob."""
    config = default_orchestration_config()
    observer = config.observer

    assert "observer" in config.model_fields_set  # stated in the yaml, not the model's default
    assert (observer.cpu_budget_ms, observer.cpu_budget_ms_per_part) == (20, 10)
    for bad in ({"cpu_budget_ms": 0}, {"cpu_budget_ms_per_part": -1}, {"unknown_knob": 1}):
        with pytest.raises(ValidationError):
            ObserverConfig.model_validate(bad)


async def test_the_apps_evaluator_takes_its_budget_from_the_observer_section(
    settings: Settings, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`create_app` reads the `observer:` section once and hands both its knobs to the evaluator
    it builds for each robot session."""
    observer = ObserverConfig(cpu_budget_ms=35, cpu_budget_ms_per_part=7)
    changed = default_orchestration_config().model_copy(update={"observer": observer})
    monkeypatch.setattr("solus_api.main.default_orchestration_config", lambda: changed)
    built = create_app(settings=settings, engine=engine)
    view = SessionView(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), None, {})

    evaluator = built.state.bench_sessions._evaluator_factory(view)

    assert (evaluator._budget_ms, evaluator._budget_per_part_ms) == (35, 7)


async def test_one_session_one_node_count_rising(engine: AsyncEngine) -> None:
    """A stall that goes on is ONE finding per session (`bucket` = the session) whose count rises
    with every tick that still shows it; another session on the same robot, starting later, opens
    a node of its own and never judges the first one's samples."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer = _CountingBuffer()
    view = _session_view(project, arm, {servo: _streams(3)})
    evaluator = _evaluator(maker, buffer)
    counts = []
    for start, seconds in ((0.0, 1.5), (1.5, 1.0), (2.5, 1.0)):
        await _stall(buffer, project, arm, 3, start=start, seconds=seconds)
        await evaluator.tick(view)
        (stall,) = await _findings(maker, project)
        counts.append(stall.attrs["count"])

    await _stall(buffer, project, arm, 3, start=3.5, seconds=1.5)
    later = _session_view(project, arm, {servo: _streams(3, start=3.5)})
    await _evaluator(maker, buffer).tick(later)

    assert counts == [1, 2, 3]
    rows = await _findings(maker, project)
    assert [row.attrs["rule_id"] for row in rows] == ["tracking_error_stall"] * 2
    sessions = {row.attrs["evidence"]["session_id"]: row.attrs["count"] for row in rows}
    assert sessions == {str(view.session_id): 3, str(later.session_id): 1}
    assert {row.attrs["evidence"]["robot_id"] for row in rows} == {str(arm.robot)}


async def test_markers_carry_finding_id(engine: AsyncEngine) -> None:
    """A finding's first raise in a session leaves a marker on each channel its part streams — on
    the part's device, at that channel's newest event time — its id attached by the server; the
    marker is otherwise a wire event. Raising it again adds none."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer, ring = _CountingBuffer(), BenchEventRing()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    view = _session_view(project, arm, {servo: _streams(3)})
    evaluator = _evaluator(maker, buffer, ring=ring)

    (stall,) = await evaluator.tick(view)
    markers = ring.recent(project, 100)
    await _stall(buffer, project, arm, 3, start=1.5, seconds=1.0)
    again = await evaluator.tick(view)

    assert again == [stall]
    assert ring.recent(project, 100) == markers
    assert sorted(m["signal"] for m in markers) == sorted(f"servo3.{q}" for q in TRACKING)
    assert {m["finding_id"] for m in markers} == {str(stall)}
    assert {m["device_id"] for m in markers} == {part_ref(DEVICE_REF, "3")}
    assert {datetime.fromisoformat(m["at"]) for m in markers} == {_event_time(29 / HZ)}
    for marker in markers:
        wire = {key: value for key, value in marker.items() if key != "finding_id"}
        assert ObserverEventIn.model_validate(wire).kind == "threshold_breach"


async def test_findings_raised_in_one_transaction_per_tick(engine: AsyncEngine) -> None:
    """Every finding a tick raises — servo 3's stall and servo 2's over-current here — is raised in
    ONE session with ONE commit (`raise_finding` takes the project lock once a tick); a tick that
    raises nothing commits nothing."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    await _stall(buffer, project, arm, 2, start=0.0, seconds=1.5, held=False)
    counting = _CountingMaker(engine)
    view = _session_view(project, arm, {arm.parts[2]: _streams(3), arm.parts[1]: _streams(2)})
    evaluator = _evaluator(counting, buffer)

    raised = await evaluator.tick(view)
    after_first = (counting.opened, counting.commits)
    quiet = await evaluator.tick(view)

    assert len(raised) == 2 and after_first == (1, 1)
    assert quiet == [] and (counting.opened, counting.commits) == (2, 1)


async def test_cursor_is_event_time_so_fast_replay_is_exact(engine: AsyncEngine) -> None:
    """A replayed minute, stamped two days before the wall clock, lands before the first tick: the
    event-time cursor judges every sample once (the one at it, which `since` returns again, is
    dropped) in sixty one-second windows, as real time would have."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer, seen = _CountingBuffer(), _Seen()
    minute = [float(index % 7) for index in range(1200)]
    await _feed(buffer, project, servo, "servo3.current", "A", minute, start=0.0)
    view = _session_view(project, arm, {servo: {"servo3.current": _event_time(0)}})
    clock = _Clock()
    evaluator = _evaluator(maker, buffer, rules=(seen,), now=clock)

    await evaluator.tick(view)
    replayed = list(seen.per_window)
    clock.at += timedelta(seconds=1)
    await evaluator.tick(view)  # nothing new
    await _feed(buffer, project, servo, "servo3.current", "A", [1.0] * 20, start=60.0)
    await evaluator.tick(view)

    assert len(replayed) == 60 and sum(replayed) == 1200 and max(replayed) <= 21
    assert seen.per_window[60:] == [0, 20]
    assert seen.new == [_event_time(index / HZ) for index in range(1220)]
    # the quiet tick read the sample at the cursor again and dropped it: its history gained
    # nothing, and the channel's last arrival is still the replay's tick
    last, quiet = seen.windows[59], seen.windows[60]
    assert len(quiet.samples["servo3.current"]) == len(last.samples["servo3.current"])
    assert quiet.last_sample_at["servo3.current"] == WALL


# ---------------------------------------------------------------------------- beyond the nine


def test_window_ends_cut_only_the_windows_that_hold_a_sample() -> None:
    """`window_ends`, pure (m7): one far-off timestamp is one more window, never millions; a
    frontier past every new sample (a lagging channel, a parked cursor) is one window at the
    newest; a replayed minute is sixty."""
    second = [_event_time(index / HZ) for index in range(20)]
    outlier = _event_time(365 * 86400.0)
    assert window_ends(T0, [*second, outlier], 1.0) == [_event_time(1.0), outlier]
    assert window_ends(_event_time(10.0), second, 1.0) == [second[-1]]
    minute = [_event_time(index / HZ) for index in range(1200)]
    assert len(window_ends(T0, minute, 1.0)) == 60


async def test_future_dated_sample_never_moves_the_cursor(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """S1/I1: a sample dated over MAX_FUTURE_SKEW_SECONDS past the wall clock is dropped before
    it moves a cursor, the frontier or a rule — mid-stream, or as a channel's first packet (the
    tap's `began`) — so the next in-order samples are judged; said once per channel."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo, ahead = arm.parts[2], WALL + timedelta(days=365)
    buffer, seen = _CountingBuffer(), _Seen()
    await _feed(buffer, project, servo, "servo3.current", "A", [1.0] * 20, start=0.0)
    await buffer.append(project, servo, "servo3.current", ahead, 9.0, unit="A")
    await _feed(buffer, project, servo, "servo3.current", "A", [1.0] * 20, start=1.0)
    await buffer.append(project, servo, "servo3.voltage", ahead, 9.0, unit="V")  # its 1st packet
    await _feed(buffer, project, servo, "servo3.voltage", "V", [7.0] * 40, start=0.0)
    streams = {"servo3.current": _event_time(0), "servo3.voltage": ahead}
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    evaluator = _evaluator(maker, buffer, rules=(seen,))
    view = _session_view(project, arm, {servo: streams})

    await evaluator.tick(view)
    await _feed(buffer, project, servo, "servo3.current", "A", [1.0] * 20, start=2.0)
    await evaluator.tick(view)

    judged = [*range(60), *range(40)]  # current through 2.95 s, voltage through 1.95 s
    assert sorted(seen.new) == sorted(_event_time(index / HZ) for index in judged)
    assert len(seen.per_window) == 3  # the first two seconds, then the third
    dropped = [r for r in caplog.records if "dated in the future" in r.getMessage()]
    assert len(dropped) == 2  # once per channel, though read again every tick


async def test_every_rule_runs_within_two_ticks_when_half_the_rules_fit(
    engine: AsyncEngine,
) -> None:
    """m3: past the CPU budget the remaining rules are skipped and the next tick starts with the
    first of them, so when at least half the rules fit (two of four here) every rule runs in any
    two consecutive ticks — no tail (`stream_gap` among it) starves for the session."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.0)
    rules = [_Counted(f"rule {index}", cost=0.012) for index in range(4)]
    evaluator = _evaluator(maker, buffer, rules=rules, cpu_budget_ms=20, cpu_budget_ms_per_part=0)
    view = _session_view(project, arm, {arm.parts[2]: _streams(3)})

    ticks: list[list[int]] = []  # each tick's runs, by rule
    for _ in range(4):
        before = [rule.runs for rule in rules]
        await evaluator.tick(view)
        ticks.append([rule.runs - was for rule, was in zip(rules, before, strict=True)])

    assert all(sum(tick) < len(rules) for tick in ticks)  # the budget bound every tick
    for first, second in itertools.pairwise(ticks):
        assert all(a + b >= 1 for a, b in zip(first, second, strict=True)), ticks


async def test_the_next_tick_starts_at_the_rule_the_budget_cut_short(engine: AsyncEngine) -> None:
    """With several parts the budget can fall between two parts of one rule: that rule is skipped
    and the next tick starts there, so it runs for every part. A rule that alone outspends the
    budget runs for the parts that fit, and the rotation steps past it, a rule a tick."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    buffer = _CountingBuffer()
    six = _session_view(project, arm, {p: _streams(n) for n, p in enumerate(arm.parts, start=1)})
    rules = [_Counted(f"rule {index}", cost=0.004) for index in range(5)]  # 24 ms over six parts
    evaluator = _evaluator(maker, buffer, rules=rules, cpu_budget_ms=60, cpu_budget_ms_per_part=0)

    await evaluator.tick(six)
    first = [rule.runs for rule in rules]
    await evaluator.tick(six)
    second = [rule.runs for rule in rules]

    assert first[:2] == [6, 6] and 0 < first[2] < 6 and first[3:] == [0, 0]  # rule 2 cut short
    assert second[:2] == [6, 6] and second[2] == first[2] + 6  # the next tick starts with it

    slow = [_Counted(f"slow {index}", cost=0.03) for index in range(3)]  # one run outspends 20 ms
    stepping = _evaluator(maker, buffer, rules=slow, cpu_budget_ms=20, cpu_budget_ms_per_part=0)
    for _ in slow:
        await stepping.tick(six)

    assert [rule.runs for rule in slow] == [1, 1, 1]  # each turn, the next rule gets its run


async def test_a_tick_of_several_windows_resumes_at_the_first_rule_any_of_them_skipped(
    engine: AsyncEngine,
) -> None:
    """A tick that judges two windows (two seconds of samples) hands its next tick the fewest
    rules a window ran whole: rule 0 outspends the first window's budget so the others are
    skipped there, the second window runs all three, and the next tick still starts at rule 1."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=2.0)
    spent = 0.03  # more than the whole 20 ms budget; 0.0 costs nothing
    rules = [
        _Scripted("rule 0", [spent, 0.0, spent]),
        _Scripted("rule 1", [0.0, spent]),
        _Scripted("rule 2", [0.0, spent]),
    ]
    evaluator = _evaluator(maker, buffer, rules=rules, cpu_budget_ms=20, cpu_budget_ms_per_part=0)
    view = _session_view(project, arm, {arm.parts[2]: _streams(3)})

    await evaluator.tick(view)  # two windows: rule 0 alone in the first, all three in the second
    await evaluator.tick(view)  # a quiet tick, one window: its first rule spends the budget

    assert [rule.runs for rule in rules] == [2, 2, 1]  # rule 1 was that first rule


async def test_a_fast_channel_keeps_thirty_seconds_of_history(engine: AsyncEngine) -> None:
    """Contract item 1 at 50 Hz: between ticks a channel keeps its last TREND_HORIZON_SECONDS —
    1501 samples, past the 1024 the history ceiling first held (m5)."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer, seen = _CountingBuffer(), _Seen()
    await _feed(buffer, project, servo, "servo3.current", "A", [1.0] * 2000, start=0.0, hz=50.0)
    view = _session_view(project, arm, {servo: {"servo3.current": _event_time(0)}})
    evaluator = _evaluator(maker, buffer, rules=(seen,))

    await evaluator.tick(view)
    await evaluator.tick(view)  # a quiet tick's one window shows what the history kept

    kept = seen.windows[-1].samples["servo3.current"]
    assert (len(kept), (kept[-1].timestamp - kept[0].timestamp).total_seconds()) == (1501, 30.0)


async def test_a_finding_carries_its_blame_causes_session_and_code_source(
    engine: AsyncEngine,
) -> None:
    """What the pane and the narration read off a finding: blame-ordered `subjects`, the causes,
    the bound's source, the session's robot and id, and the code site, its `source_id` from the
    code entity's own row (the rules leave it empty)."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    async with maker() as db:
        home = await db.get(Project, project)
        code = await db.get(GraphEntity, arm.code_file)
        assert home is not None and code is not None
        source = Source(project_id=project, team_id=home.team_id, type=SourceType.LOCAL, name="fw")
        db.add(source)
        await db.flush()
        code.source_id = source.id
        await db.commit()
        source_id = source.id
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    view = _session_view(project, arm, {arm.parts[2]: _streams(3)})

    await _evaluator(maker, buffer).tick(view)

    (stall,) = await _findings(maker, project)
    assert stall.attrs["subjects"] == [str(arm.parts[2]), str(arm.bus), str(arm.brain)]
    assert (stall.attrs["matrix_cell"], stall.domain) == ("software->mechanical", Domain.ELECTRICAL)
    evidence = stall.attrs["evidence"]
    assert (evidence["robot_id"], evidence["session_id"]) == (str(arm.robot), str(view.session_id))
    assert evidence["bounds_source"] == "config"
    assert evidence["code_site"] == {
        "entity_id": str(arm.code_file),
        "source_id": str(source_id),
        "path": "fw/fake_arm.ino",
        "line": 13,
    }
    causes = evidence["causes"]
    assert [c["kind"] for c in causes] == ["mechanical_load", "software_command", "actuator"]
    assert all(cause["for"] for cause in causes)


async def test_unmet_needs_record_missing_signals_once_and_raise_nothing(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review focus 2: a part with no limits anywhere stalls; nothing is raised, and the robot's
    `missing_signals` lists each rule's unmet needs (`<part>: <need>`, sorted, deduplicated),
    written once under the project lock (m1); the ticker goes on."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    bare = await _bare_part(maker, project)
    buffer = _CountingBuffer()
    for quantity, value in zip(TRACKING, (10.0, 40.0, 2.4), strict=True):
        await _feed(buffer, project, bare, f"bare.{quantity}", None, [value] * 30, start=0.0)
    view = _session_view(project, arm, {bare: {f"bare.{q}": _event_time(0) for q in TRACKING}})
    evaluator = _evaluator(maker, buffer)
    version = (await _entity_row(maker, arm.robot)).version
    locked: list[uuid.UUID] = []

    async def lock(db: AsyncSession, project_id: uuid.UUID) -> None:
        locked.append(project_id)
        await lock_project(db, project_id)

    monkeypatch.setattr("solus_api.livebench.findings.window_evaluator.lock_project", lock)

    first = await evaluator.tick(view)
    robot = await _entity_row(maker, arm.robot)
    second = await evaluator.tick(view)
    after = await _entity_row(maker, arm.robot)

    assert first == second == [] and await _findings(maker, project) == []
    assert locked == [project]  # the one write held the project lock
    missing = robot.attrs["missing_signals"]
    assert missing == sorted(set(missing))
    assert all(line.startswith("bare servo: ") for line in missing)
    assert (
        "bare servo: current.warn (set it in the part's limits (`current_a`, `stall_current_a`) "
        "in the part's config or its library definition)"
    ) in missing
    assert {"bare servo: voltage channel", "bare servo: mates_with relation"} <= set(missing)
    assert robot.attrs["fake"] is True  # the robot's other attrs stay
    assert (robot.version, after.version) == (version + 1, version + 1)
    assert after.attrs["missing_signals"] == missing


async def test_a_part_is_reassessed_when_its_channels_grow(engine: AsyncEngine) -> None:
    """m4: a config-less part streams its position first and its current from a later packet.
    What it lacks is reassessed when its channels grow — `missing_signals` drops "current
    channel" — and the list is written only then, never once per tick."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    bare = await _bare_part(maker, project)
    buffer = _CountingBuffer()
    await _feed(buffer, project, bare, "bare.position", None, [10.0] * 20, start=0.0)
    streams = {"bare.position": _event_time(0)}
    view = _session_view(project, arm, {bare: streams})
    evaluator = _evaluator(maker, buffer)

    await evaluator.tick(view)
    first = await _entity_row(maker, arm.robot)
    await _feed(buffer, project, bare, "bare.current", None, [0.5] * 20, start=1.0)
    streams["bare.current"] = _event_time(1.0)  # the session's tap records the new channel
    await evaluator.tick(view)
    grown = await _entity_row(maker, arm.robot)
    await evaluator.tick(view)  # nothing grew
    after = await _entity_row(maker, arm.robot)

    assert "bare servo: current channel" in first.attrs["missing_signals"]
    assert "bare servo: current channel" not in grown.attrs["missing_signals"]
    assert (grown.version, after.version) == (first.version + 1, first.version + 1)


async def test_a_failing_tick_or_rule_is_logged_and_observation_goes_on(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """A tick that raises is logged with its session and project, and the next tick runs; a rule
    that raises is logged once a session and judges nothing, while the others still judge."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer = _CountingBuffer()
    buffer.failures = 1  # the first tick finds the buffer unreachable
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    broken = _Counted("broken", breaks=True)
    clock, slept, ticked = _Clock(), list[float](), asyncio.Event()

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.at += timedelta(seconds=seconds)
        if len(slept) > 3:  # three ticks have run: park until cancelled
            ticked.set()
            await asyncio.Event().wait()

    caplog.set_level(logging.WARNING, logger=_LOGGER)
    view = _session_view(project, arm, {servo: _streams(3)})
    rules = (broken, *SIGNAL_RULES)
    task = _evaluator(maker, buffer, rules=rules, now=clock, sleep=sleep).start(view)
    await asyncio.wait_for(ticked.wait(), 30)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    (stall,) = await _findings(maker, project)
    assert stall.attrs["rule_id"] == "tracking_error_stall"
    assert broken.runs == 2  # the second and third ticks
    (tick_failed,) = [r for r in caplog.records if "tick failed" in r.getMessage()]
    assert str(view.session_id) in tick_failed.getMessage()
    assert str(project) in tick_failed.getMessage() and tick_failed.exc_info is not None
    (rule_failed,) = [r for r in caplog.records if "rule failed" in r.getMessage()]
    assert "broken" in rule_failed.getMessage() and rule_failed.exc_info is not None


async def test_findings_from_a_sim_session_carry_evidence_sim_true(engine: AsyncEngine) -> None:
    """SOLUSDEV-322 P5-T3: a sim session's view says so, and every finding its tick raises carries
    `evidence.sim = true` — same rules, same `source="observer"`, same session bucket."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo3 = arm.parts[2]
    buffer = _CountingBuffer()
    await _stall(buffer, project, arm, 3, start=0.0, seconds=1.5)
    view = SessionView(project, uuid.uuid4(), arm.robot, None, {servo3: _streams(3)}, sim=True)

    raised = await _evaluator(maker, buffer).tick(view)

    (stall,) = await _findings(maker, project)
    assert raised == [stall.id]
    assert (stall.attrs["source"], stall.attrs["evidence"]["sim"]) == ("observer", True)
    assert stall.attrs["evidence"]["robot_id"] == str(arm.robot)

    real = _session_view(project, arm, {servo3: _streams(3)})
    assert real.sim is False
