"""SOLUSDEV-321 P1-T2 — SOL's first tier answers lookups from facts, with no model call.

Each shape runs on the real planner (`plan_scope` over the project's own index and the real
graph pull) and the DB-backed `GraphFactSources`, mostly on the fake arm
(tests/fixtures/fake_arm.py). A shape declines — returns None — on a tie, an unknown quantity
or no fact, and the turn falls through to the model with the same scope.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pint
import pytest
from fastapi import FastAPI
from fixtures.fake_arm import DEVICE_REF, FakeArm, seed_fake_arm
from httpx import AsyncClient
from solus_api.agent.deterministic import (
    _GUIDE_NOTES,
    DeterministicAnswer,
    _quote_name,
    answer_first_tier,
)
from solus_api.agent.deterministic_facts import GraphFactSources, Reading
from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.interfaces import ContextBudget, EntityRead, GraphContext, GraphScope
from solus_api.agent.reason import _CITATION_RE, Anchor
from solus_api.agent.runtime import LlmRunner
from solus_api.agent.stream import AgentEventType
from solus_api.agent.turn_scope import ScopeInputs, TurnScope, index_search, plan_scope
from solus_api.checkers.interface import Severity
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.edges import write_edge
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.hardware.library import Library, PartDefinition, PinSpec
from solus_api.models import (
    ConversationTurn,
    CreditLedger,
    Domain,
    GraphEntity,
    SolMode,
    SolusSection,
    TurnRole,
)
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.enums import Complexity
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.solus_config import add_text_entry, put_config_entry
from solus_api.services.solus_payloads import (
    BudgetLine,
    Budgets,
    DivergenceGroup,
    DivergenceItem,
    EnvironmentDivergencesDoc,
    MachineDivergences,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_sessions import FakeConn, _manager, _packet, _start
from test_sol import _create_conversation, _parse_sse
from test_sol import _project as _api_project
from test_sol_reasoner import _ctx, _funded_user
from test_solus_layer import _error_meta, _part, _project

Maker = async_sessionmaker[AsyncSession]

_CONFIG = load_orchestration_config()
_T0 = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
#: The brief's unit-token rule, restated here so the test does not trust the module's copy.
_UNIT_TOKEN = re.compile(r"[A-Za-zµΩ°]+([*/·][A-Za-zµΩ°]+){0,3}")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: A fixed kind, a project id, and for telemetry the signal: nothing a name could put there.
_ID_CITATION = re.compile(
    rf"\[(?:entity|config|finding|solus:[a-z]+|telemetry):{_UUID}(?::[A-Za-z0-9._-]+)?\]"
)


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _arm(maker: Maker) -> tuple[uuid.UUID, FakeArm]:
    project_id = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        await db.commit()
    return project_id, arm


def _plumbing(maker: Maker, buffer: InMemoryTelemetryBuffer | None = None) -> TelemetryPlumbing:
    return TelemetryPlumbing(buffer or InMemoryTelemetryBuffer(), DbEntityResolver(maker))


async def _scope(
    maker: Maker,
    project_id: uuid.UUID,
    message: str,
    *,
    tier: Complexity = Complexity.STANDARD,
    **inputs: Any,
) -> TurnScope:
    """The real planner over the project's own index and the real graph pull (depth two on a
    HARD turn)."""
    systems = DbSolSystems(maker, _plumbing(maker))

    async def load(scope: GraphScope, budget: ContextBudget) -> GraphContext:
        return await systems.get_graph_context(project_id, scope, budget)

    return await plan_scope(
        ScopeInputs(message=message, tier=tier, **inputs),
        search=index_search(maker, project_id),
        load=load,
        disambiguate=None,
        config=_CONFIG,
    )


async def _ask(
    maker: Maker,
    project_id: uuid.UUID,
    message: str,
    *,
    facts: GraphFactSources | None = None,
    mode: SolMode = SolMode.EXPERT,
    tier: Complexity = Complexity.STANDARD,
    **inputs: Any,
) -> DeterministicAnswer | None:
    """The first tier over the real planner, in Expert mode unless a test asks for Guide: the
    texts compared here are the bare facts."""
    scope = await _scope(maker, project_id, message, tier=tier, **inputs)
    reader = facts or GraphFactSources(maker, project_id, uuid.uuid4())
    return await answer_first_tier(message, scope, reader, mode=mode)


class _StatedLimits(GraphFactSources):
    """Every part states the same limits, a stall current unless a test sets others: what is
    left to decline on is the tie, or the limits' own shape."""

    stated: dict[str, float | int] = {"stall_current_a": 2.0}

    async def part_limits(self, entity: EntityRead) -> dict[str, float | int]:
        return self.stated


