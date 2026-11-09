"""SOLUSDEV-321 P2-T4 — the fake arm's stall, replayed through the real path.

`livebench/tests/fixtures/serial_fake_arm_stall.json` (one synthetic six-servo arm, a minute at
20 Hz) goes in at `POST /bench/sessions` (provider `replay`) and comes out as findings:

    open_replay -> the lb06 driver -> part routing -> the session tap -> the telemetry buffer
    -> the window evaluator (ticked here by hand) -> raise_finding

Two things are not the production ones. The transport is gated: it hands over only the frames a
test has released, so a test releases a second of the recording, ticks the evaluator and releases
the next, as real time would. (The buffer keeps 512 samples a channel, about 25 s at 20 Hz; one
dump of the minute would lose its first 35 s before a tick read them.) And the evaluator's CPU
budget is roomy, so which rules ran in a window never depends on the machine; what the rules
cost is measured instead (`test_sixty_seconds_is_one_node_count_rising` logs it). The exception is
`test_five_distinct_findings_inside_40s`: it runs under the shipped budget (20 ms, and 10 ms a
part: 60 ms for this arm) and allows each deadline a tick of slack. "Within 2 s" is event time
throughout: the recording's own clock, never the wall's.
"""

import asyncio
import importlib.util
import json
import logging
import statistics
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from fixtures import fake_arm
from fixtures.fake_arm import DEVICE_REF, FakeArm, seed_fake_arm
from httpx import AsyncClient
from livebench.hardware import replay as replay_module
from livebench.hardware.channel import Channel, Frame, Opener
from livebench.hardware.replay import Recording, load_recording
from solus_api.checkers.interface import Severity
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.graph import kinds
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.resolver import CachingEntityResolver, DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.bench_router import BenchEventRing
from solus_api.livebench.findings.envelopes import EnvelopeCache
from solus_api.livebench.findings.rules import SIGNAL_RULES
from solus_api.livebench.findings.rules.rule_base import RuleHit, SignalRule, WindowContext
from solus_api.livebench.findings.window_evaluator import WindowEvaluator
from solus_api.livebench.sessions import SessionManager, SessionView
from solus_api.models import GraphEntity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_bench_router import FakeLocal, TapConn
from test_vendor_hygiene_api import SRC_ROOT, VENDOR_WORDS

logger = logging.getLogger("solus.tests.stall_replay")

REPO: Final = Path(__file__).resolve().parents[3]
FIXTURES: Final = REPO / "livebench" / "tests" / "fixtures"
GENERATOR: Final = FIXTURES / "make_fake_arm_stall.py"
RECORDING: Final = "serial_fake_arm_stall.json"
#: What the route tests put in a replay root of their own: a file the double runner never reads.
CAPTURE: Final = "capture.json"
#: The recording's event clock, and the wall clock the evaluator is given: long after it.
EPOCH: Final = datetime(2026, 10, 25, tzinfo=UTC)
WALL: Final = EPOCH + timedelta(days=2)
#: One line of the recording carries every servo; routing splits it into one packet a part.
PARTS: Final = 6
#: By which second of the recording (the samples before it consumed) each condition is first told,
#: against the scenario at a roomy CPU budget: the stall and the bus's sag once the stall is a
#: second old, the heat's two predictions once the runaway is steep enough, the frozen position a
#: second after it freezes, servo 2's stall a second after its onset.
TOLD_BY: Final = {
    ("tracking_error_stall", "servo 3"): 7,
    ("rail_sag_correlated", "bus"): 7,
    ("time_to_limit", "servo 3"): 20,
    ("temp_trend_to_limit", "servo 3"): 22,
    ("sensor_frozen", "servo 5"): 32,
    ("tracking_error_stall", "servo 2"): 42,
}
#: What the evaluator is given besides its clock: a roomy CPU budget, unless a test parametrises
#: `replay` with other arguments for it (`{}`: the shipped budget).
ROOMY: Final = {"cpu_budget_ms": 60_000}
Maker = async_sessionmaker[AsyncSession]


# ---------------------------------------------------------------------------- the gated transport


class _Gate:
    """How many of the recording's frames the transport may hand over so far."""

    def __init__(self) -> None:
        self.allowed = 0
        self.taken = 0

    def take(self) -> bool:
        if self.taken >= self.allowed:
            return False
        self.taken += 1
        return True


