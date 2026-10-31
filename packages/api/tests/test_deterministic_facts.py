"""SOLUSDEV-321 P1-T2 — `GraphFactSources`, the first tier's DB-backed fact seams.

Every read is scoped to the project the route bound (§7): another project's ids read as nothing,
never as another tenant's facts. A machine's recent commands reach only the member who owns it
(the project card's rule). A latest value needs exactly one channel for the quantity, and a
scene joint is the one bound to the part. The answers that hinge on a read's shape live here
too: a list cut at five, a part filed under a robot category, a position pair stored with its
unit, a read that fails.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fixtures.fake_arm import DEVICE_REF, LIMITS, seed_fake_arm
from solus_api.agent.deterministic_facts import FactPage, GraphFactSources, JointRange
from solus_api.agent.interfaces import EntityRead
from solus_api.checkers.interface import Severity
from solus_api.graph import kinds
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.edges import write_edge
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.hardware.config import (
    EntityHardwareConfig,
    FieldProvenance,
    PartConfig,
    ProvenanceRecord,
    TelemetryChannel,
)
from solus_api.hardware.store import put_entity_config
from solus_api.models import Domain, GraphEntity, SolusSection
from solus_api.orchestration.enums import Complexity
from solus_api.services.activity import record_project_activity
from solus_api.services.environment_divergence import recompute_divergences
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.solus_config import add_text_entry, put_config_entry
from solus_api.services.solus_payloads import Budgets
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_deterministic import _arm, _ask, _StatedLimits
from test_sessions import FakeConn, _manager, _packet, _start
from test_sol_reasoner import _funded_user
from test_solus_layer import _error_meta, _part, _project

Maker = async_sessionmaker[AsyncSession]

_T0 = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _read(maker: Maker, entity_id: uuid.UUID) -> EntityRead:
    async with maker() as db:
        return EntityRead.model_validate(await db.get(GraphEntity, entity_id))


def _scene(
    project_id: uuid.UUID, part: uuid.UUID | None, span: float, **fields: Any
) -> GraphEntity:
    """A scene model whose joint `j3` spans ±`span` rad, bound to `part` when one is given."""
    joint = {"name": "j3", "type": "revolute", "lower": -span, "upper": span}
    return GraphEntity(
        project_id=project_id,
        kind=kinds.BENCH_SCENE_MODEL,
        domain=Domain.SIMULATION,
        origin="manual",
        name="fake scene",
        attrs={
            "model": {"joints": [joint]},
            "bindings": [{"joint": "j3", "part_entity_id": str(part)}] if part else [],
        },
        **fields,
    )


class _SceneToo(_StatedLimits):
    """Stated limits, and a scene joint bound to every part: a fact a decline must not reach."""

    async def scene_joint(self, entity: EntityRead) -> JointRange | None:
        return JointRange(uuid.uuid4(), "j3", -1.0, 1.0, "rad")


class _FailingLimits(GraphFactSources):
    async def part_limits(self, entity: EntityRead) -> dict[str, float | int]:
        raise RuntimeError("fake detail the log must never carry")


async def test_every_read_is_scoped_to_its_own_project(engine: AsyncEngine) -> None:
    """Project B's fake arm, findings, errors, history, samples, scene, budgets, divergences,
    machine and bench session are all real — and project A's seams read every one of them as
    nothing (A's own divergences table, written when its arm was seeded, lists no machine)."""
    maker = _maker(engine)
    mine, theirs = await _project(maker), await _project(maker)
    owner = await _funded_user(maker)
    async with maker() as db:
        await seed_fake_arm(db, mine, user_id=None)
        arm = await seed_fake_arm(db, theirs, user_id=None)
        await raise_finding(
            db,
            theirs,
            FindingSpec(
                rule_id="fake_rule",
                severity=Severity.WARNING,
                source="observer",
                headline="fake finding",
                subjects=[arm.parts[2]],
                domain=Domain.ELECTRICAL,
            ),
        )
        await add_text_entry(
            db,
            theirs,
            SolusSection.ERRORS,
            "fake error",
            author="user",
            created_by=None,
            payload=_error_meta(arm.parts[2], None),
        )
        machine = await upsert_machine(
            db, theirs, owner, "their-companion", MachineIn(hostname="h", os="linux", arch="x")
        )
        db.add(_scene(theirs, arm.parts[2], 1.0))
        await put_config_entry(
            db,
            theirs,
            SolusSection.CONSTRAINTS,
            "budgets",
            Budgets(computed_at=_T0, budgets=[]),
            text="Budgets",
            configured_entity_id=None,
            created_by=None,
            author="system",
        )
        await recompute_divergences(db, theirs)  # the table now lists their machine
        await db.commit()
    buffer = InMemoryTelemetryBuffer()
    await buffer.append(theirs, arm.parts[2], "servo3.current", _T0, 1.5, unit="A")
    plumbing = TelemetryPlumbing(buffer, DbEntityResolver(maker))
    sessions, _ = _manager(theirs)
    conn = FakeConn()
    await _start(sessions, theirs, conn, mode="real", provider="replay", label="theirs")
    await conn.drive(_packet(DEVICE_REF, 0.0, v=1.0))
    servo, robot = await _read(maker, arm.parts[2]), await _read(maker, arm.robot)

    def facts(project_id: uuid.UUID) -> GraphFactSources:
        return GraphFactSources(maker, project_id, owner, telemetry=plumbing, sessions=sessions)

    other, own = facts(mine), facts(theirs)
    assert await other.part_limits(servo) == {}
    assert await other.latest(servo, "current") is None
    assert await other.findings(servo.id) == FactPage(rows=(), more=False)
    assert await other.errors(servo.id) == ()
    assert await other.history(None, servo.id) == FactPage(rows=(), more=False)
    assert await other.machine("their-companion") is None
    assert await other.sessions(robot) == ()
    assert await other.scene_joint(servo) is None
    assert await other.budgets() is None
    unlisted = await other.divergences()
    assert unlisted is None or unlisted.machines == ()
    # The same reads, bound to the project that holds the facts, find every one.
    assert await own.part_limits(servo) == LIMITS
    reading = await own.latest(servo, "current")
    assert reading is not None and (reading.value, reading.unit) == (1.5, "A")
    assert [finding.headline for finding in (await own.findings(servo.id)).rows] == ["fake finding"]
    assert [error.text for error in await own.errors(servo.id)] == ["fake error"]
    assert (await own.history(None, servo.id)).rows
    assert await own.machine("their-companion") is not None
    assert [bench.label for bench in await own.sessions(robot) or ()] == ["theirs"]
    assert await own.scene_joint(servo) is not None
    assert await own.budgets() is not None
    listed = await own.divergences()
    assert listed is not None and [row.machine_id for row in listed.machines] == [machine.id]


async def test_machine_commands_reach_only_their_owner(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _project(maker)
    owner, teammate = await _funded_user(maker), await _funded_user(maker)
    async with maker() as db:
        machine = await upsert_machine(
            db, project_id, owner, "fake-companion", MachineIn(hostname="h", os="linux", arch="x")
        )
        machine.attrs = {
            **machine.attrs,
            "recent_commands": [
                {"command_redacted": "make old", "exit_code": 1},
                {"command_redacted": "make new", "exit_code": 0},
            ],
        }
        await db.commit()

    mine = await GraphFactSources(maker, project_id, owner).machine("fake-companion")
    theirs = await GraphFactSources(maker, project_id, teammate).machine("fake-companion")

    assert mine is not None and theirs is not None
    assert [command["command_redacted"] for command in mine.recent_commands] == [
        "make new",
        "make old",
    ]
    assert theirs.recent_commands == () and theirs.hostname == mine.hostname == "h"


async def test_latest_needs_exactly_one_channel_for_the_quantity(engine: AsyncEngine) -> None:
    """Two channels end in `.current`: which one the person means is not known, so nothing is
    read. One channel answers, with its configured unit when the sample carries none."""
    maker = _maker(engine)
    project_id = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        servo = await db.get(GraphEntity, arm.parts[2])
        assert servo is not None
        await put_entity_config(
            db,
            project_id,
            servo,
            EntityHardwareConfig(
                entity_id=servo.id,
                component=PartConfig(
                    telemetry=[
                        TelemetryChannel(name="servo3.current", unit="A"),
                        TelemetryChannel(name="aux.current", unit="A"),
                        TelemetryChannel(name="servo3.voltage", unit="V"),
                    ]
                ),
                provenance={"component": ProvenanceRecord(by=FieldProvenance.USER)},
            ),
            expected_version=1,
            created_by=None,
        )
        await db.commit()
    buffer = InMemoryTelemetryBuffer()
    for signal in ("servo3.current", "aux.current", "servo3.voltage"):
        await buffer.append(project_id, arm.parts[2], signal, _T0, 7.0)
    facts = GraphFactSources(
        maker,
        project_id,
        uuid.uuid4(),
        telemetry=TelemetryPlumbing(buffer, DbEntityResolver(maker)),
    )
    part = await _read(maker, arm.parts[2])

    assert await facts.latest(part, "current") is None
    assert await facts.latest(part, "temperature") is None
    reading = await facts.latest(part, "voltage")
    assert reading is not None and (reading.signal, reading.unit) == ("servo3.voltage", "V")


async def test_scene_joint_is_the_joint_bound_to_the_part(engine: AsyncEngine) -> None:
    """The query filters scenes by their bindings (jsonb containment), so fifty scenes that
    bind nothing cannot hide the one that does. A second binding that agrees on the range
    still answers; one that disagrees declines: which one is meant is not known."""
    maker = _maker(engine)
    project_id = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        # Ids that sort before any random one: a scan capped by id never got past them.
        db.add_all(_scene(project_id, None, 1.0, id=uuid.UUID(int=n)) for n in range(1, 51))
        bound = _scene(project_id, arm.parts[2], 2.5)
        db.add(bound)
        await db.commit()
    facts = GraphFactSources(maker, project_id, uuid.uuid4())
    servo_3 = await _read(maker, arm.parts[2])

    assert await facts.scene_joint(servo_3) == JointRange(bound.id, "j3", -2.5, 2.5, "rad")
    assert await facts.scene_joint(await _read(maker, arm.parts[1])) is None
    for span, agreed in ((2.5, True), (1.0, False)):
        async with maker() as db:
            db.add(_scene(project_id, arm.parts[2], span))
            await db.commit()
        joint = await facts.scene_joint(servo_3)
        assert (joint is not None and (joint.lower, joint.upper) == (-2.5, 2.5)) is agreed, span


async def test_cut_lists_say_so(engine: AsyncEngine) -> None:
    """Open findings and history show their first five, newest first; when more exist the
    answer says so in one fixed phrase, and five or fewer end plainly."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    servo_4 = arm.parts[3]
    async with maker() as db:
        gauge = await _part(db, project_id, "fake gauge 9")
        for subject, count in ((servo_4, 6), (gauge.id, 5)):
            for n in range(count):
                spec = FindingSpec(
                    rule_id=f"fake_rule_{n}",
                    severity=Severity.WARNING,
                    source="observer",
                    headline=f"fake finding {n}",
                    subjects=[subject],
                    domain=Domain.ELECTRICAL,
                )
                await raise_finding(db, project_id, spec)
                await record_project_activity(db, project_id, "fake.touched", entity_ids=[subject])
        await db.commit()

    findings = await _ask(maker, project_id, "any open findings on servo 4?")
    history = await _ask(maker, project_id, "show me the history of servo 4")
    assert findings is not None and findings.text.endswith("), and older ones.")
    assert len(findings.citations) == 5
    assert history is not None and history.text.endswith(", and older ones.")
    assert history.text.count("`fake.touched`") == 5
    for question in ("any open findings on gauge 9?", "show me the history of gauge 9"):
        five = await _ask(maker, project_id, question)
        assert five is not None and "older ones" not in five.text, question


async def test_a_category_owned_part_counts_and_resolves(engine: AsyncEngine) -> None:
    """A part filed under one of the robot's categories (robot → category → part, the
    store's own shape) counts toward the robot, and a machine question about it finds the
    robot's host; the category itself is never counted."""
    maker = _maker(engine)
    project_id, arm = await _arm(maker)
    owner = await _funded_user(maker)
    async with maker() as db:
        category, gripper = (
            GraphEntity(
                project_id=project_id,
                kind=kind,
                domain=Domain.ELECTRICAL,
                origin="manual",
                name=name,
                attrs={"robot_id": str(arm.robot)} if kind == kinds.ROBOT_CATEGORY else {},
            )
            for kind, name in ((kinds.ROBOT_CATEGORY, "fake wrist"), (kinds.PART, "gripper 7"))
        )
        db.add_all([category, gripper])
        await db.flush()
        for src_id, dst_id in ((arm.robot, category.id), (category.id, gripper.id)):
            await write_edge(
                db,
                project_id=project_id,
                src_id=src_id,
                dst_id=dst_id,
                relation_type="contains",
                origin="manual",
                confidence=1.0,
                evidence=[],
                created_by=None,
            )
        robot = await db.get(GraphEntity, arm.robot)
        assert robot is not None
        robot.attrs = {**robot.attrs, "host_machine_id": "fake-companion"}
        bench = MachineIn(hostname="fake-bench", os="linux", arch="arm64")
        await upsert_machine(db, project_id, owner, "fake-companion", bench)
        await db.commit()

    parts = await _ask(
        maker,
        project_id,
        "how many parts does Fake arm have?",
        robot_id=arm.robot,
        tier=Complexity.HARD,
    )
    assert parts is not None and parts.text.startswith("7 parts in `Fake arm`")
    assert "`gripper 7`" in parts.text and "fake wrist" not in parts.text
    host = await _ask(
        maker,
        project_id,
        "which machine is gripper 7 on?",
        facts=GraphFactSources(maker, project_id, owner),
        tier=Complexity.HARD,
    )
    assert host is not None and "`fake-bench`" in host.text


async def test_position_limits_read_one_suffixed_pair_in_its_unit(engine: AsyncEngine) -> None:
    """Position limits stored only as one `position_min_<u>`/`position_max_<u>` pair read in
    that unit (none when the suffix is no unit), ahead of the scene joint. Two pairs, or half
    of one, decline: which is meant is not known, so the scene is not consulted either."""
    maker = _maker(engine)
    project_id, _ = await _arm(maker)
    question = "what are the position limits of servo 3?"

    def stated(limits: Mapping[str, float | int]) -> _SceneToo:
        facts = _SceneToo(maker, project_id, uuid.uuid4())
        facts.stated = dict(limits)
        return facts

    degrees = stated({"position_min_deg": -90, "position_max_deg": 90})
    answer = await _ask(maker, project_id, question, facts=degrees)
    assert answer is not None and "-90 to 90 deg (its hardware config)" in answer.text
    radians = await _ask(maker, project_id, f"{question[:-1]} in rad?", facts=degrees)
    assert radians is not None and "-1.5708 to 1.5708 rad" in radians.text
    steps = stated({"position_min_steps2": 0, "position_max_steps2": 4095})
    unitless = await _ask(maker, project_id, question, facts=steps)
    assert unitless is not None and ": 0 to 4095 (its hardware config)" in unitless.text
    scene = await _ask(maker, project_id, question, facts=stated({"stall_current_a": 2.0}))
    assert scene is not None and scene.sources == ("scene",)
    for declined in (
        {"position_min_deg": -90, "position_max_deg": 90, "position_min_rad": -1},
        {"position_min_deg": -90},
    ):
        assert await _ask(maker, project_id, question, facts=stated(declined)) is None, declined


async def test_a_failed_read_declines_and_logs_only_its_seam_type_and_project(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """A read that raises declines like a missing fact. The warning names the seam, the
    exception's type and the project: never its message or a traceback, which may carry
    the project's data."""
    maker = _maker(engine)
    project_id, _ = await _arm(maker)
    facts = _FailingLimits(maker, project_id, uuid.uuid4())

    with caplog.at_level(logging.WARNING, logger="solus.agent.deterministic"):
        answer = await _ask(maker, project_id, "what is the stall current of servo 3?", facts=facts)

    assert answer is None
    logged = [r for r in caplog.records if r.name == "solus.agent.deterministic"]
    assert [record.getMessage() for record in logged] == [
        f"first tier declined: part_limits read failed (RuntimeError) project={project_id}"
    ]
    assert all(record.exc_info is None for record in logged)
    assert "fake detail" not in caplog.text