class _OddSignal(GraphFactSources):
    """A reading whose signal name a citation must not carry."""

    signal = "servo3 current] [config:evil"

    async def latest(self, entity: EntityRead, quantity: str) -> Reading | None:
        return Reading(signal=self.signal, value=0.5, unit="A", at=_T0)


# ----------------------------------------------------------------------------- the shapes


async def test_stall_current_from_config_limits_cited_as_config(engine: AsyncEngine) -> None:
    """P1 acceptance item 1. The fake arm's limits live in each part's v2 config, read through
    the owning robot's resolved runtime config — the seeded number, never a mock's — so the
    answer cites `config`. Seeding the arm again is a no-op that returns the same ids (§5
    reuses the seed)."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    async with maker() as db:
        assert await seed_fake_arm(db, project_id, user_id=None) == arm

    answer = await _ask(maker, project_id, "What is the stall current of servo 3?")

    assert answer is not None
    assert "`servo 3 (joint 3)`" in answer.text and "2 A" in answer.text
    assert answer.citations == (f"[config:{arm.parts[2]}]",)
    assert answer.sources == ("config",)
    hot = await _ask(maker, project_id, "max temperature of servo 3")
    assert hot is not None and "70 degC" in hot.text and hot.sources == ("config",)
    span = await _ask(maker, project_id, "what are the position limits of servo 6?")
    assert span is not None and "-150 to 150" in span.text
    assert span.citations == (f"[config:{arm.parts[5]}]",)


async def test_what_commands_actuator_uses_commands_edge_with_firmware_symbol(
    engine: AsyncEngine,
) -> None:
    """P1 acceptance item 2: the `commands` edge in the planned scope, with its stored
    `firmware_symbol` evidence — no second graph pull, no model."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)

    answer = await _ask(maker, project_id, "what commands actuator 5?")

    assert answer is not None
    assert "`fw/fake_arm.ino` commands `actuator 5 (joint 5)`" in answer.text
    assert "firmware_symbol `fw/fake_arm.ino:15`" in answer.text
    assert answer.citations == (f"[entity:{arm.code_file}]", f"[entity:{arm.parts[4]}]")
    assert answer.sources == ("graph",)