class _PacedChannel:
    """The real replay channel behind a gate: only the frames a test has released, and a quiet
    link's silence in between. Pacing, nothing else: every frame is the recording's own."""

    def __init__(self, inner: Channel, gate: _Gate) -> None:
        self.kind, self.identity = inner.kind, inner.identity
        self._inner, self._gate = inner, gate

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        if not self._gate.take():
            time.sleep(0.002)
            return None
        return self._inner.recv(max_bytes)

    def send(self, frame: Frame) -> None:
        self._inner.send(frame)

    def flush_input(self) -> None:
        self._inner.flush_input()

    def close(self) -> None:
        self._inner.close()


def _gate_the_transport(monkeypatch: pytest.MonkeyPatch, gate: _Gate) -> None:
    """`livebench.local.open_replay` reads `replay_opener` when it opens: put the gate behind it."""
    real = replay_module.replay_opener

    def gated(recording: Recording, *, realtime: bool = False) -> Opener:
        opener = real(recording, realtime=realtime)
        return lambda binding, params: _PacedChannel(opener(binding, params), gate)

    monkeypatch.setattr(replay_module, "replay_opener", gated)


# ---------------------------------------------------------------------------- the evaluator


class _Clock:
    """The evaluator's wall clock, moved by the test: a second a tick."""

    def __init__(self) -> None:
        self.at = WALL

    def __call__(self) -> datetime:
        return self.at


class _Stopwatch:
    """A rule that times the real one: `spent` is the seconds its `evaluate` has taken."""

    def __init__(self, rule: SignalRule) -> None:
        self._rule = rule
        self.rule_id, self.matrix_cell, self.needs = rule.rule_id, rule.matrix_cell, rule.needs
        self.spent = 0.0

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return self._rule.severity(evidence)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        started = time.perf_counter()
        try:
            return self._rule.evaluate(ctx)
        finally:
            self.spent += time.perf_counter() - started


class _Parked:
    """Stands in for the session's own ticker, which would tick by the wall clock: it keeps the
    view the manager built (the robot and owner the replay opener passed) and idles."""

    def __init__(self, views: list[SessionView]) -> None:
        self._views = views

    def start(self, view: SessionView) -> asyncio.Task[None]:
        self._views.append(view)
        return asyncio.create_task(asyncio.sleep(3600))


@dataclass
class _Replay:
    """A paced replay into a project's fake arm, and an evaluator the test ticks by hand."""

    client: AsyncClient
    headers: dict[str, str]
    project: uuid.UUID
    arm: FakeArm
    maker: Maker
    manager: SessionManager
    gate: _Gate
    session_id: uuid.UUID
    view: SessionView
    evaluator: WindowEvaluator
    clock: _Clock
    watches: list[_Stopwatch]
    frame_times: list[float]
    second: int = 0
    window_ms: list[float] = field(default_factory=list)
    #: (rule id, who it is about) -> the second of the recording consumed when it was first told
    first_raised: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def names(self) -> dict[uuid.UUID, str]:
        arm = self.arm
        parts = {part: f"servo {n}" for n, part in enumerate(arm.parts, start=1)}
        return {arm.bus: "bus", arm.brain: "brain", arm.robot: "robot", **parts}

    def counts(self) -> dict[str, int]:
        return self.manager.get(self.project, self.session_id).counts

    def who(self, finding: GraphEntity) -> str:
        return self.names[uuid.UUID(finding.attrs["subjects"][0])]

    async def advance_to(self, second: int) -> list[uuid.UUID]:
        """Release the recording up to `second` seconds of its own time, one second and one tick
        at a time: wait for the session to ingest each second, then tick. The last tick's ids."""
        raised: list[uuid.UUID] = []
        for target in range(self.second + 1, second + 1):
            released = sum(1 for at in self.frame_times if at < target)
            self.gate.allowed = released
            await self._ingested(released * PARTS)
            self.clock.at += timedelta(seconds=1)
            raised = await self.evaluator.tick(self.view)
            self.window_ms.append(1000 * sum(watch.spent for watch in self.watches))
            for watch in self.watches:
                watch.spent = 0.0
            for finding in await self.findings():
                self.first_raised.setdefault((finding.attrs["rule_id"], self.who(finding)), target)
        self.second = max(self.second, second)
        return raised

    async def _ingested(self, packets: int) -> None:
        deadline = time.monotonic() + 15
        while (counts := self.counts())["ingested"] < packets:
            if time.monotonic() > deadline:
                pytest.fail(f"the session ingested {counts['ingested']} of {packets}: {counts}")
            await asyncio.sleep(0.005)

    async def findings(self) -> list[GraphEntity]:
        async with self.maker() as db:
            rows = await db.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == self.project,
                    GraphEntity.kind == kinds.FINDING,
                    GraphEntity.deleted_at.is_(None),
                )
                .order_by(GraphEntity.created_at)
            )
            return list(rows)


