"""SOLUSDEV-322 P8-T1 — the fixture acceptance harness: eight scenarios, in process.

Every SOL turn here runs the production shape — `LlmRunner` over the gateway (metering, ledger,
`model call start` log line), `build_mode_dispatch` outside `build_dispatch` with the real
`request_confirmation` park — with ONE substitution: the provider adapter is `ScriptedModel`,
which emits each scenario's tool-call sequence and never leaves the process
(`build_adapter_registry` is forbidden for the whole module, so a real adapter cannot even be
built). Companions are fakes in the shape of `tests/test_gazebo_tools.Native` /
`tests/test_isaac_tools.Native`; ownership is the ledger's. Isaac cannot run on this host
(x86_64 only): its scenarios are fixture-only.

Each scenario records its scripted model calls, the gateway's `model call start` lines, the
`credit_ledger` rows, the `ToolConfirmation` cards and its wall time; the table prints at session
end and is pasted into `docs/qa/acceptance/P8-sim-acceptance.md`.
"""

from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fixtures.fake_arm import DEVICE_REF, FakeArm, seed_fake_arm
from fixtures.fake_systems import FakeSolSystems
from httpx import AsyncClient
from solus_api.agent import prompt
from solus_api.agent.confirmations import decide_confirmation, request_confirmation
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import AgentRunContext, DispatchFn, LlmRunner, build_dispatch
from solus_api.agent.stream import AgentEvent, AgentEventType
from solus_api.agent.tools.gazebo_models import PUBLIC_MODELS as GZ_MODELS
from solus_api.agent.tools.gazebo_tools import build_gazebo_tools, gazebo_routine_readback
from solus_api.agent.tools.isaac_models import PUBLIC_MODELS as ISAAC_MODELS
from solus_api.agent.tools.isaac_tools import build_isaac_tools
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.sim_available import SimAvailability
from solus_api.agent.tools.sim_generate import NAME as GENERATE
from solus_api.agent.tools.sim_generate import SimGenerateTool, gap_report_rows
from solus_api.agent.tools.simulate import register_simulation_tools
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.agent.turn_limits import GUIDE_TOOL_CALLS
from solus_api.connectors.onshape_assembly_read import mates_from_definition
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.live import LiveHub
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.sim_run_retention import prune_sim_runs
from solus_api.livebench.sim_runs import sim_run_hook
from solus_api.models import (
    Artifact,
    ArtifactStorage,
    ConfirmationStatus,
    CreditBalance,
    CreditLedger,
    Domain,
    GraphEntity,
    PlanType,
    Project,
    Subscription,
    SubscriptionStatus,
    Team,
    ToolConfirmation,
    User,
)
from solus_api.orchestration import gateway
from solus_api.orchestration.providers import ImageBlock, ToolConversation, ToolUse, Usage
from solus_api.simulation.model_job import (
    GenerateModelRequest,
    gap_report,
    gather,
    run_generate_sim_model,
)
from solus_api.simulation.sessions_ledger import SessionsLedger
from solus_api.storage import LocalArtifactStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_gazebo_tools import ATTACHED, FILES, MANIFEST, MODEL_SHA, SESSION, MemoryStore
from test_gazebo_tools import graph as gazebo_graph
from test_gazebo_tools import tools as attached_fixture_tools
from test_isaac_tools import ARTICULATION, STAGE
from test_isaac_tools import SESSION as ISAAC_SESSION
from test_isaac_tools import Native as IsaacNative
from test_model_job import CadArm, cad_arm
from test_sim_available import QUEUED, _machine, _probe
from test_sim_run_retention import NOW, OLD, RECENT, _payload_state, _runs, _setup
from test_sim_runs import ELBOW, ROUTINE, _gazebo_result
from test_simulate import AT_15, _bracket

Maker = async_sessionmaker[AsyncSession]
Call = tuple[str, dict[str, Any]]
ToolItem = tuple[str, dict[str, Any]]
Round = Sequence[str | ToolItem]

GATEWAY_LOGGER = "solus.orchestration.gateway"
START_LINE = "model call start"
PROVIDERS = ("anthropic", "openai", "google")
FAMILIES = (("gz", "8.15.0"), ("ignition", "6.16.0"), ("classic", "11.15.1"))
GUIDE_REFUSAL = "Guide mode can explain"
WAITING = "waiting for the person to approve"
CLASSIC_SENTENCE = "Classic 11 cannot write a running world back to its file."
#: The fork's own `Unsupported.wire()` for `save_world` on Classic (adapter_base.py).
UNSUPPORTED = {
    "ok": False,
    "code": "unsupported_on",
    "family": "classic",
    "version": "11",
    "reason": "classic 11 cannot write a running world back to its file",
}
INFERENCE = Path(__file__).resolve().parents[1] / "fixtures" / "inference"


# ------------------------------------------------------------------------------- the report


@dataclass
class ReportRow:
    scenario: str
    scripted: int = 0
    starts: int = 0
    ledger: int = 0
    cards: int = 0
    seconds: float = 0.0
    note: str = ""

    @property
    def real(self) -> int:
        """Start lines nobody scripted answered: must be 0."""
        return self.starts - self.scripted


REPORT: list[ReportRow] = []
_HEADER = (
    f"{'scenario':<28}{'scripted':>9}{'starts':>7}{'real':>5}{'ledger':>7}{'cards':>6}"
    f"{'wall s':>8}  note"
)


def _line(r: ReportRow) -> str:
    return (
        f"{r.scenario:<28}{r.scripted:>9}{r.starts:>7}{r.real:>5}{r.ledger:>7}{r.cards:>6}"
        f"{r.seconds:>8.2f}  {r.note}"
    )


def report_lines() -> list[str]:
    total = ReportRow(
        f"TOTAL ({len(REPORT)} rows)",
        sum(r.scripted for r in REPORT),
        sum(r.starts for r in REPORT),
        sum(r.ledger for r in REPORT),
        sum(r.cards for r in REPORT),
        sum(r.seconds for r in REPORT),
    )
    rule = "-" * len(_HEADER)
    return [_HEADER, rule, *map(_line, REPORT), rule, _line(total)]