async def test_pwm_pins_from_definition_pins(engine: AsyncEngine) -> None:
    """Pins come from the part definition (`definition.pins`), here a fake one in a fake
    library. The fake parts carry no `definition_id`, so nothing states their pins."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    async with maker() as db:
        brain = await db.get(GraphEntity, arm.brain)
        assert brain is not None
        brain.attrs = {**brain.attrs, "definition_id": "fake-board"}
        await db.commit()
    board = PartDefinition(
        id="fake-board",
        name="Fake board",
        category="controllers",
        pins=[
            PinSpec(name="P1", capabilities=["pwm", "gpio"]),
            PinSpec(name="P2", capabilities=["adc"]),
            PinSpec(name="P3", capabilities=["pwm"]),
        ],
    )
    facts = GraphFactSources(
        maker,
        project_id,
        uuid.uuid4(),
        library=Library(parts={"fake-board": board}, platforms={}),
    )

    for message in ("which pins on fake brain support PWM?", "what pwm pins does fake brain have?"):
        answer = await _ask(maker, project_id, message, facts=facts, mentions=(arm.brain,))
        assert answer is not None, message
        assert "`P1`" in answer.text and "`P3`" in answer.text and "`P2`" not in answer.text
        assert answer.citations == (f"[entity:{arm.brain}]",)
        assert answer.sources == ("definition",)
    assert await _ask(maker, project_id, "which pins on servo 3 support pwm?", facts=facts) is None


async def test_which_bus_and_machine(engine: AsyncEngine) -> None:
    """The bus is the `drives` edge's source; the machine is the robot's host, and its recent
    commands reach only the member who owns it (the project card's rule)."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    owner, teammate = await _funded_user(maker), await _funded_user(maker)
    async with maker() as db:
        robot = await db.get(GraphEntity, arm.robot)
        assert robot is not None
        robot.attrs = {**robot.attrs, "host_machine_id": "fake-companion"}
        machine = await upsert_machine(
            db,
            project_id,
            owner,
            "fake-companion",
            MachineIn(hostname="fake-bench", os="linux", arch="arm64"),
        )
        machine.attrs = {
            **machine.attrs,
            "recent_commands": [{"command_redacted": "make flash-fake", "exit_code": 0}],
        }
        await db.commit()

    bus = await _ask(maker, project_id, "which bus is servo 3 on?")
    assert bus is not None and "`servo 3 (joint 3)` is on bus `fake bus`" in bus.text
    assert bus.citations == (f"[entity:{arm.bus}]", f"[entity:{arm.parts[2]}]")
    assert bus.sources == ("graph",)

    question = "which machine is Fake arm on?"
    mine, theirs = [
        await _ask(
            maker,
            project_id,
            question,
            facts=GraphFactSources(maker, project_id, user),
            robot_id=arm.robot,
        )
        for user in (owner, teammate)
    ]
    assert mine is not None and theirs is not None
    assert "`fake-bench`" in mine.text and "`make flash-fake`" in mine.text
    assert "`fake-bench`" in theirs.text and "flash-fake" not in theirs.text
    assert mine.citations == theirs.citations == (f"[entity:{machine.id}]",)
    assert mine.sources == ("machine",)


async def test_latest_value_from_buffer(engine: AsyncEngine) -> None:
    """The newest sample of the part's one channel for the quantity, read entity-scoped from
    the telemetry buffer with its unit; another project's samples never answer."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    servo_3 = arm.parts[2]
    buffer = InMemoryTelemetryBuffer()
    await buffer.append(project_id, servo_3, "servo3.current", _T0 - timedelta(seconds=1), 0.3)
    await buffer.append(project_id, servo_3, "servo3.current", _T0, 0.42, unit="A")
    await buffer.append(project_id, servo_3, "servo3.temperature", _T0, 41.5, unit="degC")
    await buffer.append(uuid.uuid4(), servo_3, "servo3.voltage", _T0, 9.9, unit="V")
    facts = GraphFactSources(maker, project_id, uuid.uuid4(), telemetry=_plumbing(maker, buffer))

    current = await _ask(maker, project_id, "what is the latest current of servo 3?", facts=facts)
    assert current is not None
    assert "0.42 A" in current.text and "2026-10-26 12:00:00 UTC" in current.text
    assert "0.3" not in current.text and "`servo3.current`" in current.text
    assert current.citations == (f"[telemetry:{servo_3}:servo3.current]",)
    assert current.sources == ("telemetry",)
    hot = await _ask(maker, project_id, "what's the current temperature of servo 3?", facts=facts)
    assert hot is not None and "41.5 degC" in hot.text
    assert await _ask(maker, project_id, "latest voltage of servo 3", facts=facts) is None


async def test_unit_conversion_pint(engine: AsyncEngine) -> None:
    """A number and two unit tokens from the message, converted by pint; a stated fact asked for
    in another unit. A dimension mismatch or a unit pint does not know declines."""
    maker = _maker(engine)
    project_id, _ = await _arm(maker)

    bare = await _ask(maker, project_id, "convert 2.5 A to mA")
    assert bare is not None and bare.text == "2.5 A = 2500 mA."
    assert bare.citations == () and bare.sources == ()
    angle = await _ask(maker, project_id, "what is 150 deg in rad?")
    assert angle is not None and angle.text == "150 deg = 2.61799 rad."
    stall = await _ask(maker, project_id, "what is the stall current of servo 3 in mA?")
    assert stall is not None and "2000 mA" in stall.text and stall.sources == ("config",)
    for declined in (
        "convert 2 A to V",
        "convert 2 A to blorps",
        "what is the stall current of servo 3 in V?",
        "what are the position limits of servo 3 in rad?",
    ):
        assert await _ask(maker, project_id, declined) is None, declined


async def test_can_supply_run_load_from_budgets(engine: AsyncEngine) -> None:
    """The stored `constraints/budgets` line for the rail the person names: ok is yes, exceeded
    is no; an unknown line, an unnamed or unmatched rail declines."""
    maker = _maker(engine)
    project_id = await _project(maker)
    lines = [
        BudgetLine(
            name="power:+5V", current=3.2, limit=5, unit="A", source="fake rails", status="ok"
        ),
        BudgetLine(
            name="power:12V", current=9, limit=6, unit="A", source="fake rails", status="exceeded"
        ),
        BudgetLine(name="power:3V3", current=0.4, unit="A", source="fake rails", status="unknown"),
    ]
    async with maker() as db:
        entry = await put_config_entry(
            db,
            project_id,
            SolusSection.CONSTRAINTS,
            "budgets",
            Budgets(computed_at=_T0, budgets=lines),
            text="Budgets",
            configured_entity_id=None,
            created_by=None,
            author="system",
        )
        await db.commit()

    yes = await _ask(maker, project_id, "can the 5V rail run the load?")
    assert yes is not None and yes.text.startswith("Yes")
    assert "`+5V`" in yes.text and "3.2 A" in yes.text and "5 A" in yes.text
    assert yes.citations == (f"[solus:constraints:{entry.id}]",) and yes.sources == ("budgets",)
    no = await _ask(maker, project_id, "can the 12V supply power the servos?")
    assert no is not None and no.text.startswith("No") and "9 A" in no.text
    for declined in ("can the 3V3 rail run the load?", "can the 48V rail run the load?"):
        assert await _ask(maker, project_id, declined) is None, declined


async def test_open_findings_errors_and_history(engine: AsyncEngine) -> None:
    """Open findings observing the part, the `.solus` errors that blame it and the project
    history naming it — each its own read, each cited by id; a read that finds nothing is
    itself the answer."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    servo_2 = arm.parts[1]
    async with maker() as db:
        finding = await raise_finding(
            db,
            project_id,
            FindingSpec(
                rule_id="tracking_error_stall",
                severity=Severity.WARNING,
                source="observer",
                headline="fake servo 2 held position while commanded to move",
                subjects=[servo_2],
                domain=Domain.ELECTRICAL,
            ),
        )
        error = await add_text_entry(
            db,
            project_id,
            SolusSection.ERRORS,
            "fake stall during the replay",
            author="user",
            created_by=None,
            payload=_error_meta(servo_2, None),
        )
        await db.commit()

    findings = await _ask(maker, project_id, "any open findings on servo 2?")
    assert findings is not None and "held position while commanded" in findings.text
    assert findings.citations == (f"[finding:{finding.id}]",)
    assert findings.sources == ("finding",)
    errors = await _ask(maker, project_id, "any errors on servo 2?")
    assert errors is not None and "`fake stall during the replay`" in errors.text
    assert errors.citations == (f"[solus:errors:{error.id}]",) and errors.sources == ("solus",)
    history = await _ask(maker, project_id, "what changed on servo 2 in the last 2 hours?")
    assert history is not None and "`config.bumped`" in history.text
    assert history.citations == (f"[entity:{servo_2}]",) and history.sources == ("history",)
    quiet = await _ask(maker, project_id, "any open findings on servo 4?")
    assert quiet is not None and quiet.text == "No open findings on `servo 4 (joint 4)`."


async def test_will_it_run_here_from_divergences(engine: AsyncEngine) -> None:
    """ "Here" is the asker's own machine in the stored divergences table: its causes, or none.
    Without a machine of one's own in the table nothing says what "here" is."""
    maker = _maker(engine)
    project_id = await _project(maker)
    me, teammate = await _funded_user(maker), await _funded_user(maker)
    async with maker() as db:
        mine, theirs = [
            await upsert_machine(
                db, project_id, user, companion, MachineIn(hostname=host, os="linux", arch=arch)
            )
            for user, companion, host, arch in (
                (me, "my-companion", "fake-laptop", "x86_64"),
                (teammate, "their-companion", "fake-rig", "arm64"),
            )
        ]
        doc = EnvironmentDivergencesDoc(
            computed_at=_T0,
            spec_entry_id=None,
            machines=[
                MachineDivergences(
                    machine_id=mine.id,
                    hostname="fake-laptop",
                    causes=[
                        DivergenceGroup(
                            cause="missing",
                            items=[DivergenceItem(name="fake-numerics", expected=">=2")],
                        )
                    ],
                ),
                MachineDivergences(machine_id=theirs.id, hostname="fake-rig", causes=[]),
            ],
        )
        entry = await put_config_entry(
            db,
            project_id,
            SolusSection.ENVIRONMENT,
            "divergences",
            doc,
            text="Environment divergences",
            configured_entity_id=None,
            created_by=None,
            author="system",
        )
        await db.commit()

    here = await _ask(
        maker, project_id, "will it run here?", facts=GraphFactSources(maker, project_id, me)
    )
    assert here is not None
    assert "`fake-laptop`" in here.text and "`fake-numerics`" in here.text
    assert "fake-rig" not in here.text
    assert here.citations == (f"[solus:environment:{entry.id}]",)
    assert here.sources == ("divergences",)
    clean = await _ask(
        maker,
        project_id,
        "will this run on my machine?",
        facts=GraphFactSources(maker, project_id, teammate),
    )
    assert clean is not None and clean.text.startswith("No divergence")
    assert "`fake-rig`" in clean.text
    assert await _ask(maker, project_id, "will it run here?") is None


async def test_robot_status_from_sessions(engine: AsyncEngine) -> None:
    """A robot is live when an active bench session streams its device ref (the project card's
    mapping); none active is itself the answer; no session source at all declines."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    live, _ = _manager(project_id)
    conn = FakeConn()
    await _start(live, project_id, conn, mode="real", provider="replay", label="fake replay")
    await conn.drive(_packet(DEVICE_REF, 0.0, v=1.0))
    idle, _ = _manager(project_id)

    question = "is Fake arm running?"
    running = await _ask(
        maker,
        project_id,
        question,
        facts=GraphFactSources(maker, project_id, uuid.uuid4(), sessions=live),
        robot_id=arm.robot,
    )
    assert running is not None and "`fake replay`" in running.text
    assert running.citations == (f"[entity:{arm.robot}]",) and running.sources == ("session",)
    stopped = await _ask(
        maker,
        project_id,
        "what is the status of Fake arm?",
        facts=GraphFactSources(maker, project_id, uuid.uuid4(), sessions=idle),
        robot_id=arm.robot,
    )
    assert stopped is not None and stopped.text == "`Fake arm` has no active bench session."
    assert await _ask(maker, project_id, question, robot_id=arm.robot) is None


async def test_counting_shape(engine: AsyncEngine) -> None:
    """A how-many question counts entities in the planned scope — a kind for a generic noun,
    whole-word names otherwise — inside the named container; never from pixels."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)

    servos = await _ask(
        maker, project_id, "how many servos does Fake arm have?", robot_id=arm.robot
    )
    assert servos is not None and servos.text.startswith("5 servos in `Fake arm`")
    assert "actuator" not in servos.text
    assert servos.citations == (f"[entity:{arm.robot}]",) and servos.sources == ("graph",)
    parts = await _ask(maker, project_id, "how many parts does Fake arm have?", robot_id=arm.robot)
    assert parts is not None and parts.text.startswith("6 parts in `Fake arm`")
    assert await _ask(maker, project_id, "how many motors does Fake arm have?") is None


# ------------------------------------------------------------------- declines and containment


async def test_declines_on_tie_unknown_or_no_fact(engine: AsyncEngine) -> None:
    """Review focus 4: two parts tie for "servo 3" — both reach the scope as `name_match` — and
    the first tier declines although either part's limits would answer. A quantity or unit it
    does not know, and a fact nobody stated, decline too."""
    maker = _maker(engine)
    project_id = await _project(maker)
    async with maker() as db:
        leader = await _part(db, project_id, "servo 3 (leader)")
        follower = await _part(db, project_id, "servo 3 (follower)")
        await _part(db, project_id, "servo 7 (wrist)")
        await db.commit()
    stated = _StatedLimits(maker, project_id, uuid.uuid4())
    question = "what is the stall current of servo 3?"

    scope = await _scope(maker, project_id, question)
    assert set(scope.anchors) == {
        Anchor(id=leader.id, reason="name_match"),
        Anchor(id=follower.id, reason="name_match"),
    }
    assert await answer_first_tier(question, scope, stated, mode=SolMode.EXPERT) is None
    lone = await _ask(maker, project_id, "what is the stall current of servo 7?", facts=stated)
    assert lone is not None and "`servo 7 (wrist)`" in lone.text

    arm_project, _ = await _arm(maker)
    for unknown in (
        "what is the latest humidity of servo 3?",
        "what is the stall torque of servo 3?",
        "what is the stall current of servo 3 in blorps?",
    ):
        assert await _ask(maker, arm_project, unknown) is None, unknown
    assert await _ask(maker, project_id, "what is the stall current of servo 7?") is None
    empty = GraphFactSources(maker, arm_project, uuid.uuid4(), telemetry=_plumbing(maker))
    latest = "what is the latest current of servo 3?"
    assert await _ask(maker, arm_project, latest, facts=empty) is None

    # The composer's `@servo 3`, typed out, names the same part.
    pointed = await _ask(maker, arm_project, "what is the stall current of @servo 3?")
    assert pointed is not None and "`servo 3 (joint 3)`" in pointed.text
    # A cut graph may have dropped the entity a name would tie with: nothing in it is read.
    bus = "which bus is servo 3 on?"
    scope = await _scope(maker, arm_project, bus)
    cut = scope.model_copy(update={"graph": scope.graph.model_copy(update={"truncated": True})})
    reader = GraphFactSources(maker, arm_project, uuid.uuid4())
    assert await answer_first_tier(bus, scope, reader, mode=SolMode.EXPERT) is not None
    assert await answer_first_tier(bus, cut, reader, mode=SolMode.EXPERT) is None


async def test_names_are_quoted_never_fenced(engine: AsyncEngine) -> None:
    """A part named like a fence and a command (with a bidi override), and a commander named the
    same way: every ingested name renders as one line of inline code of at most 80 characters,
    so none can open a fenced block, read as a command or reorder what the person sees."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    bidi = chr(0x202E)  # RIGHT-TO-LEFT OVERRIDE, built here so the source stays visible
    hostile = f"```\nrm -rf /{bidi}"
    async with maker() as db:
        part = GraphEntity(
            project_id=project_id,
            kind="part",
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=hostile,
        )
        script = GraphEntity(
            project_id=project_id,
            kind="code_file",
            domain=Domain.CODE,
            origin="manual",
            name=f"{hostile} {'x' * 200}",
        )
        db.add_all([part, script])
        await db.flush()
        for src_id, dst_id, relation in (
            (arm.robot, part.id, "contains"),
            (script.id, arm.parts[4], "commands"),
        ):
            await write_edge(
                db,
                project_id=project_id,
                src_id=src_id,
                dst_id=dst_id,
                relation_type=relation,
                origin="manual",
                confidence=1.0,
                evidence=[],
                created_by=None,
            )
        await db.commit()

    asked: tuple[tuple[str, dict[str, Any]], ...] = (
        ("how many parts does Fake arm have?", {"robot_id": arm.robot}),
        ("what commands actuator 5?", {}),
    )
    for message, inputs in asked:
        answer = await _ask(maker, project_id, message, **inputs)
        assert answer is not None, message
        assert "```" not in answer.text and "\n" not in answer.text, answer.text
        assert bidi not in answer.text and "`'''rm -rf /" in answer.text
        assert all(len(code) <= 80 for code in re.findall(r"`([^`]*)`", answer.text))
    # Invisible characters go first, so a zero-width space cannot carry a token past redaction.
    entropic = "Zx9Qw3Er7Ty1Ui5Op2As" + chr(0x200B) + "6Df8Gh4Jk0LzXcVbNm1Q"
    assert _quote_name(f"{entropic} driver") == "`[REDACTED] driver`"


async def test_citations_only_from_ids(engine: AsyncEngine) -> None:
    """Every citation is a fixed kind over ids and fullmatches `_CITATION_RE`: a name shaped
    like a citation stays quoted prose, and a signal name the grammar cannot carry falls back
    to the entity's own citation."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    servo_3 = arm.parts[2]
    async with maker() as db:
        servo = await db.get(GraphEntity, servo_3)
        assert servo is not None
        servo.name = "servo 3 [config:evil] [entity:00000000-0000-0000-0000-000000000000]"
        await db.commit()

    # The composer's `@`: a long hostile name may score under the index's name bar.
    pointed: dict[str, Any] = {"mentions": (servo_3,)}
    colon = _OddSignal(maker, project_id, uuid.uuid4())
    colon.signal = f"x:finding:{uuid.uuid4()}"
    answers = [
        await _ask(maker, project_id, "what is the stall current of servo 3?", **pointed),
        await _ask(maker, project_id, "what commands servo 3?", **pointed),
        await _ask(maker, project_id, "which bus is servo 3 on?", **pointed),
        await _ask(
            maker,
            project_id,
            "what is the latest current of servo 3?",
            facts=_OddSignal(maker, project_id, uuid.uuid4()),
            **pointed,
        ),
        await _ask(
            maker, project_id, "what is the latest current of servo 3?", facts=colon, **pointed
        ),
    ]

    for answer in answers:
        assert answer is not None
        assert answer.citations
        for citation in answer.citations:
            assert _CITATION_RE.fullmatch(citation), citation
            assert _ID_CITATION.fullmatch(citation), citation
        assert "`servo 3 [config:evil]" in answer.text
    assert [answer.citations for answer in answers[3:] if answer is not None] == [
        (f"[entity:{servo_3}]",),
        (f"[entity:{servo_3}]",),
    ]


async def test_pint_never_evaluates_message_text(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Message text never reaches pint's expression evaluator: a magnitude is `float()` of a
    regex-matched number, and only tokens that fullmatch the unit grammar reach
    `parse_units`. Code-shaped and exponent-bomb units decline without evaluation."""
    maker = _maker(engine)
    project_id, _ = await _arm(maker)
    parsed: list[str] = []
    parse_units = pint.UnitRegistry.parse_units

    def spy(self: pint.UnitRegistry, input_string: str, *args: Any, **kwargs: Any) -> Any:
        parsed.append(input_string)
        return parse_units(self, input_string, *args, **kwargs)

    def evaluated(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("message text reached pint's expression evaluator")

    monkeypatch.setattr(pint.UnitRegistry, "parse_units", spy)
    monkeypatch.setattr(pint.UnitRegistry, "parse_expression", evaluated)
    monkeypatch.setattr(pint.UnitRegistry, "__call__", evaluated)

    for hostile in (
        "convert __import__('os') to mA",
        "convert 2 __import__('os') to mA",
        "convert 1 meter ** 1000000 to mm",
        "what is 1 meter ** 1000000 in mm?",
        "convert 2 A to mA; import os",
        "what is the stall current of servo 3 in __import__('os')?",
    ):
        assert await _ask(maker, project_id, hostile) is None, hostile
    assert parsed == []
    converted = await _ask(maker, project_id, "convert 2 A to mA")
    assert converted is not None and converted.text == "2 A = 2000 mA."
    assert parsed and all(_UNIT_TOKEN.fullmatch(token) for token in parsed), parsed


# --------------------------------------------------------------- the runner and the route


class _NoModel:
    """Every provider adapter: reaching one at all fails the test."""

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the model layer was reached; the first tier answers alone")


_NO_MODEL = {provider: _NoModel() for provider in ("anthropic", "openai", "google")}


async def test_zero_model_calls_when_answered(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """P1 acceptance item 1 through the real runner: the planned scope's manifest,
    `answer_source` graph, then the message — no tool frame, no prompt, no `model call start`
    line, no adapter reached, nothing debited."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    plumbing = _plumbing(maker)
    ctx = await _ctx(engine, "what is the stall current of servo 3?")
    assert ctx.user_id is not None
    turn = replace(
        ctx,
        project_id=project_id,
        systems=DbSolSystems(maker, plumbing),
        facts=GraphFactSources(maker, project_id, ctx.user_id, telemetry=plumbing),
    )
    async with maker() as db:
        ledger = select(CreditLedger.id).where(CreditLedger.user_id == ctx.user_id)
        before = (await db.scalars(ledger)).all()

    with caplog.at_level(logging.INFO, logger="solus.orchestration.gateway"):
        events = [event async for event in LlmRunner(adapters=_NO_MODEL).run(turn)]

    assert [event.type for event in events] == [
        AgentEventType.CONTEXT_USED,
        AgentEventType.ANSWER_SOURCE,
        AgentEventType.MESSAGE,
    ]
    assert not [r for r in caplog.records if r.getMessage().startswith("model call start")]
    manifest, source, message = (event.data for event in events)
    citation = f"[config:{arm.parts[2]}]"
    assert {"id": str(arm.parts[2]), "reason": "name_match"} in manifest["anchors"]
    assert [layer["layer"] for layer in manifest["layers"]] == ["graph"]
    assert source == {"source": "graph", "sources": ["config"], "citations": [citation]}
    assert "2 A" in message["content"] and message["citations"] == [citation]
    async with maker() as db:
        assert (await db.scalars(ledger)).all() == before


async def test_guide_mode_adds_one_fixed_note_expert_does_not(engine: AsyncEngine) -> None:
    """CLAUDE.md §2 item 5, through the real runner with no model reachable: Expert gets the
    fact alone; Guide gets the same fact and ONE fixed, Solus-authored sentence on where it
    comes from, never a name or a number from the project. Every shape keeps its citations
    and sources in both modes, and the sentence follows the answer's source."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    plumbing = _plumbing(maker)
    ctx = await _ctx(engine, "what is the stall current of servo 3?")
    assert ctx.user_id is not None
    turn = replace(
        ctx,
        project_id=project_id,
        systems=DbSolSystems(maker, plumbing),
        facts=GraphFactSources(maker, project_id, ctx.user_id, telemetry=plumbing),
    )
    said: dict[SolMode, str] = {}
    for mode in SolMode:
        runner = LlmRunner(adapters=_NO_MODEL).run(replace(turn, sol_mode=mode))
        said[mode] = [event async for event in runner][-1].data["content"]

    note = _GUIDE_NOTES["config"]
    assert said[SolMode.GUIDE] == f"{said[SolMode.EXPERT]} {note}"
    assert "2 A" in said[SolMode.EXPERT] and "servo" not in note
    shapes: tuple[tuple[str, dict[str, Any], str], ...] = (
        ("which bus is servo 3 on?", {}, "graph"),
        ("how many parts does Fake arm have?", {"robot_id": arm.robot}, "count"),
        ("any open findings on servo 4?", {}, "finding"),
        ("convert 2.5 A to mA", {}, "unit"),
    )
    for message, inputs, source in shapes:
        expert = await _ask(maker, project_id, message, **inputs)
        guide = await _ask(maker, project_id, message, mode=SolMode.GUIDE, **inputs)
        assert expert is not None, message
        assert guide == replace(expert, text=f"{expert.text} {_GUIDE_NOTES[source]}"), message
    for sentence in _GUIDE_NOTES.values():
        assert not re.search(r"[0-9`]", sentence) and sentence.endswith("."), sentence


async def test_turn_persisted_with_deterministic_envelope(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Through the SOL route: the route hands the runner its facts, the first tier answers, and
    the stored assistant turn carries the envelope — `answer_source`, citations and sources.
    No tool frame streams, so no tool turn is stored or counted; no model call starts and no
    credit is debited."""
    _, project = await _api_project(client, alice_headers)
    arm = await seed_fake_arm(db, uuid.UUID(project["id"]), user_id=None)
    await db.commit()
    app.state.agent_runner = LlmRunner(adapters=_NO_MODEL)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    ledger = select(func.count()).select_from(CreditLedger)
    debits = await db.scalar(ledger)

    with caplog.at_level(logging.INFO, logger="solus.orchestration.gateway"):
        reply = await client.post(
            f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages",
            json={"content": "what is the stall current of servo 3?"},
            headers=alice_headers,
        )

    assert reply.status_code == 200, reply.text
    assert [name for name, _ in _parse_sse(reply.text)] == [
        "context_used",
        "answer_source",
        "message",
        "done",
    ]
    assert not [r for r in caplog.records if r.getMessage().startswith("model call start")]
    assert await db.scalar(ledger) == debits
    citation = f"[config:{arm.parts[2]}]"
    turns = (
        await db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == uuid.UUID(conversation["id"]))
            .order_by(ConversationTurn.created_at)
        )
    ).all()
    (assistant,) = [turn for turn in turns if turn.role is TurnRole.ASSISTANT]
    assert assistant.attrs["answer_source"] == "graph"
    assert assistant.attrs["citations"] == [citation]
    assert assistant.attrs["sources"] == ["config"]
    assert "2 A" in assistant.content and assistant.attrs["tool_calls"] == 0
    assert [turn for turn in turns if turn.role is TurnRole.TOOL] == []