def _told_late(
    replay: _Replay, keys: Iterable[tuple[str, str]], slack: int = 0
) -> dict[tuple[str, str], tuple[int, int]]:
    """The conditions told more than `slack` ticks after their deadline in `TOLD_BY`, as (second
    told, deadline)."""
    return {
        key: (replay.first_raised[key], TOLD_BY[key])
        for key in keys
        if replay.first_raised[key] > TOLD_BY[key] + slack
    }


async def _arm_in_a_project(
    client: AsyncClient, headers: dict[str, str], maker: Maker, *, team: str = "Robotics Team"
) -> tuple[uuid.UUID, FakeArm]:
    await me(client, headers)
    made = await create_team(client, headers, name=team)
    project = uuid.UUID((await create_project(client, headers, made["id"]))["id"])
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        await db.commit()
    return project, arm


def _replay_body(robot: uuid.UUID, recording: str, **over: Any) -> dict[str, Any]:
    config = {
        "provider": "replay",
        "recording": recording,
        "driver_id": "lb06",
        "robot_entity_id": str(robot),
        "realtime": False,
        **over,
    }
    return {"mode": "real", "config": config}


@pytest.fixture
async def replay(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> AsyncIterator[_Replay]:
    """The fake arm in a project, its stall started as a paced replay through the route. The
    evaluator's budget is `ROOMY` unless the test parametrises this fixture with its own."""
    assert app.state.bench_local is not None, "livebench is not installed"
    maker: Maker = async_sessionmaker(engine, expire_on_commit=False)
    project, arm = await _arm_in_a_project(client, alice_headers, maker)
    buffer = InMemoryTelemetryBuffer()  # the server's own: 512 samples a channel
    plumbing = TelemetryPlumbing(buffer, CachingEntityResolver(DbEntityResolver(maker)))
    views: list[SessionView] = []
    manager = SessionManager(plumbing, evaluator_factory=lambda view: _Parked(views))
    app.state.bench_sessions = manager
    app.state.settings.bench_replay_root = FIXTURES
    gate = _Gate()
    _gate_the_transport(monkeypatch, gate)

    started = await client.post(
        f"/api/v1/projects/{project}/bench/sessions",
        headers=alice_headers,
        json=_replay_body(arm.robot, RECORDING),
    )
    assert started.status_code == 201, started.text
    watches = [_Stopwatch(rule) for rule in SIGNAL_RULES]
    clock = _Clock()
    evaluator = WindowEvaluator(
        buffer,
        maker,
        EnvelopeCache(InMemoryCacheStore()),
        watches,
        BenchEventRing(),
        now=clock,
        **getattr(request, "param", ROOMY),
    )
    (view,) = views
    run = _Replay(
        client=client,
        headers=alice_headers,
        project=project,
        arm=arm,
        maker=maker,
        manager=manager,
        gate=gate,
        session_id=uuid.UUID(started.json()["data"]["id"]),
        view=view,
        evaluator=evaluator,
        clock=clock,
        watches=watches,
        frame_times=[frame.at_s for frame in load_recording(FIXTURES / RECORDING).frames],
    )
    yield run
    await manager.aclose_all()


# ---------------------------------------------------------------------------- the stall


async def test_replayed_stall_raises_one_finding_within_2s_with_blame_and_causes(
    replay: _Replay,
) -> None:
    arm = replay.arm
    await replay.advance_to(1)
    counts = replay.counts()
    assert counts["ingested"] > 0, f"no packet reached the arm's parts: {counts}"  # first
    assert counts["unresolved"] == 0
    alice = await me(replay.client, replay.headers)
    assert replay.view.robot_entity_id == arm.robot  # the robot and the member the opener passed
    assert replay.view.owner_user_id == uuid.UUID(alice["id"])

    await replay.advance_to(6)  # the onset is at 5 s; a second on, the stall is not yet judged
    assert await replay.findings() == []
    await replay.advance_to(7)  # 2 s of the recording's own time after the onset
    findings = await replay.findings()

    (stall,) = [f for f in findings if replay.who(f) == "servo 3"]  # exactly one on servo 3
    (other,) = [f for f in findings if f is not stall]
    assert (other.attrs["rule_id"], replay.who(other)) == ("rail_sag_correlated", "bus")
    assert stall.attrs["rule_id"] == "tracking_error_stall"
    assert (stall.attrs["status"], stall.attrs["severity"]) == ("open", "critical")
    evidence = stall.attrs["evidence"]
    assert evidence["current_a"] > evidence["bound"] == 2.0  # against the rating, stated by config
    assert evidence["bounds_source"] == "config"
    # the other rules on servo 3 fold into it, in precedence order: nothing else, nothing missing
    assert evidence["also"] == ["current_over_rating", "time_to_limit"]
    onset = EPOCH + timedelta(seconds=5)
    assert datetime.fromisoformat(evidence["window_end"]) - onset <= timedelta(seconds=2)
    assert stall.attrs["subjects"] == [str(arm.parts[2]), str(arm.bus), str(arm.brain)]
    assert evidence["code_site"] == {
        "entity_id": str(arm.code_file),
        "source_id": None,
        "path": "fw/fake_arm.ino",
        "line": 13,
    }
    assert [cause["kind"] for cause in evidence["causes"]] == [
        "mechanical_load",
        "software_command",
        "actuator",
    ]
    assert (evidence["robot_id"], evidence["session_id"]) == (
        str(arm.robot),
        str(replay.session_id),
    )


async def test_sixty_seconds_is_one_node_count_rising(replay: _Replay) -> None:
    series: dict[uuid.UUID, list[int]] = {}
    raised_in: dict[uuid.UUID, int] = {}
    for second in range(1, 61):
        for finding_id in await replay.advance_to(second):
            raised_in[finding_id] = raised_in.get(finding_id, 0) + 1
        for finding in await replay.findings():
            series.setdefault(finding.id, []).append(finding.attrs["count"])
    findings = await replay.findings()
    kind = {f.id: (f.attrs["rule_id"], replay.who(f)) for f in findings}

    assert replay.counts() == {"ingested": 60 * 20 * PARTS, "unresolved": 0}
    assert len(set(kind.values())) == len(findings) == 6  # one node a condition, not one a tick
    assert all(f.attrs["count"] == raised_in[f.id] for f in findings)  # a raise a tick, no more
    by_kind = {name: finding_id for finding_id, name in kind.items()}
    stall = series[by_kind[("tracking_error_stall", "servo 3")]]
    assert stall[:4] == [1, 2, 3, 4] and set(stall[4:]) == {4}  # rising while it lasts, then still
    for ongoing in (("temp_trend_to_limit", "servo 3"), ("sensor_frozen", "servo 5")):
        rising = series[by_kind[ongoing]]
        assert rising == list(range(1, len(rising) + 1)), ongoing  # one more every tick
        assert len(rising) > 25  # to the end of the minute
    again = next(f for f in findings if kind[f.id] == ("tracking_error_stall", "servo 2"))
    assert datetime.fromisoformat(again.attrs["evidence"]["items"][0]["window_start"]) >= (
        EPOCH + timedelta(seconds=40)
    )  # servo 2 stalls after the first five distinct are told: the subject of the final acceptance
    assert _told_late(replay, TOLD_BY) == {}  # each condition, by its deadline in the scenario
    milliseconds = replay.window_ms
    logger.info(
        "rule time per window, six parts over a 30 s context: median %.1f ms, max %.1f ms "
        "over %d windows (the shipped per-window budget for six parts is 60 ms)",
        statistics.median(milliseconds),
        max(milliseconds),
        len(milliseconds),
    )
    assert len(milliseconds) == 60 and min(milliseconds) > 0


@pytest.mark.parametrize("replay", [{}], ids=["shipped_budget"], indirect=True)
async def test_five_distinct_findings_inside_40s(replay: _Replay) -> None:
    await replay.advance_to(40)
    findings = await replay.findings()

    told = [(f.attrs["rule_id"], replay.who(f)) for f in findings]
    assert len(findings) == 5 and all(f.attrs["status"] == "open" for f in findings)
    assert set(told) == {
        ("tracking_error_stall", "servo 3"),
        ("rail_sag_correlated", "bus"),
        ("time_to_limit", "servo 3"),
        ("temp_trend_to_limit", "servo 3"),
        ("sensor_frozen", "servo 5"),
    }
    assert told[2:] == [  # the stall and the sag first, together; then as the arm's day unfolds
        ("time_to_limit", "servo 3"),
        ("temp_trend_to_limit", "servo 3"),
        ("sensor_frozen", "servo 5"),
    ]
    ends = [datetime.fromisoformat(f.attrs["evidence"]["window_end"]) for f in findings]
    assert max(ends) < EPOCH + timedelta(seconds=40)  # nothing was judged past what was released
    five = [key for key in TOLD_BY if key != ("tracking_error_stall", "servo 2")]
    # each of the five by its deadline in the scenario, a tick late at most (the shipped budget
    # can skip a rule for a window; the next tick starts with it)
    assert _told_late(replay, five, slack=1) == {}


# ---------------------------------------------------------------------------- the route


class _ReplayLocal(FakeLocal):
    """The runner's replay opener, as a double that keeps what it is asked to open."""

    async def open_replay(self, config: dict[str, Any], *, project_id: uuid.UUID) -> TapConn:
        return await self._open("replay", config=config, project_id=project_id)


async def test_replay_config_rejects_traversal_unset_root_and_foreign_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    maker: Maker = async_sessionmaker(engine, expire_on_commit=False)
    project, arm = await _arm_in_a_project(client, alice_headers, maker)
    _, foreign = await _arm_in_a_project(client, alice_headers, maker, team="Another team")
    local = _ReplayLocal()
    app.state.bench_local = local
    root = tmp_path / "replays"
    root.mkdir()
    (root / CAPTURE).write_text("{}")
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (root / "escape.json").symlink_to(outside)
    url = f"/api/v1/projects/{project}/bench/sessions"

    async def start(body: dict[str, Any]) -> Any:
        return await client.post(url, headers=alice_headers, json=body)

    app.state.settings.bench_replay_root = None  # unset, whatever the shell exported
    unset = await start(_replay_body(arm.robot, CAPTURE))
    app.state.settings.bench_replay_root = root

    assert (unset.status_code, unset.json()["error"]["code"]) == (503, "source_unavailable")
    for recording in (
        "../outside.json",
        "escape.json",  # a symlink out of the root
        str(outside),
        "capture.json/../../outside.json",
        "notes.txt",
        "ghost.json",
    ):
        refused = await start(_replay_body(arm.robot, recording))
        assert refused.status_code == 422, recording
        assert refused.json()["error"]["code"] == "validation_error", recording
    for robot in (foreign.robot, uuid.uuid4()):  # another project's robot; no such robot
        gone = await start(_replay_body(robot, CAPTURE))
        assert (gone.status_code, gone.json()["error"]["code"]) == (404, "not_found")
    sim = await start({**_replay_body(arm.robot, CAPTURE), "mode": "sim"})
    assert sim.status_code == 422 and local.opened == []

    started = await start(_replay_body(arm.robot, CAPTURE))

    assert started.status_code == 201, started.text
    record = started.json()["data"]
    assert (record["provider"], record["mode"]) == ("replay", "real")
    assert record["robot_entity_id"] == str(arm.robot)
    assert record["label"] == "Replay capture.json as Fake arm"
    assert record["device"] == {"device_ref": DEVICE_REF, "driver_id": "lb06", "replay": True}
    (opened,) = local.opened
    assert opened["config"]["recording"] == str((root / "capture.json").resolve())
    assert opened["config"]["realtime"] is False and opened["project_id"] == project
    await app.state.bench_sessions.aclose_all()


async def test_cross_team_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    maker: Maker = async_sessionmaker(engine, expire_on_commit=False)
    mine, my_arm = await _arm_in_a_project(client, alice_headers, maker, team="Alice's")
    theirs, their_arm = await _arm_in_a_project(client, bob_headers, maker, team="Bob's")
    local = _ReplayLocal()
    app.state.bench_local = local
    app.state.settings.bench_replay_root = tmp_path
    (tmp_path / CAPTURE).write_text("{}")

    def url(project: uuid.UUID, tail: str = "") -> str:
        return f"/api/v1/projects/{project}/bench/sessions{tail}"

    body = _replay_body(my_arm.robot, CAPTURE)
    anonymous = await client.post(url(mine), json=body)
    intruder = await client.post(url(mine), headers=bob_headers, json=body)  # not a member
    through_theirs = await client.post(url(theirs), headers=bob_headers, json=body)  # her robot
    assert anonymous.status_code == 401
    assert (intruder.status_code, through_theirs.status_code) == (404, 404)
    assert through_theirs.json()["error"]["code"] == "not_found" and local.opened == []

    started = await client.post(url(mine), headers=alice_headers, json=body)
    own = await client.post(
        url(theirs), headers=bob_headers, json=_replay_body(their_arm.robot, CAPTURE)
    )
    assert (started.status_code, own.status_code) == (201, 201)  # each team's own robot is fine
    alice_session = started.json()["data"]["id"]
    seen = await client.get(url(theirs, f"/{alice_session}"), headers=bob_headers)
    stopped = await client.post(url(theirs, f"/{alice_session}/stop"), headers=bob_headers)
    assert (seen.status_code, stopped.status_code) == (404, 404)
    assert (
        await client.get(url(mine, f"/{alice_session}"), headers=bob_headers)
    ).status_code == 404
    listed = await client.get(url(theirs), headers=bob_headers)
    assert [row["robot_entity_id"] for row in listed.json()["data"]] == [str(their_arm.robot)]
    await app.state.bench_sessions.aclose_all()


def _capture_file(root: Path, name: str, *, binding: str, frames: int = 6) -> None:
    """The first `frames` frames of the committed recording, filed under `binding`."""
    source = json.loads((FIXTURES / RECORDING).read_text())
    document = {"transport": "usb_serial", "binding": binding, "frames": source["frames"][:frames]}
    (root / name).write_text(json.dumps(document))


async def test_the_runner_refuses_a_capture_of_another_device_or_one_it_cannot_read(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """The real runner (`livebench.local`) behind the route: it refuses, as a 422 that never
    echoes the file, a capture recorded from a device that is not the robot's (its lines would
    be relabelled onto this robot's parts or dropped), one that does not parse, and a driver
    nobody registered. No session is left behind."""
    maker: Maker = async_sessionmaker(engine, expire_on_commit=False)
    project, arm = await _arm_in_a_project(client, alice_headers, maker)
    app.state.settings.bench_replay_root = tmp_path
    _capture_file(tmp_path, "other.json", binding="OTHER-DEVICE")
    _capture_file(tmp_path, "mine.json", binding=fake_arm.USB_SERIAL)
    (tmp_path / "garbage.json").write_text("secret-text {not json")
    url = f"/api/v1/projects/{project}/bench/sessions"

    async def start(recording: str, **over: Any) -> dict[str, Any]:
        resp = await client.post(
            url, headers=alice_headers, json=_replay_body(arm.robot, recording, **over)
        )
        assert resp.status_code == 422, (recording, resp.text)
        error: dict[str, Any] = resp.json()["error"]
        assert error["code"] == "validation_error"
        return error

    other = await start("other.json")
    garbage = await start("garbage.json")
    unknown = await start("mine.json", driver_id="no-such-driver")

    assert other["message"] == "the recording was captured from another device than this robot's"
    assert garbage["message"] == "the recording could not be read"
    assert "secret-text" not in str(garbage) and "OTHER-DEVICE" not in str(other)
    assert "no-such-driver" in unknown["message"]
    assert (await client.get(url, headers=alice_headers)).json()["data"] == []


async def test_a_realtime_replay_is_paced_by_its_recorded_times_and_goes_quiet_at_its_end(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """The default (`realtime` true): six lines 50 ms apart take at least 250 ms to arrive, and
    when the capture ends the session stays active and silent, as a quiet link does."""
    maker: Maker = async_sessionmaker(engine, expire_on_commit=False)
    project, arm = await _arm_in_a_project(client, alice_headers, maker)
    app.state.settings.bench_replay_root = tmp_path
    _capture_file(tmp_path, "short.json", binding=fake_arm.USB_SERIAL, frames=6)
    url = f"/api/v1/projects/{project}/bench/sessions"
    body = _replay_body(arm.robot, "short.json")
    del body["config"]["realtime"]

    began = time.monotonic()
    started = await client.post(url, headers=alice_headers, json=body)
    assert started.status_code == 201, started.text
    session = started.json()["data"]["id"]

    async def detail() -> dict[str, Any]:
        resp = await client.get(f"{url}/{session}", headers=alice_headers)
        data: dict[str, Any] = resp.json()["data"]
        return data

    while (await detail())["counts"]["ingested"] < 6 * PARTS:
        assert time.monotonic() - began < 10, await detail()
        await asyncio.sleep(0.01)
    paced = time.monotonic() - began
    await asyncio.sleep(0.4)  # the capture has ended
    quiet = await detail()
    stopped = await client.post(f"{url}/{session}/stop", headers=alice_headers)

    assert paced >= 0.25
    assert (quiet["status"], quiet["counts"]["ingested"]) == ("active", 6 * PARTS)
    assert stopped.json()["data"]["status"] == "ended"
    await app.state.bench_sessions.aclose_all()


# ---------------------------------------------------------------------------- hygiene


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_fake_arm_stall", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_recording_is_the_fake_arms_own() -> None:
    """The generator and the graph half agree on the device, the servos and the channels."""
    generator = _load_generator()

    assert generator.BINDING == fake_arm.USB_SERIAL and generator.DEVICE_ID == DEVICE_REF
    assert generator.CHANNELS == fake_arm.CHANNELS
    assert len(generator.SERVOS) == len(fake_arm.PART_NAMES) == PARTS
    recording = load_recording(FIXTURES / RECORDING)
    assert recording.identity.device_ref == DEVICE_REF


def test_regenerating_the_recording_reproduces_the_committed_bytes(tmp_path: Path) -> None:
    """Fixed epoch, no randomness: the same run writes the same bytes."""
    generator = _load_generator()

    assert generator.main(["make_fake_arm_stall.py", str(tmp_path)]) == 0

    assert (tmp_path / RECORDING).read_bytes() == (FIXTURES / RECORDING).read_bytes()


def test_fixture_and_shared_code_carry_no_vendor_name() -> None:
    """The seed, the generator, the recording (its lines decoded), and the shared code that
    reads it name no vendor or product; the device and the names are synthetic."""
    frames = load_recording(FIXTURES / RECORDING).frames
    lines = "\n".join(frame.payload.decode() for frame in frames)
    findings = sorted((SRC_ROOT / "livebench" / "findings").rglob("*.py"))
    swept = {
        "fixtures/fake_arm.py": (Path(fake_arm.__file__)).read_text(),
        "make_fake_arm_stall.py": GENERATOR.read_text(),
        RECORDING: (FIXTURES / RECORDING).read_text() + "\n" + lines,
        "livebench/replay_provider.py": (SRC_ROOT / "livebench" / "replay_provider.py").read_text(),
        "livebench/bench_router.py": (SRC_ROOT / "livebench" / "bench_router.py").read_text(),
        "livebench/local.py": (REPO / "livebench/src/livebench/local.py").read_text(),
        "hardware/replay.py": (REPO / "livebench/src/livebench/hardware/replay.py").read_text(),
        **{str(path.relative_to(SRC_ROOT)): path.read_text() for path in findings},
    }

    assert len(findings) > 10 and len(lines) > 1_000_000  # the sweep reads what it should
    offenders = [
        f"{name}:{number}: [{match.group(0)}]"
        for name, text in swept.items()
        for number, line in enumerate(text.splitlines(), start=1)
        if (match := VENDOR_WORDS.search(line))
    ]
    assert not offenders, "\n".join(offenders)