@pytest.fixture(scope="session", autouse=True)
def _print_report(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    reporter: Any = request.config.pluginmanager.get_plugin("terminalreporter")
    for line in ("", "P8-T1 sim acceptance", *report_lines()):
        if reporter is not None:
            reporter.write_line(line)


@pytest.fixture(autouse=True)
def _no_real_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gateway call without `adapters=` would build the real registry: forbidden here."""

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a real provider adapter was built")

    monkeypatch.setattr(gateway, "build_adapter_registry", forbidden)


class ScenarioRecorder:
    """One scenario's counters, read from the log, the ledger and the cards table."""

    def __init__(self, name: str, maker: Maker, caplog: pytest.LogCaptureFixture) -> None:
        self.name, self.maker, self.caplog = name, maker, caplog
        self.started = time.perf_counter()
        caplog.set_level(logging.INFO, logger=GATEWAY_LOGGER)

    async def finish(self, scripted: int, note: str = "") -> ReportRow:
        starts = sum(1 for r in self.caplog.records if r.getMessage().startswith(START_LINE))
        async with self.maker() as db:
            ledger = await db.scalar(select(func.count()).select_from(CreditLedger))
            cards = await db.scalar(select(func.count()).select_from(ToolConfirmation))
        row = ReportRow(
            self.name,
            scripted,
            starts,
            int(ledger or 0),
            int(cards or 0),
            time.perf_counter() - self.started,
            note,
        )
        assert row.real == 0, row
        REPORT.append(row)
        return row


# ----------------------------------------------------------------------- the scripted model


class ScriptedModel:
    """One provider adapter, in process. A runner round pops the next scripted round (text and
    tool uses, offered under the provider-safe names); any other call, or a round nothing was
    scripted for, answers `ok`. Every call is counted."""

    def __init__(self, rounds: Sequence[Round], offered: Mapping[str, str]) -> None:
        self.rounds: deque[Round] = deque(rounds)
        self.offered = offered
        self.calls = 0

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        self.calls += 1
        if conversation is None or not self.rounds:
            yield "ok"
            yield Usage(tokens_in=5, tokens_out=1)
            return
        for index, item in enumerate(self.rounds.popleft()):
            if isinstance(item, str):
                yield item
                continue
            tool, args = item
            yield ToolUse(id=f"tu_{self.calls}_{index}", name=self.offered[tool], args=args)
        yield Usage(tokens_in=5, tokens_out=2)


@dataclass(frozen=True)
class CallOutcome:
    tool: str
    args: dict[str, Any]
    ok: bool
    value: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True)
class SeenTurn:
    events: list[AgentEvent]

    @property
    def outcomes(self) -> list[CallOutcome]:
        calls = {e.data["call_id"]: e for e in self.events if e.type is AgentEventType.TOOL_CALL}
        out = []
        for event in self.events:
            if event.type is not AgentEventType.TOOL_RESULT:
                continue
            call = calls[event.data["call_id"]]
            error = event.data.get("error")
            out.append(
                CallOutcome(
                    call.data["tool"],
                    call.data["args"],
                    bool(event.data["ok"]),
                    event.data.get("value"),
                    error["message"] if isinstance(error, dict) else None,
                )
            )
        return out

    def of(self, tool: str) -> CallOutcome:
        return next(o for o in self.outcomes if o.tool == tool)

    @property
    def message(self) -> str:
        return str(next(e for e in self.events if e.type is AgentEventType.MESSAGE).data["content"])


@dataclass
class SimBench:
    """One project's SOL surface: the registry, the person, and the production dispatch shape."""

    maker: Maker
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    registry: ToolRegistry = field(default_factory=ToolRegistry)
    scripted: int = 0

    @property
    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self.registry.list())

    def add(self, tools: Sequence[Tool]) -> None:
        for tool in tools:
            self.registry.register(tool)

    def dispatch(self, mode: ActionMode) -> DispatchFn:
        async def park(call: Any) -> Any:
            async with self.maker() as db:
                parked = await request_confirmation(
                    db,
                    self.registry,
                    call,
                    project_id=self.project_id,
                    team_id=self.team_id,
                    user_id=self.user_id,
                )
                await db.commit()
                return parked

        return build_mode_dispatch(
            mode, self.descriptors, build_dispatch(self.registry, park), registry=self.registry
        )

    async def turn(self, mode: ActionMode, rounds: Sequence[Round], ask: str) -> SeenTurn:
        model = ScriptedModel(rounds, prompt.provider_tool_names(self.descriptors))
        ctx = AgentRunContext(
            prompt=ask,
            tools=self.descriptors,
            dispatch=self.dispatch(mode),
            systems=FakeSolSystems(),
            project_id=self.project_id,
            action_mode=mode,
            user_id=self.user_id,
            sessionmaker=self.maker,
            secret_store=InMemorySecretStore(),
        )
        runner = LlmRunner(adapters={name: model for name in PROVIDERS})
        events = [event async for event in runner.run(ctx)]
        self.scripted += model.calls
        return SeenTurn(events)

    async def cards(self) -> list[ToolConfirmation]:
        async with self.maker() as db:
            return list(await db.scalars(select(ToolConfirmation).order_by(ToolConfirmation.id)))


# ------------------------------------------------------------------------------- seeding


async def _fund(maker: Maker, user_id: uuid.UUID) -> None:
    """Credits and an active plan for the person's SOL turns (an API-provisioned user already
    holds a balance row and a trial: those are updated, not duplicated)."""
    async with maker() as db:
        balance = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user_id))
        if balance is None:
            db.add(CreditBalance(user_id=user_id, balance=10_000))
        else:
            balance.balance = 10_000
        plan = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        if plan is None:
            db.add(
                Subscription(user_id=user_id, plan=PlanType.PRO, status=SubscriptionStatus.ACTIVE)
            )
        else:
            plan.plan, plan.status = PlanType.PRO, SubscriptionStatus.ACTIVE
        await db.commit()


async def _seeded(engine: AsyncEngine) -> SimBench:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        team = Team(name="sim acceptance")
        user = User(supabase_user_id=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@example.com")
        db.add_all([team, user])
        await db.flush()
        project = Project(team_id=team.id, name="Arm", created_by=user.id)
        db.add(project)
        await db.commit()
        bench = SimBench(maker, project.id, team.id, user.id)
    await _fund(maker, bench.user_id)
    return bench


async def _bench_of(maker: Maker, project: Project) -> SimBench:
    assert project.created_by is not None
    await _fund(maker, project.created_by)
    return SimBench(maker, project.id, project.team_id, project.created_by)


async def _fake_arm_model(
    maker: Maker, project_id: uuid.UUID, fake: FakeArm, store: MemoryStore, user_id: uuid.UUID
) -> GraphEntity:
    """A `simulation_model` of the fake arm whose `elbow` joint IS servo 3's node."""
    async with maker() as db:
        links = [
            GraphEntity(project_id=project_id, domain=Domain.MECHANICAL, kind="component", name=n)
            for n in ("upper_arm", "forearm")
        ]
        db.add_all(links)
        await db.flush()
        artifacts: dict[str, Any] = {"meshes": {}}
        for path, data in FILES.items():
            artifact = Artifact(
                project_id=project_id,
                uri="/x",
                media_type="application/octet-stream",
                size_bytes=len(data),
                storage_location=ArtifactStorage.LOCAL,
                created_by=user_id,
                retained=True,
            )
            db.add(artifact)
            await db.flush()
            await store.put(str(artifact.id), data)
            if path.endswith(".urdf"):
                artifacts["urdf"] = str(artifact.id)
            else:
                artifacts["meshes"][path] = str(artifact.id)
        model = {
            "schema_version": 2,
            "asset": {"urdf_path": "robot.urdf", "files": dict(MANIFEST), "sha256": MODEL_SHA},
            "links": [{"entity_id": str(link.id), "name": link.name} for link in links],
            "joints": [
                {
                    "entity_id": str(fake.parts[2]),
                    "name": "elbow",
                    "parent_link_entity_id": str(links[0].id),
                    "child_link_entity_id": str(links[1].id),
                    "lower_rad": -1.0,
                    "upper_rad": 1.0,
                }
            ],
            "sensors": [],
        }
        root = GraphEntity(
            project_id=project_id,
            domain=Domain.SIMULATION,
            kind=kinds.SIMULATION_MODEL,
            origin="system",
            name="Fake arm model",
            attrs={"robot_id": str(fake.robot), "simulation_model": model, "artifacts": artifacts},
        )
        db.add(root)
        await db.commit()
        return root


async def _alias_elbow(maker: Maker, part_id: uuid.UUID) -> None:
    async with maker() as db:
        part = await db.get(GraphEntity, part_id)
        assert part is not None
        part.attrs = {**part.attrs, "sim_aliases": [{"provider": "gazebo", "device_id": ELBOW}]}
        await db.commit()


# ---------------------------------------------------------------------- the fake companions


class GazeboCompanion:
    """One raw `gazebo.<name>` bridge tool of one family: untrusted advert, scripted answers,
    every call logged. `save_world` on Classic answers the fork's `unsupported_on`."""

    def __init__(
        self, name: str, calls: list[Call], family: str, version: str, world: dict[str, Any]
    ) -> None:
        self.descriptor = ToolDescriptor(
            name="gazebo." + name,
            description="untrusted advert",
            params={"type": "object", "properties": {"model_sha256": {}, "script": {}}},
            returns={},
        )
        self.name, self.calls, self.family, self.version, self.world = (
            name,
            calls,
            family,
            version,
            world,
        )
        self.plan: dict[str, Any] = {
            "ok": True,
            "dry_run": True,
            "preview": [{"label": f"{name} on {family}", "before": "as is", "after": "as asked"}],
            "fingerprint": "a" * 64,
        }
        if name == "save_world" and family == "classic":
            self.plan = dict(UNSUPPORTED)

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((self.name, copy.deepcopy(args)))
        read = self._read(args)
        if read is not None:
            return read
        if args.get("dry_run") is True:
            return copy.deepcopy(self.plan)
        return self._write(args)

    def _read(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if self.name == "probe":
            return {"ok": True, "families": [{"name": self.family, "version": self.version}]}
        if self.name == "list_worlds":
            return {"ok": True, "worlds": [{"path": "demo.sdf"}], "running": []}
        if self.name == "attach":
            return {"ok": True, "session_id": ATTACHED, "world": args["world"]}
        if self.name == "put_asset":
            if args["index"] + 1 == args["total"]:
                self.world["assets"].add(args["sha256"])
            return {"ok": True, "received": args["index"] + 1, "promoted": True}
        if self.name == "spawn" and args["model_sha256"] not in self.world["assets"]:
            return {"ok": False, "code": "model_not_verified", "reason": "push it first"}
        return None

    def _write(self, args: dict[str, Any]) -> dict[str, Any]:
        session = args.get("session_id", SESSION)
        if self.name == "open_world":
            return {"ok": True, "session_id": SESSION, "world": "demo", "family": self.family}
        if self.name == "stop":
            return {"ok": True, "session_id": session, "state": "stopped"}
        if self.name == "run_routine":
            return _gazebo_result(session_id=session, family=self.family, version=self.version)
        return {"ok": True, "session_id": session}


def _gazebo_tools(
    bench: SimBench,
    *,
    family: str,
    version: str,
    ledger: SessionsLedger,
    store: MemoryStore,
    runs: LocalArtifactStore | None = None,
) -> list[Call]:
    """The owned `gazebo.*` wrappers over a `family` companion, with the Run hook when `runs`."""
    calls: list[Call] = []
    world: dict[str, Any] = {"assets": {MODEL_SHA}}
    native = {
        "gazebo." + n: GazeboCompanion(n, calls, family, version, world)
        for n in (*GZ_MODELS, "put_asset")
    }
    hook = (
        sim_run_hook(
            bench.maker,
            LiveHub(),
            runs,
            ledger,
            project_id=bench.project_id,
            provider="gazebo",
            user_id=bench.user_id,
            reader=gazebo_routine_readback,
        )
        if runs is not None
        else None
    )
    bench.add(
        build_gazebo_tools(
            bench.maker,
            bench.project_id,
            native,
            ledger=ledger,
            artifacts=store,
            user_id=bench.user_id,
            record_sim_run=hook,
        )
    )
    return calls


class IsaacCompanion(IsaacNative):
    """The Isaac test fake, answering `read_state` for the sensors asked and tracking the
    stage's running state across `open_stage` / `stop` (the real fork does)."""

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.name == "read_state":
            self.calls.append(("read_state", copy.deepcopy(args)))
            return {
                "ok": True,
                "articulation": {"path": args.get("articulation"), "dofs": {"elbow": 0.0}},
                "sensors": {
                    path: {"kind": path.rsplit("/", 1)[-1], "sample": [0.0, 0.0, 9.81]}
                    for path in args.get("sensors", [])
                },
            }
        result = await super().invoke(args)
        if args.get("dry_run") is not True and self.name in ("open_stage", "stop"):
            running = self.name == "open_stage"
            self.state.update(state="running" if running else "stopped")
            self.state.update(session_id=ISAAC_SESSION if running else None)
        return result


def _isaac_tools(bench: SimBench, ledger: SessionsLedger, store: MemoryStore | None) -> list[Call]:
    calls: list[Call] = []
    state: dict[str, Any] = {
        "state": "stopped",
        "session_id": None,
        "scene_generation": 0,
        "graph_digest": None,
        "model_entity_id": None,
        "loaded": False,
    }
    native = {"isaac." + n: IsaacCompanion(n, calls, state) for n in (*ISAAC_MODELS, "put_asset")}
    bench.add(
        build_isaac_tools(bench.maker, bench.project_id, native, ledger=ledger, artifacts=store)
    )
    return calls


def _writes(calls: list[Call], name: str) -> list[dict[str, Any]]:
    return [arg for op, arg in calls if op == name and not arg.get("dry_run")]


def _gz_call(op: str, **args: Any) -> ToolItem:
    return "gazebo." + op, {"session_id": SESSION, **args}


SWEEP: dict[str, Any] = {**ROUTINE, "duration_s": 2}


def _gazebo_ops(model_id: uuid.UUID) -> list[ToolItem]:
    return [
        _gz_call("spawn", model_entity_id=str(model_id), name="arm1"),
        _gz_call(
            "set_joint_targets", model="arm1", targets=[{"joint": "elbow", "position_rad": 0.3}]
        ),
        _gz_call("control", action="step", steps=5),
        _gz_call("run_routine", **SWEEP),
        _gz_call("stop"),
    ]


# ============================================================================== scenario 1


async def test_scenario_1_no_simulator_rung_1_answers_with_zero_cards(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """No simulator: a strength question is answered at rung 1 in process (margin → stops), only
    `simulate` is called and nothing is carded; a question only rung 4 answers is routed to a
    Gazebo/Isaac routine that is not connected, in one sentence."""
    bench = await _seeded(engine)
    record = ScenarioRecorder("1 no simulator", bench.maker, caplog)
    async with bench.maker() as db:
        part = GraphEntity(
            project_id=bench.project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name="shoulder bracket",
            attrs=_bracket(AT_15),
        )
        db.add(part)
        await db.commit()
    register_simulation_tools(
        bench.registry,
        bench.maker,
        bench.project_id,
        user_id=bench.user_id,
        hub=LiveHub(),
        enqueue_sim=None,
    )
    question = {"subject_id": str(part.id), "quantity": "stress_mpa"}

    turn = await bench.turn(
        ActionMode.DO,
        [[("simulate", {"question": question})], ["41 MPa against 276 MPa yield: it holds."]],
        "Will the shoulder bracket take the 500 g payload at full reach?",
    )

    assert [o.tool for o in turn.outcomes] == ["simulate"]
    ran = turn.of("simulate")
    assert ran.ok and ran.value is not None, ran.error
    assert (ran.value["decision"], ran.value["rung"], ran.value["verdict"]) == ("ran", 1, "stops")
    assert "margin" in ran.value["reason"]

    routed = await bench.turn(
        ActionMode.DO,
        [[("simulate", {"question": {**question, "quantity": "joint_trajectory"}})], ["ok"]],
        "Sweep the elbow through its range.",
    )
    route = routed.of("simulate")
    assert route.ok and route.value is not None, route.error
    assert route.value["decision"] == "route"
    assert route.value["route"]["target"] in {"gazebo", "isaac"}
    assert route.value["route"]["connected"] is False
    assert route.value["route"]["status"] == "not connected"
    assert await bench.cards() == []
    row = await record.finish(
        bench.scripted,
        f"rung 1 {ran.value['values']['stress_mpa']['value']:.1f} MPa stops; "
        f"joint_trajectory → route {route.value['route']['target']} not connected",
    )
    assert row.cards == 0


# ============================================================================== scenario 2


@dataclass
class ArmBench:
    bench: SimBench
    cad: CadArm
    fake: FakeArm
    model: GraphEntity
    ledger: SessionsLedger
    calls: list[Call]
    runs: LocalArtifactStore
    queued: list[tuple[str, str, dict[str, Any]]]


async def _arm_bench(
    db: AsyncSession,
    client: AsyncClient,
    headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    engine: AsyncEngine,
    tmp_path: Path,
    family: str,
    version: str,
) -> ArmBench:
    """Alice's CAD arm (the generate target) and the fake arm (the robot with a real bus
    identity) in one project; the owned Gazebo wrappers over a `family` companion."""
    cad = await cad_arm(db, client, headers, app, monkeypatch)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        project = await session.get(Project, cad.project_id)
        assert project is not None
        fake = await seed_fake_arm(session, cad.project_id, user_id=cad.user_id)
        await session.commit()
    bench = SimBench(maker, cad.project_id, project.team_id, cad.user_id)
    await _fund(maker, cad.user_id)
    await _alias_elbow(maker, fake.parts[2])
    store = MemoryStore()
    model = await _fake_arm_model(maker, cad.project_id, fake, store, cad.user_id)
    ledger = SessionsLedger(maker)
    runs = LocalArtifactStore(str(tmp_path / "runs"))
    calls = _gazebo_tools(
        bench, family=family, version=version, ledger=ledger, store=store, runs=runs
    )
    queued: list[tuple[str, str, dict[str, Any]]] = []

    async def enqueue(job: str, project_id: str, request: dict[str, Any]) -> str:
        queued.append((job, project_id, request))
        return f"{job}:{project_id}"

    bench.add([SimGenerateTool(maker, cad.project_id, user_id=cad.user_id, enqueue_sim=enqueue)])
    return ArmBench(bench, cad, fake, model, ledger, calls, runs, queued)


async def _run_of(arm: ArmBench, outcome: CallOutcome) -> tuple[Any, Any]:
    assert outcome.ok and outcome.value is not None, outcome.error
    assert outcome.value["run_reason"] is None, outcome.value
    async with arm.bench.maker() as db:
        record = await run_store.record(db, arm.bench.project_id, uuid.UUID(outcome.value["run"]))
        manifest = await run_store.load(db, arm.runs, record, arm.bench.user_id, 60)
    return record, manifest


async def _elbow_lands_on_servo_3(arm: ArmBench) -> None:
    """The one ingest path: the Gazebo sample and the real bus packet resolve to servo 3."""
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(arm.bench.maker))

    async def ingest(device_id: str, source: str | None) -> uuid.UUID | None:
        packet = TelemetryPacket(
            device_id=device_id,
            timestamp=datetime(2026, 11, 9, tzinfo=UTC),
            values={"elbow.position": 0.1},
            units={"elbow.position": "rad"},
        )
        return (await plumbing.ingest(arm.bench.project_id, packet, source=source)).entity_id

    assert await ingest(ELBOW, "gazebo") == arm.fake.parts[2]
    assert await ingest(f"{DEVICE_REF}/3", None) == arm.fake.parts[2]


async def _approve_generate(arm: ArmBench, app: FastAPI) -> dict[str, Any]:
    """The decide path on the parked card, then the job it enqueued, run inline (no worker)."""
    (card,) = await arm.bench.cards()
    async with arm.bench.maker() as db:
        decided = await decide_confirmation(
            db,
            arm.bench.registry,
            card.id,
            approve=True,
            project_id=arm.bench.project_id,
            user_id=arm.bench.user_id,
        )
        await db.commit()
    assert decided.ok and decided.value is not None, decided.error
    assert decided.value["status"] == "queued"
    [(job, project_id, request)] = arm.queued
    assert (job, project_id) == ("run_generate_sim_model", str(arm.bench.project_id))
    generated = await run_generate_sim_model(
        {"sessionmaker": arm.bench.maker, "artifact_store": app.state.artifact_store}, request
    )
    assert generated["status"] == "generated", generated
    async with arm.bench.maker() as db:
        model = await db.get(GraphEntity, uuid.UUID(generated["model_id"]))
    assert model is not None
    stored = model.attrs["artifacts"]
    assert stored["urdf"] and stored["mjcf"], stored
    return dict(model.attrs)


@pytest.mark.parametrize(("family", "version"), FAMILIES)
async def test_scenario_2_owned_gazebo_chain_in_build_and_guide(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    family: str,
    version: str,
) -> None:
    """Build: probe → list_worlds → open_world → sim.generate_model (the one card, approved on
    the decide path) → spawn → set_joint_targets → control → run_routine → stop in one turn.
    Guide: the same sim ops over two turns of at most GUIDE_TOOL_CALLS. Zero cards for the sim
    ops in both; a sim Run exists per routine, and its elbow is servo 3's node."""
    arm = await _arm_bench(
        db, client, alice_headers, app, monkeypatch, engine, tmp_path, family, version
    )
    bench = arm.bench
    record = ScenarioRecorder(f"2 {family} {version}", bench.maker, caplog)
    opening: list[ToolItem] = [
        ("gazebo.probe", {}),
        ("gazebo.list_worlds", {}),
        ("gazebo.open_world", {"world_ref": "demo.sdf", "family": family}),
    ]
    generate: ToolItem = (GENERATE, {"robot_id": str(arm.cad.robot.id), "name": "Arm"})
    ops = _gazebo_ops(arm.model.id)

    build = await bench.turn(
        ActionMode.DO, [[*opening, generate, *ops], ["Swept the elbow."]], "Sweep the elbow."
    )

    sim_ops = [o for o in build.outcomes if o.tool != GENERATE]
    assert [o.tool for o in sim_ops] == [name for name, _ in (*opening, *ops)]
    assert all(o.ok for o in sim_ops), [(o.tool, o.error) for o in sim_ops if not o.ok]
    assert build.of("gazebo.probe").value == {
        "ok": True,
        "families": [{"name": family, "version": version}],
    }
    opened = build.of("gazebo.open_world")
    assert opened.value is not None and opened.value["owner"] == "sol"
    parked = build.of(GENERATE)
    assert not parked.ok and parked.error is not None and WAITING in parked.error
    cards = await bench.cards()
    assert [c.tool for c in cards] == [GENERATE], "the gap report is the only card"
    async with bench.maker() as session:
        report = gap_report(
            await gather(session, GenerateModelRequest.model_validate(arm.cad.request()))
        )
    assert cards[0].preview == gap_report_rows(report)
    for name, _ in ops:
        assert len(_writes(arm.calls, name[7:])) == 1, name
    assert _writes(arm.calls, "spawn")[0]["model_sha256"] == MODEL_SHA
    record_row, manifest = await _run_of(arm, build.of("gazebo.run_routine"))
    assert run_store.summary(record_row).origin == "sim"
    assert run_store.summary(record_row).robot_id == arm.fake.robot
    assert (record_row.attrs["sim"]["family"], record_row.attrs["sim"]["version"]) == (
        family,
        version,
    )
    assert [(p.entity_id, p.device_id) for p in manifest.parts] == [(arm.fake.parts[2], ELBOW)]
    await _elbow_lands_on_servo_3(arm)
    generated = await _approve_generate(arm, app)

    assert GUIDE_TOOL_CALLS == 8
    first = await bench.turn(ActionMode.GUIDE, [[*opening, ops[0]], ["Spawned."]], "Open it.")
    second = await bench.turn(ActionMode.GUIDE, [ops[1:], ["Swept the elbow."]], "Sweep it.")
    guide = [*first.outcomes, *second.outcomes]
    assert [o.tool for o in guide] == [name for name, _ in (*opening, *ops)]
    assert all(o.ok for o in guide), [(o.tool, o.error) for o in guide if not o.ok]
    assert len(await bench.cards()) == 1, "Guide parked nothing"
    second_run, _ = await _run_of(arm, second.of("gazebo.run_routine"))
    assert second_run.id != record_row.id
    assert await arm.ledger.running(project_id=bench.project_id, provider="gazebo") == []
    await record.finish(
        bench.scripted,
        f"Build 1 turn ({len(build.outcomes)} calls), Guide 2 turns "
        f"({len(first.outcomes)}+{len(second.outcomes)}); card = {GENERATE} "
        f"({len(cards[0].preview)} rows, approved → {len(generated['artifacts'])} artifact kinds); "
        f"2 sim Runs on the fake arm; elbow = servo 3",
    )


# ============================================================================== scenario 3


async def test_scenario_3_attached_world_cards_in_build_refuses_in_guide(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    store = MemoryStore()
    project, root = await gazebo_graph(db, store)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bench = await _bench_of(maker, project)
    record = ScenarioRecorder("3 attached world", maker, caplog)
    ledger = SessionsLedger(maker)
    built, _, calls = attached_fixture_tools(engine, project.id, ledger=ledger, store=store)
    bench.add(list(built.values()))
    attached_ops: list[ToolItem] = [
        (name, {**args, "session_id": ATTACHED}) for name, args in _gazebo_ops(root.id)[:3]
    ]
    stop: ToolItem = ("gazebo.stop", {"session_id": ATTACHED})

    build = await bench.turn(
        ActionMode.DO,
        [[("gazebo.attach", {"family": "gz", "world": "demo"}), *attached_ops, stop], ["ok"]],
        "Move the arm in my running world.",
    )
    guide = await bench.turn(ActionMode.GUIDE, [[*attached_ops, stop], ["ok"]], "Move it.")

    attach = build.of("gazebo.attach")
    assert attach.ok and attach.value is not None and attach.value["owner"] == "user"
    for outcome in build.outcomes[1:4]:
        assert not outcome.ok and outcome.error is not None and WAITING in outcome.error
    for outcome in guide.outcomes[:3]:
        assert not outcome.ok and outcome.error is not None and GUIDE_REFUSAL in outcome.error
    for turn in (build, guide):
        stopped = turn.of("gazebo.stop")
        assert not stopped.ok and stopped.error is not None and "started by you" in stopped.error
    cards = await bench.cards()
    assert [c.tool for c in cards] == [name for name, _ in attached_ops]
    assert all(c.preview for c in cards), "each card carries the complete native preview"
    for name in ("spawn", "set_joint_targets", "control", "stop"):
        assert _writes(calls, name) == [], name
    await record.finish(
        bench.scripted,
        "Build: 3 cards (spawn, set_joint_targets, control); Guide: 3 refusals; "
        "stop refused in both, no card, fork never asked",
    )


# ============================================================================== scenario 4


async def test_scenario_4_save_world_and_save_stage_card_on_owned_sessions(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    store = MemoryStore()
    project, _ = await gazebo_graph(db, store)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bench = await _bench_of(maker, project)
    record = ScenarioRecorder("4 save on owned", maker, caplog)
    ledger = SessionsLedger(maker)
    gz_calls = _gazebo_tools(bench, family="gz", version="8.15.0", ledger=ledger, store=store)
    isaac_calls = _isaac_tools(bench, ledger, store)

    turn = await bench.turn(
        ActionMode.DO,
        [
            [
                ("gazebo.open_world", {"world_ref": "demo.sdf"}),
                _gz_call("save_world", dest="saved/demo.sdf"),
                ("isaac.open_stage", {"stage_ref": STAGE}),
                ("isaac.save_stage", {"session_id": ISAAC_SESSION, "dest": "nested/copy.usda"}),
            ],
            ["ok"],
        ],
        "Save both.",
    )

    assert turn.of("gazebo.open_world").ok and turn.of("isaac.open_stage").ok
    for name in ("gazebo.save_world", "isaac.save_stage"):
        saved = turn.of(name)
        assert not saved.ok and saved.error is not None and WAITING in saved.error, name
    cards = await bench.cards()
    assert [c.tool for c in cards] == ["gazebo.save_world", "isaac.save_stage"]
    assert all(c.preview for c in cards)
    assert _writes(gz_calls, "save_world") == [] and _writes(isaac_calls, "save_stage") == []
    assert await ledger.owned_running_count(project_id=project.id, provider="gazebo") == 1
    assert await ledger.owned_running_count(project_id=project.id, provider="isaac") == 1
    await record.finish(bench.scripted, "2 cards on 2 owned sessions; neither file written")


# ============================================================================== scenario 5


ISAAC_CHAIN: list[ToolItem] = [
    ("isaac.list_stages", {}),
    ("isaac.open_stage", {"stage_ref": STAGE}),
    ("isaac.find_articulations", {"session_id": ISAAC_SESSION}),
    (
        "isaac.read_state",
        {
            "session_id": ISAAC_SESSION,
            "articulation": ARTICULATION,
            "sensors": [f"{ARTICULATION}/imu", f"{ARTICULATION}/contact"],
        },
    ),
    (
        "isaac.run_routine",
        {
            "session_id": ISAAC_SESSION,
            "routine": "sweep",
            "duration_s": 2.0,
            "sweep": {
                "articulation": ARTICULATION,
                "joint": "elbow",
                "lower": -0.5,
                "upper": 0.5,
                "speed_rad_s": 0.25,
            },
        },
    ),
    ("isaac.stop", {"session_id": ISAAC_SESSION}),
]


@pytest.mark.parametrize("mode", [ActionMode.DO, ActionMode.GUIDE])
async def test_scenario_5_fixture_isaac_stage_chain_runs_with_zero_cards(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture, mode: ActionMode
) -> None:
    """Fixture-only: Isaac cannot run on this aarch64 host. The chain runs against the fake."""
    store = MemoryStore()
    project, root = await gazebo_graph(db, store)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bench = await _bench_of(maker, project)
    record = ScenarioRecorder(f"5 isaac {mode.value}", maker, caplog)
    calls = _isaac_tools(bench, SessionsLedger(maker), store)
    spawn: ToolItem = (
        "isaac.spawn_at",
        {"session_id": ISAAC_SESSION, "model_entity_id": str(root.id), "name": "arm2"},
    )
    chain = [*ISAAC_CHAIN[:3], spawn, *ISAAC_CHAIN[3:]]

    turn = await bench.turn(mode, [chain, ["Swept the elbow on the stage."]], "Sweep it.")

    assert [o.tool for o in turn.outcomes] == [name for name, _ in chain]
    assert all(o.ok for o in turn.outcomes), [(o.tool, o.error) for o in turn.outcomes if not o.ok]
    state = turn.of("isaac.read_state").value
    assert state is not None and set(state["sensors"]) == set(chain[4][1]["sensors"])
    assert _writes(calls, "spawn_at")[0]["model_sha256"] == MODEL_SHA
    assert len(_writes(calls, "run_routine")) == 1
    assert await bench.cards() == []
    await record.finish(bench.scripted, f"{len(chain)} ops ok, 0 cards (fixture-only host)")


# ============================================================================== scenario 6


async def _classic_save_turn(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture, name: str
) -> tuple[SimBench, ScenarioRecorder, str, SeenTurn, list[Call]]:
    """An owned Classic 11 world; `save_world` previewed directly (the fork's `unsupported_on`
    becomes one sentence), then proposed by the model in a Build turn."""
    store = MemoryStore()
    project, _ = await gazebo_graph(db, store)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bench = await _bench_of(maker, project)
    record = ScenarioRecorder(name, maker, caplog)
    calls = _gazebo_tools(
        bench, family="classic", version="11.15.1", ledger=SessionsLedger(maker), store=store
    )
    save: Any = next(t for t in bench.registry.tools() if t.descriptor.name == "gazebo.save_world")
    opened = await bench.turn(
        ActionMode.DO, [[("gazebo.open_world", {"world_ref": "demo.world"})], ["ok"]], "Open."
    )
    assert opened.of("gazebo.open_world").ok
    with pytest.raises(ToolException, match="Classic 11 cannot write") as refused:
        await save.preview({"session_id": SESSION, "dest": "saved/demo.world"})
    sentence = str(refused.value)
    turn = await bench.turn(
        ActionMode.DO,
        [[_gz_call("save_world", dest="saved/demo.world")], [sentence]],
        "Save the world.",
    )
    return bench, record, sentence, turn, calls


async def test_scenario_6a_classic_save_world_is_unsupported_in_one_sentence(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    bench, record, sentence, turn, calls = await _classic_save_turn(
        db, engine, caplog, "6a classic save_world"
    )

    saved = turn.of("gazebo.save_world")
    assert not saved.ok and saved.error is not None
    assert sentence == CLASSIC_SENTENCE and sentence.count(".") == 1
    assert _writes(calls, "save_world") == [] and await bench.cards() == []
    assert turn.message == CLASSIC_SENTENCE
    await record.finish(
        bench.scripted,
        f"preview: {sentence!r}; 0 cards; the turn's tool result said: {saved.error!r}",
    )


async def test_scenario_6a_the_turns_tool_result_carries_the_classic_sentence(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """P9-T1: the fork's `unsupported_on` sentence survives the park — `_consent_rows` raises a
    `PreviewRefusal`, which `_build_preview` carries into the turn's tool result."""
    bench, record, _, turn, _ = await _classic_save_turn(db, engine, caplog, "6a through turn")
    saved = turn.of("gazebo.save_world")
    await record.finish(bench.scripted, f"tool result said: {saved.error!r}")
    assert saved.error is not None and CLASSIC_SENTENCE in saved.error, saved.error


@pytest.mark.parametrize(
    ("os_name", "arch", "versions", "says"),
    [("Darwin", "arm64", {"nvidia-smi": "550"}, "Linux"), ("Linux", "x86_64", {}, "GPU")],
)
async def test_scenario_6b_machine_attrs_give_honest_isaac_rows(
    engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
    os_name: str,
    arch: str,
    versions: dict[str, str],
    says: str,
) -> None:
    bench = await _seeded(engine)
    record = ScenarioRecorder(f"6b {os_name}/{arch}", bench.maker, caplog)
    await _machine(
        bench.maker, bench.project_id, bench.user_id, os=os_name, arch=arch, versions=versions
    )
    bench.add([_probe("isaac.probe", {"available": True})])
    bench.add(
        [
            SimAvailability(
                bench.maker,
                bench.project_id,
                user_id=bench.user_id,
                settings=QUEUED,
                registry=bench.registry,
                ledger=SessionsLedger(bench.maker),
            ).tool()
        ]
    )

    turn = await bench.turn(ActionMode.GUIDE, [[("sim.available", {})], ["ok"]], "Can I sim?")

    available = turn.of("sim.available")
    assert available.ok and available.value is not None, available.error
    rows = {row["provider"]: row for row in available.value["providers"]}
    isaac = rows["isaac"]
    assert isaac["connected"] is True and isaac["runnable_here"] is False
    assert says in isaac["reason"] and isaac["reason"].endswith(".")
    # The fallback: the same result offers MuJoCo (and the calculators) as runnable here.
    mujoco = rows["mujoco"]
    assert mujoco["runnable_here"] is True and mujoco["reason"] is None, mujoco
    assert rows["calculators"]["runnable_here"] is True
    assert await bench.cards() == []
    await record.finish(
        bench.scripted,
        f"isaac: {isaac['reason']}; fallback mujoco {mujoco['version']} runnable_here=True",
    )


# ============================================================================== scenario 7


async def test_scenario_7_generation_gives_urdf_mjcf_and_gap_report(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No model call: the two-link CAD arm → URDF + MJCF + gap report; the arm with one
    frameless mate → a `.frame` gap naming the mate; the Onshape inference fixture without
    `matedCS` → mates with no frame (the gap), the mated one → frames."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    record = ScenarioRecorder("7 generation", maker, caplog)
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)
    ctx = {"sessionmaker": maker, "artifact_store": app.state.artifact_store}

    generated = await run_generate_sim_model(ctx, arm.request())

    assert generated["status"] == "generated", generated
    async with maker() as session:
        model = await session.get(GraphEntity, uuid.UUID(generated["model_id"]))
        report = gap_report(
            await gather(session, GenerateModelRequest.model_validate(arm.request()))
        )
    assert model is not None
    stored = model.attrs["artifacts"]
    assert (
        stored["urdf"]
        and stored["mjcf"]
        and set(stored["meshes"])
        == {
            "meshes/base.stl",
            "meshes/arm.stl",
            "meshes/tip.stl",
        }
    )
    urdf = await app.state.artifact_store.get(stored["urdf"])
    mjcf = await app.state.artifact_store.get(stored["mjcf"])
    assert urdf.startswith(b"<") and b"<robot" in urdf and b"<mujoco" in mjcf
    gaps = {gap["name"] for gap in model.attrs["gaps"]}
    assert {"tip.mass", "Fm2.limits"} <= gaps, gaps
    assert [p["name"] for p in report["properties"] if p["name"].endswith(".frame")] == [
        "Fm1.frame",
        "Fm2.frame",
    ]

    frameless = await cad_arm(db, client, alice_headers, app, monkeypatch, frames=(True, False))
    async with maker() as session:
        inference = gap_report(
            await gather(session, GenerateModelRequest.model_validate(frameless.request()))
        )
    (frame_gap,) = [gap for gap in inference["gaps"] if gap["name"] == "Fm2.frame"]
    assert "mate" in frame_gap["set_in"]

    plain = mates_from_definition(json.loads((INFERENCE / "assembly_definition.json").read_text()))
    mated = mates_from_definition(
        json.loads((INFERENCE / "assembly_definition_mated_cs.json").read_text())
    )
    assert plain and all(m.frame is None for m in plain)
    assert mated and all(m.frame is not None for m in mated)
    await record.finish(
        0,
        f"URDF {len(urdf)} B, MJCF {len(mjcf)} B, gaps {sorted(gaps)}; frameless mate → "
        f"Fm2.frame gap ({frame_gap['set_in'][:40]}…); fixture: {len(plain)} mates no frame, "
        f"{len(mated)} with frames",
    )


# ============================================================================== scenario 8


async def test_scenario_8_retention_under_a_frozen_clock(
    engine: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    maker, project, user = await _setup(engine)
    record = ScenarioRecorder("8 retention", maker, caplog)
    store = LocalArtifactStore(str(tmp_path))
    robot = uuid.uuid4()
    async with maker() as db:
        old = await _runs(db, store, project, user, robot, 22, ended_at=OLD)
        recent = await _runs(db, store, project, user, robot, 2, ended_at=RECENT)
        real = await _runs(db, store, project, user, robot, 2, ended_at=OLD, origin="live")

    async with maker() as db:
        pruned = await prune_sim_runs(db, store, now=NOW)
        states = {run_id: await _payload_state(db, store, run_id) for run_id in old}
        kept = [await _payload_state(db, store, run_id) for run_id in [*recent, *real]]
        again = await prune_sim_runs(db, store, now=NOW)

    assert pruned.deleted == 4 and [states[r] for r in old[:4]] == ["deleted"] * 4
    assert all(states[r] == "live" for r in old[4:]) and kept == ["live"] * 4
    assert again.deleted == 0
    await record.finish(
        0,
        f"now={NOW:%Y-%m-%d %H:%M}Z: 22 sim @40 d + 2 sim @5 d + 2 real @40 d → "
        f"deleted {pruned.deleted}, kept {pruned.kept}; second pass deleted {again.deleted}",
    )


# ============================================================================== scenario 9


async def test_scenario_9_cross_project_isolation_on_the_park_decide_and_run_paths(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Two teams. A owns a world, ran a routine (a sim Run) and parked a save_world card. B's
    Build turn names A's model and A's session; B decides A's card; B reads A's Run. Every one
    refuses and nothing of A's moves."""
    store = MemoryStore()
    project_a, _ = await gazebo_graph(db, store)
    project_b, _ = await gazebo_graph(db, store)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bench_a, bench_b = await _bench_of(maker, project_a), await _bench_of(maker, project_b)
    assert bench_a.team_id != bench_b.team_id and bench_a.user_id != bench_b.user_id
    async with maker() as session:
        fake = await seed_fake_arm(session, project_a.id, user_id=bench_a.user_id)
        await session.commit()
    await _alias_elbow(maker, fake.parts[2])
    root_a = await _fake_arm_model(maker, project_a.id, fake, store, bench_a.user_id)
    record = ScenarioRecorder("9 cross-project isolation", maker, caplog)
    ledger = SessionsLedger(maker)
    runs = LocalArtifactStore(str(tmp_path / "runs"))
    calls_a = _gazebo_tools(
        bench_a, family="gz", version="8.15.0", ledger=ledger, store=store, runs=runs
    )
    calls_b = _gazebo_tools(bench_b, family="gz", version="8.15.0", ledger=ledger, store=store)
    turn_a = await bench_a.turn(
        ActionMode.DO,
        [
            [
                ("gazebo.open_world", {"world_ref": "demo.sdf"}),
                _gz_call("spawn", model_entity_id=str(root_a.id), name="arm1"),
                _gz_call("run_routine", **SWEEP),
                _gz_call("save_world", dest="saved/demo.sdf"),
            ],
            ["ok"],
        ],
        "Sweep and save.",
    )
    ran = turn_a.of("gazebo.run_routine")
    assert ran.ok and ran.value is not None and ran.value["run"], (ran.error, ran.value)
    run_a = uuid.UUID(ran.value["run"])
    (card_a,) = await bench_a.cards()
    assert (card_a.tool, card_a.project_id) == ("gazebo.save_world", project_a.id)

    # (a) B's Build turn proposes A's model and A's session.
    a_before = len(calls_a)
    turn_b = await bench_b.turn(
        ActionMode.DO,
        [
            [_gz_call("spawn", model_entity_id=str(root_a.id), name="stolen"), _gz_call("stop")],
            ["ok"],
        ],
        "Spawn and stop.",
    )
    for name in ("gazebo.spawn", "gazebo.stop"):
        outcome = turn_b.of(name)
        assert not outcome.ok and outcome.error is not None, (name, outcome.value)
    # A's session is not B's to own: B's stop parks in B (as any non-owned session does), never A.
    assert WAITING in str(turn_b.of("gazebo.stop").error)
    assert WAITING not in str(turn_b.of("gazebo.spawn").error), "A's model was previewed for B"
    assert [op for op, args in calls_b if not args.get("dry_run")] == [], calls_b
    assert len(calls_a) == a_before, "B's turn reached A's companion"
    cards = await bench_a.cards()
    assert [(c.id, c.project_id) for c in cards if c.project_id == project_a.id] == [
        (card_a.id, project_a.id)
    ], "B's turn added nothing to A"
    assert [(c.tool, c.project_id) for c in cards if c.id != card_a.id] == [
        ("gazebo.stop", project_b.id)
    ]
    rows = await ledger.running(project_id=project_a.id, provider="gazebo")
    assert [(r.session_id, r.owner) for r in rows] == [(SESSION, "sol")], "A's session moved"

    # (b) B decides A's parked card.
    async with maker() as session:
        decided = await decide_confirmation(
            session,
            bench_b.registry,
            card_a.id,
            approve=True,
            project_id=bench_b.project_id,
            user_id=bench_b.user_id,
        )
        await session.commit()
    assert not decided.ok and decided.error is not None
    assert decided.error.code == ToolErrorCode.NOT_FOUND, decided.error
    async with maker() as session:
        still = await session.get(ToolConfirmation, card_a.id)
    assert still is not None and still.status is ConfirmationStatus.PENDING
    assert _writes(calls_a, "save_world") == [] and _writes(calls_b, "save_world") == []

    # (c) B reads A's sim Run.
    async with maker() as session:
        assert (await run_store.record(session, project_a.id, run_a)).id == run_a
        with pytest.raises(APIError) as hidden:
            await run_store.record(session, project_b.id, run_a)
    assert hidden.value.status_code == 404
    owners = [(c.tool, "A" if c.project_id == project_a.id else "B") for c in cards]
    await record.finish(
        bench_a.scripted + bench_b.scripted,
        f"B: spawn(A's model) refused, stop(A's session) parked in B, 0 B writes, "
        f"cards {owners}; decide(A's card as B) → {decided.error.code.value}, "
        f"card still {still.status.value}; run_store.record(B, A's run) → 404",
    )
