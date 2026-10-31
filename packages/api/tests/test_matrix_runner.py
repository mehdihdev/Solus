"""SOLUSDEV-321 P3-T3 — the matrix run (`checkers/matrix_runner.py`).

One bounded read of the project; every rule's results kept on the edges they judge; each `fail`
raised as a checker finding, and each fact the project lacks as ONE standing `info` finding per
(rule, entity) — never one per edge — which a later run resolves once it judges that entity with
the fact stated. A dry run, or a run given its own facts, writes nothing, and no run publishes
`graph.changed`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import timedelta
from typing import Any, Final

import pytest
from fixtures.fake_arm import CODE_PATH, ROBOT_NAME, FakeArm, seed_fake_arm
from fixtures.matrix_divider import seed_divider
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers import matrix_runner
from solus_api.checkers.cells import RULES_BY_ID
from solus_api.checkers.cells.software_mechanical import COMMANDED, CommandedRangeVsJointLimit
from solus_api.checkers.cells.software_software import PackageVersionConflict
from solus_api.checkers.fact_store import ExpectedValue, FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import RuleResult
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.core.db import build_sessionmaker
from solus_api.graph import kinds
from solus_api.graph.edges import annotate_edge, write_edge
from solus_api.graph.neighborhood import MAX_EDGE_SCAN
from solus_api.graph.read_scope import GraphReadScope, bind_scope
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Membership,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
    utcnow,
)
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.sim_ladder import LOCAL_PROVIDERS, should_simulate
from solus_contracts.relations import EdgeOrigin, MatrixCell, RelationType
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_live_publisher import RecordingHub, commit_then_drain

RULE: Final = "commanded_range_vs_joint_limit"
COMMANDS: Final = RelationType.COMMANDS.value
#: A literal goal past the fake arm's ±150 deg position limit (its parts' config).
GOAL: Final[dict[str, Any]] = {
    "min": 200.0,
    "max": 200.0,
    "unit": "deg",
    "min_ref": f"{CODE_PATH}:13",
    "max_ref": f"{CODE_PATH}:13",
}
#: Review focus 5: the large project, at full size.
LARGE_ENTITIES: Final = 3_000
LARGE_EDGES: Final = MAX_EDGE_SCAN + 500
BULK_FILES: Final = 100
#: `connectors/worker.py` registers `run_matrix_checkers` with this timeout.
JOB_TIMEOUT_S: Final = 300.0


async def _matrix_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project to run the matrix over, and its team."""
    tag = uuid.uuid4().hex[:8]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@ex.com")
    team = Team(name=f"matrix-{tag}")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=f"matrix-{tag}", created_by=user.id)
    db.add(project)
    await db.flush()
    return project.id, team.id


async def _arm_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, FakeArm]:
    """A project holding the fake arm: one code file commanding six parts, no goal stated."""
    project_id, team_id = await _matrix_project(db)
    arm = await seed_fake_arm(db, project_id, user_id=None)
    await db.commit()
    return project_id, team_id, arm


async def _command_goal(
    db: AsyncSession,
    project_id: uuid.UUID,
    arm: FakeArm,
    part: uuid.UUID,
    goal: dict[str, Any] = GOAL,
    source_id: uuid.UUID | None = None,
) -> GraphEdge:
    """The arm's code commanding `part` to the literal `goal` (`commands.attrs.commanded`)."""
    return await write_edge(
        db,
        project_id=project_id,
        src_id=arm.code_file,
        dst_id=part,
        relation_type=COMMANDS,
        origin=EdgeOrigin.MANUAL.value,
        confidence=1.0,
        evidence=[],
        created_by=None,
        attrs={"commanded": goal},
        source_id=source_id,
    )


async def _matrix_findings(
    db: AsyncSession, project_id: uuid.UUID, rule_id: str | None = None
) -> list[GraphEntity]:
    """The project's live findings, oldest first; one rule's when named."""
    stmt = select(GraphEntity).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind == kinds.FINDING,
        GraphEntity.deleted_at.is_(None),
    )
    if rule_id is not None:
        stmt = stmt.where(GraphEntity.attrs["rule_id"].astext == rule_id)
    return list(await db.scalars(stmt.order_by(GraphEntity.created_at, GraphEntity.id)))


async def _commands_rows(
    db: AsyncSession, project_id: uuid.UUID, src_id: uuid.UUID, dst_id: uuid.UUID
) -> list[GraphEdge]:
    """Every live `commands` row from `src_id` to `dst_id`, whatever its source."""
    return list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.src_id == src_id,
                GraphEdge.dst_id == dst_id,
                GraphEdge.relation_type == COMMANDS,
                GraphEdge.deleted_at.is_(None),
            )
        )
    )


async def _project_edges(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEdge]:
    return list(await db.scalars(select(GraphEdge).where(GraphEdge.project_id == project_id)))


def _rule_items(edge: GraphEdge, rule_id: str = RULE) -> list[dict[str, Any]]:
    """The edge's `checker_results` items of one rule."""
    return [item for item in edge.attrs.get("checker_results", []) if item["rule_id"] == rule_id]


def _bulk_row(project_id: uuid.UUID, kind: str, domain: Domain, name: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "kind": kind,
        "domain": domain,
        "name": name,
        "origin": "manual",
        "attrs": {},
    }


async def test_results_cached_on_edge_and_findings_raised(db: AsyncSession) -> None:
    """A goal past the part's limit fails on every live row of that relation — another source's
    row too (R43) — with its status and time; the fail is ONE checker finding on the code file and
    the part, in the rule's cell. The arm's goal-less edges each carry their `unknown_input`."""
    project_id, team_id, arm = await _arm_project(db)
    source = Source(
        project_id=project_id,
        team_id=team_id,
        type=SourceType.LOCAL,
        name="fw",
        status=SourceStatus.CONNECTED,
        config={},
    )
    db.add(source)
    await db.flush()
    goal_part = arm.parts[2]
    await _command_goal(db, project_id, arm, goal_part)
    await _command_goal(db, project_id, arm, goal_part, source_id=source.id)
    await db.commit()

    report = await run_matrix(db, project_id)
    await db.commit()

    rows = await _commands_rows(db, project_id, arm.code_file, goal_part)
    assert len(rows) == 2
    for row in rows:
        (item,) = _rule_items(row)
        assert (item["status"], item["severity"]) == ("fail", "warning")
        assert item["evidence"]["commanded_max"] == 200.0 and item["at"].endswith("Z")
    for part in arm.parts:
        if part == goal_part:
            continue
        (row,) = await _commands_rows(db, project_id, arm.code_file, part)
        (item,) = _rule_items(row)
        assert item["status"] == "unknown_input"
        assert item["evidence"]["missing"]["name"] == "commanded"
    (fail,) = [
        f for f in await _matrix_findings(db, project_id, RULE) if f.attrs["severity"] != "info"
    ]
    assert (fail.attrs["source"], fail.attrs["severity"], fail.attrs["count"]) == (
        "checker",
        "warning",
        1,
    )
    assert fail.attrs["subjects"] == [str(arm.code_file), str(goal_part)]
    assert fail.attrs["matrix_cell"] == MatrixCell.SOFTWARE_MECHANICAL.value
    assert (report.findings_raised, report.edges_annotated) == (1, 7)


async def test_info_per_rule_entity_not_per_edge(db: AsyncSession) -> None:
    """The arm's code commands six parts and states no goal: six edges lack `commanded`, and the
    run raises ONE standing info for (rule, the code file) with `bucket = None`, never one per
    edge. A fact the whole project lacks is one info per rule on the robot (R61)."""
    project_id, _, arm = await _arm_project(db)

    report = await run_matrix(db, project_id)
    await db.commit()

    (info,) = await _matrix_findings(db, project_id, RULE)
    assert (info.attrs["severity"], info.attrs["source"], info.attrs["status"]) == (
        "info",
        "checker",
        "open",
    )
    assert info.attrs["subjects"] == [str(arm.code_file)] and info.attrs["evidence"]["edges"] == 6
    assert info.attrs["matrix_cell"] == MatrixCell.SOFTWARE_MECHANICAL.value
    key = f"{project_id}|{RULE}|{arm.code_file}|"
    assert info.canonical_key == hashlib.sha1(key.encode()).hexdigest()  # bucket None
    (waiting,) = await _matrix_findings(db, project_id, "gains_vs_resonance")
    assert waiting.attrs["subjects"] == [str(arm.robot)]
    found = await _matrix_findings(db, project_id)
    assert len({(f.attrs["rule_id"], *f.attrs["subjects"]) for f in found}) == len(found)
    assert (report.infos_raised, report.findings_raised) == (len(found), 0)


async def test_info_findings_do_not_grow_across_syncs(db: AsyncSession) -> None:
    """A second sync that still states no goal bumps the standing info's `count` and records the
    new change signal (when each source last synced); it opens no second node. A run no sync
    caused (M110, P3-T3 fix 1: the signal has not moved) raises nothing again: `count` counts
    the syncs that still lack the fact."""
    project_id, team_id, _ = await _arm_project(db)
    synced = utcnow() - timedelta(hours=1)
    source = Source(
        project_id=project_id,
        team_id=team_id,
        type=SourceType.LOCAL,
        name="fw",
        status=SourceStatus.CONNECTED,
        config={},
        last_synced_at=synced,
    )
    db.add(source)
    await db.commit()
    await run_matrix(db, project_id)
    await db.commit()
    opened = {f.id for f in await _matrix_findings(db, project_id)}
    (info,) = await _matrix_findings(db, project_id, RULE)
    assert info.attrs["evidence"]["signal"] == {str(source.id): synced.isoformat()}

    unsynced = await run_matrix(db, project_id)  # a person's edit: no source synced since
    await db.commit()
    assert (info.attrs["count"], unsynced.infos_raised) == (1, 0)

    resynced = synced + timedelta(minutes=30)
    source.last_synced_at = resynced
    await db.commit()
    await run_matrix(db, project_id)
    await db.commit()

    assert {f.id for f in await _matrix_findings(db, project_id)} == opened
    assert info.attrs["count"] == 2
    assert info.attrs["evidence"]["signal"] == {str(source.id): resynced.isoformat()}


async def test_info_text_names_field_and_set_in(db: AsyncSession) -> None:
    """The headline names the rule, the fact, the entity and where a person states it. With no
    robot to anchor a fact the whole project lacks, it is a line of the run's report and no
    finding (R61)."""
    project_id, _, _ = await _arm_project(db)
    waiting = RULES_BY_ID["gains_vs_resonance"]
    (need,) = waiting.needs.facts

    await run_matrix(db, project_id)
    await db.commit()

    (info,) = await _matrix_findings(db, project_id, RULE)
    assert info.attrs["headline"] == (
        f"could not check {RULE}: commanded unknown for {CODE_PATH}; set it in {COMMANDED.set_in}"
    )
    assert info.attrs["evidence"]["missing"] == [COMMANDED.model_dump()]
    (robot_info,) = await _matrix_findings(db, project_id, waiting.rule_id)
    assert robot_info.attrs["headline"] == (
        f"could not check {waiting.rule_id}: {need.name} unknown for {ROBOT_NAME}; "
        f"set it in {need.set_in}"
    )

    bare, _ = await _matrix_project(db)
    await db.commit()
    report = await run_matrix(db, bare)
    await db.commit()

    assert await _matrix_findings(db, bare) == []
    line = f"could not check {waiting.rule_id}: {need.name} unknown; set it in {need.set_in}"
    assert line in report.notes


async def test_dry_run_writes_nothing(db: AsyncSession) -> None:
    """`dry_run`, or the caller's own facts (P4's backward loop): the results come back and
    nothing is written — no edge result, no finding."""
    project_id, _, arm = await _arm_project(db)
    await _command_goal(db, project_id, arm, arm.parts[2])
    await db.commit()
    before = {row.id: dict(row.attrs) for row in await _project_edges(db, project_id)}

    dry = await run_matrix(db, project_id, dry_run=True)
    told = await run_matrix(db, project_id, facts=FactStore())
    await db.commit()

    assert [warning.checker_id for warning in dry.warnings] == [RULE]
    assert (dry.edges_annotated, dry.findings_raised, dry.infos_raised) == (0, 0, 0)
    (unstated,) = told.results[RULE]  # the caller's empty facts: the store-wide unknown
    assert unstated.status == "unknown_input" and told.warnings == ()
    assert await _matrix_findings(db, project_id) == []
    assert {row.id: dict(row.attrs) for row in await _project_edges(db, project_id)} == before


async def _simulated_bracket(
    db: AsyncSession, project_id: uuid.UUID, name: str, fraction: float
) -> GraphEntity:
    """A bracket a rung-1 simulation found at `fraction` of its yield: its `sim_result`, and the
    expected values `record_sim_result` writes on it. Its own facts let the mesh check run."""
    bracket = GraphEntity(
        project_id=project_id,
        kind=kinds.PART,
        domain=Domain.MECHANICAL,
        origin="manual",
        name=name,
        attrs={
            "section": {"shape": "rect", "dims_mm": [30.0, 5.0]},
            "load": {"force_n": 1173.0, "arm_m": 0.025},
            "material": {"name": "fake-6061", "yield_mpa": 276.0, "density_kg_m3": 2700.0},
        },
    )
    db.add(bracket)
    await db.flush()
    run = GraphEntity(
        project_id=project_id,
        kind=kinds.SIM_RESULT,
        domain=Domain.SIMULATION,
        origin="system",
        name=f"stress_mpa, yield_fraction — {name}",
        attrs={"subject_id": str(bracket.id), "rung": 1},
    )
    db.add(run)
    await db.flush()
    expected = {
        "yield_fraction": {"value": fraction, "unit": None, "sim_result_id": str(run.id)},
        "stress_mpa": {"value": fraction * 276.0, "unit": "MPa", "sim_result_id": str(run.id)},
    }
    bracket.attrs = {**bracket.attrs, "expected": expected}
    return bracket


async def test_inconclusive_results_reach_should_simulate(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R97 (P4-T5): after the rules, the run hands its `inconclusive` results to the ladder as
    `rule` and keeps what it proposes on its report and in its log line, a dry run included.
    Nothing runs: no provider is asked to run, and no simulation result is written."""
    project_id, _ = await _matrix_project(db)
    near = await _simulated_bracket(db, project_id, "near bracket", 0.85)
    await _simulated_bracket(db, project_id, "easy bracket", 0.15)
    await db.commit()
    heard: list[tuple[str, list[tuple[str, tuple[uuid.UUID, ...]]]]] = []

    def spying(results: list[RuleResult], **kwargs: Any) -> Any:
        heard.append((kwargs["trigger"], [(r.status, r.subjects) for r in results]))
        return should_simulate(results, **kwargs)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a matrix run ran a simulation")

    monkeypatch.setattr(matrix_runner, "should_simulate", spying)
    for provider in LOCAL_PROVIDERS:
        monkeypatch.setattr(type(provider), "run", forbidden)

    with caplog.at_level(logging.INFO, logger="solus.checkers.matrix_runner"):
        report = await run_matrix(db, project_id)
    await db.commit()
    dry = await run_matrix(db, project_id, dry_run=True)

    verdicts = {r.subjects: r.status for r in report.results["bracket_strength_at_joint"]}
    assert sorted(verdicts.values()) == ["inconclusive", "pass"]
    assert heard == [("rule", [("inconclusive", (near.id,))])] * 2
    (proposal,) = report.proposals
    assert (proposal.trigger, proposal.subject_id, proposal.quantity) == (
        "rule",
        near.id,
        "yield_fraction",
    )
    assert (proposal.rung, proposal.target, proposal.decision) == (3, "mesh_interference", "run")
    assert dry.proposals == report.proposals
    assert "proposals=1" in caplog.text
    runs = select(func.count()).where(
        GraphEntity.project_id == project_id, GraphEntity.kind == kinds.SIM_RESULT
    )
    assert await db.scalar(runs) == 2  # the two seeded runs, and no other


async def test_a_run_given_its_callers_facts_asks_the_ladder_nothing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor 7: a run handed its caller's facts, as `dry_run_change`'s two dry runs are, is
    judged and nothing more. The ladder is not asked, so no provider's `can_answer` runs on it
    (the mesh check's parses the mesh, in the request)."""
    project_id, _ = await _matrix_project(db)
    near = await _simulated_bracket(db, project_id, "near bracket", 0.85)
    await db.commit()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a run given its caller's facts asked the ladder")

    monkeypatch.setattr(matrix_runner, "should_simulate", forbidden)
    facts = FactStore(
        expected_values={near.id: {"yield_fraction": ExpectedValue(0.85, None, None)}}
    )

    report = await run_matrix(db, project_id, facts=facts, dry_run=True)

    assert [r.status for r in report.results["bracket_strength_at_joint"]] == ["inconclusive"]
    assert report.proposals == ()


def test_results_that_state_no_band_never_crowd_out_one_that_does() -> None:
    """`MAX_LADDER_RESULTS` bounds the ladder's work a run, and only an inconclusive result that
    states the band's quantity (R94) counts against it: the ladder can read no other. A project
    full of unit gaps still has its bracket near its yield asked about."""
    bracket = EntityRead(
        id=uuid.uuid4(),
        kind=kinds.PART,
        domain="mechanical",
        name="bracket",
        attrs={
            "section": {"shape": "rect", "dims_mm": [30.0, 5.0]},
            "load": {"force_n": 1173.0, "arm_m": 0.025},
            "material": {"name": "fake-6061", "yield_mpa": 276.0, "density_kg_m3": 2700.0},
        },
    )
    gap = RuleResult(
        status="inconclusive",
        message="the two units do not compare",
        subjects=(bracket.id,),
        evidence={"unit": "deg", "limit_unit": "rad"},
    )
    near = RuleResult(
        status="inconclusive",
        message="near its yield",
        subjects=(bracket.id,),
        evidence={"quantity": "yield_fraction", "value": 0.85, "limit": 1.0, "rung": 1},
    )
    report = matrix_runner.MatrixReport(
        results={"gaps": (gap,) * (matrix_runner.MAX_LADDER_RESULTS + 1), "near": (near,)},
        warnings=(),
        truncated=False,
    )
    graph = GraphContext(entities=[bracket], edges=[])

    (proposal,) = matrix_runner._proposals(uuid.uuid4(), report, graph, FactStore(), queued=False)

    assert (proposal.subject_id, proposal.quantity, proposal.rung) == (
        bracket.id,
        "yield_fraction",
        3,
    )


async def test_runner_never_publishes_graph_changed(db: AsyncSession, engine: AsyncEngine) -> None:
    """A run's commit publishes the findings it raised (`finding.raised`) and never a
    `graph.changed`: the fan-out would wake the very trigger that runs it."""
    project_id, _, _ = await _arm_project(db)
    hub = RecordingHub()
    maker = build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]

    async with maker() as session:
        await run_matrix(session, project_id)
        await commit_then_drain(session)

    seen = {frame_type for _, frame_type in hub.seen()}
    assert "finding.raised" in seen and "graph.changed" not in seen


async def test_bounded_on_large_project(db: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    """Review focus 5 at full size: 3,000 entities and more `commands` edges than
    `MAX_EDGE_SCAN`. The run reads at most the cap and logs it, writes one list per edge it read
    and none past it, raises ONE standing info per (rule, entity) — for the commanded fact one per
    code file, never one per edge — and finishes well inside the job's 300 s."""
    project_id, _, arm = await _arm_project(db)
    seeded = await db.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == project_id, GraphEntity.domain != Domain.WORKSPACE)
    )
    assert seeded is not None
    files = [
        _bulk_row(project_id, kinds.CODE_FILE, Domain.CODE, f"fw/bulk_{n}.ino")
        for n in range(BULK_FILES)
    ]
    parts = [
        _bulk_row(project_id, kinds.PART, Domain.ELECTRICAL, f"bulk part {n}")
        for n in range(LARGE_ENTITIES - seeded - BULK_FILES)
    ]
    await db.execute(insert(GraphEntity), [*files, *parts])
    await db.execute(
        insert(GraphEdge),
        [
            {
                "project_id": project_id,
                "src_id": files[n % BULK_FILES]["id"],
                "dst_id": parts[n % len(parts)]["id"],
                "relation_type": COMMANDS,
                "domain_pair": "code<->electrical",
                "confidence": 1.0,
                "origin": "manual",
                "attrs": {},
            }
            for n in range(LARGE_EDGES)
        ],
    )
    await db.commit()

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="solus.checkers.matrix_runner"):
        report = await run_matrix(db, project_id)
        await db.commit()
    elapsed = time.monotonic() - started

    commands = (GraphEdge.project_id == project_id, GraphEdge.relation_type == COMMANDS)
    bare = await db.scalar(
        select(func.count()).where(*commands, ~GraphEdge.attrs.has_key("checker_results"))
    )
    assert report.truncated and "matrix run capped" in caplog.text
    assert report.edges_annotated <= MAX_EDGE_SCAN
    assert bare is not None and report.edges_annotated + bare == LARGE_EDGES + len(arm.parts)
    assert len(await _matrix_findings(db, project_id, RULE)) == BULK_FILES + 1  # one per file
    found = await _matrix_findings(db, project_id)
    assert len({(f.attrs["rule_id"], *f.attrs["subjects"]) for f in found}) == len(found)
    logging.getLogger(__name__).warning("run_matrix on the large project: %.1f s", elapsed)
    assert elapsed < JOB_TIMEOUT_S / 3, f"run_matrix took {elapsed:.1f} s"


async def test_info_resolves_once_judged_and_never_for_what_a_capped_run_skipped(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R63: once the goals are stated, the code file's standing info is resolved by the system —
    only by a run that judged those edges. A run capped below them resolves nothing, and (m3,
    P3-T3 fix 1) raises no info for the relation its cap hid: a report line says so instead."""
    project_id, _, arm = await _arm_project(db)
    await run_matrix(db, project_id)
    await db.commit()
    (info,) = await _matrix_findings(db, project_id, RULE)
    for part in arm.parts:
        await _command_goal(db, project_id, arm, part, goal={**GOAL, "min": 10.0, "max": 20.0})
    await db.commit()

    monkeypatch.setattr(matrix_runner, "MAX_EDGE_SCAN", 0)
    capped = await run_matrix(db, project_id)
    await db.commit()
    assert capped.truncated and capped.infos_resolved == 0
    assert info.attrs["status"] == "open"
    assert [f.attrs["subjects"] for f in await _matrix_findings(db, project_id, RULE)] == [
        [str(arm.code_file)]
    ]
    assert any(note.startswith(f"could not check {RULE}: commands") for note in capped.notes)

    monkeypatch.undo()
    report = await run_matrix(db, project_id)
    await db.commit()

    assert (info.attrs["status"], info.attrs["resolved_by"]) == ("resolved", "system")
    assert report.infos_resolved == 1  # the code file's, the one standing info of the rule
    assert [
        _rule_items(row)[0]["status"]
        for row in await _project_edges(db, project_id)
        if _rule_items(row)
    ] == ["pass"] * 6


async def test_a_run_keeps_other_rules_items_and_drops_its_own_stale_ones(
    db: AsyncSession,
) -> None:
    """A run over some cells keeps the other cells' results on an edge; a rule's own result on an
    edge it no longer judges is removed (docs/api/relations.md §2)."""
    project_id, _, arm = await _arm_project(db)
    await _command_goal(db, project_id, arm, arm.parts[2])
    await db.commit()
    await run_matrix(db, project_id)
    await db.commit()
    (row,) = await _commands_rows(db, project_id, arm.code_file, arm.parts[2])
    assert [item["rule_id"] for item in row.attrs["checker_results"]] == [RULE]

    await run_matrix(db, project_id, cells={MatrixCell.MECHANICAL_MECHANICAL})
    await db.commit()
    assert [item["rule_id"] for item in row.attrs["checker_results"]] == [RULE]

    robot = await db.get(GraphEntity, arm.robot)
    assert robot is not None
    robot.deleted_at = utcnow()  # no robot, no runtime config: the rule judges no edge
    await db.commit()
    await run_matrix(db, project_id, cells={MatrixCell.SOFTWARE_MECHANICAL})
    await db.commit()
    assert row.attrs["checker_results"] == []


async def test_the_write_phase_takes_the_project_lock_before_any_edge_row(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I2 (P3-T3 fix 1): one lock order everywhere. A review acceptance locks the project and then
    writes edges; the run's reads take no row lock, and its write phase takes the project lock
    before it locks any edge row."""
    order: list[str] = []

    async def locking(session: AsyncSession, project_id: uuid.UUID) -> None:
        order.append("project")
        await lock_project(session, project_id)

    async def annotating(*args: Any, **kwargs: Any) -> GraphEdge | None:
        order.append("edge")
        return await annotate_edge(*args, **kwargs)

    monkeypatch.setattr("solus_api.checkers.matrix_runner.lock_project", locking)
    monkeypatch.setattr("solus_api.checkers.matrix_runner.annotate_edge", annotating)
    project_id, _, _ = await _arm_project(db)

    await run_matrix(db, project_id)
    await db.commit()

    assert order[0] == "project" and "edge" in order


async def test_a_run_never_waits_for_an_edge_row_another_writer_holds(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """NB1 (P3-T3 fix 2, R68): a sync locks edge rows and only then takes the project lock, which a
    run holds first, so the run never waits for an edge row. One another writer holds is skipped
    this run (counted, logged once) and judged at the next, which writes it."""
    project_id, _, arm = await _arm_project(db)
    (held,) = await _commands_rows(db, project_id, arm.code_file, arm.parts[2])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as sync:
        await sync.execute(select(GraphEdge.id).where(GraphEdge.id == held.id).with_for_update())
        with caplog.at_level(logging.WARNING, logger="solus.checkers.matrix_runner"):
            report = await asyncio.wait_for(run_matrix(db, project_id), timeout=10)
            await db.commit()
        await sync.rollback()

    assert (report.edges_annotated, report.edges_skipped) == (5, 1)
    assert "not kept for 1 edge(s) another writer holds" in caplog.text
    again = await run_matrix(db, project_id)
    await db.commit()
    assert (again.edges_annotated, again.edges_skipped) == (1, 0)


async def test_an_oversized_fail_is_trimmed_or_skipped_and_the_run_goes_on(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """I3 (P3-T3 fix 1): `FindingSpec` refuses evidence past 16 KiB. A fail whose evidence lists
    thousands of items is cut to the first `MAX_EVIDENCE_LIST`, with the count beside them; one
    the cut cannot bound is logged and skipped. Either way the run completes and its other
    findings land."""
    project_id, _, arm = await _arm_project(db)
    drift = [{"name": f"pkg{n}", "version": "1.0." + "9" * 80} for n in range(2_000)]
    told = (
        RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message="2,000 packages drifted",
            subjects=(arm.code_file,),
            evidence={"machine": "m1", "causes": {"version_drift": drift}},
        ),
        RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message="no cut bounds this",
            subjects=(arm.robot,),
            evidence={"blob": "x" * 20_000},
        ),
    )

    def scripted(self: object, graph: object, facts: object) -> list[RuleResult]:
        return list(told)

    monkeypatch.setattr(PackageVersionConflict, "evaluate", scripted)
    with caplog.at_level(logging.WARNING, logger="solus.checkers.matrix_runner"):
        report = await run_matrix(db, project_id)
        await db.commit()

    (drifted,) = await _matrix_findings(db, project_id, "package_version_conflict")
    causes = drifted.attrs["evidence"]["causes"]
    assert len(causes["version_drift"]) == matrix_runner.MAX_EVIDENCE_LIST
    assert causes["version_drift_count"] == len(drift)
    assert report.findings_raised == 1 and "matrix finding not raised" in caplog.text
    assert await _matrix_findings(db, project_id, RULE)  # the run's other findings landed


async def test_two_rows_that_disagree_raise_their_finding_once(db: AsyncSession) -> None:
    """m5 (P3-T3 fix 1): two rows of one relation can disagree, when two sources state two goals,
    so the rule fails the same (rule, subjects) twice with two messages. A run still raises that
    finding once: its `count` grows by one a run."""
    project_id, team_id, arm = await _arm_project(db)
    source = Source(
        project_id=project_id,
        team_id=team_id,
        type=SourceType.LOCAL,
        name="fw",
        status=SourceStatus.CONNECTED,
        config={},
    )
    db.add(source)
    await db.flush()
    further = {**GOAL, "min": 250.0, "max": 250.0}
    await _command_goal(db, project_id, arm, arm.parts[2])
    await _command_goal(db, project_id, arm, arm.parts[2], goal=further, source_id=source.id)
    await db.commit()

    report = await run_matrix(db, project_id)
    await db.commit()

    fails = [
        f for f in await _matrix_findings(db, project_id, RULE) if f.attrs["severity"] != "info"
    ]
    assert [f.attrs["count"] for f in fails] == [1] and report.findings_raised == 1


async def test_a_run_resolves_only_standing_infos(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m4 (P3-T3 fix 1): a run resolves the standing infos it judged, which it knows by the mark
    only they carry (`evidence.missing`). It never resolves a rule's one-subject fail that happens
    to be `info`: that finding stays a person's to close."""
    project_id, _, arm = await _arm_project(db)
    told = [RuleResult(status="fail", message="an advisory fail", subjects=(arm.code_file,))]

    def scripted(self: object, graph: object, facts: object) -> list[RuleResult]:
        return list(told)

    monkeypatch.setattr(PackageVersionConflict, "evaluate", scripted)
    await run_matrix(db, project_id)
    await db.commit()
    (fail,) = await _matrix_findings(db, project_id, "package_version_conflict")
    assert fail.attrs["severity"] == "info"

    told[:] = [RuleResult(status="pass", message="fine now", subjects=(arm.code_file,))]
    report = await run_matrix(db, project_id)
    await db.commit()

    assert fail.attrs["status"] == "open" and report.infos_resolved == 0


async def test_a_rerun_rewrites_only_the_edges_whose_verdict_moved(db: AsyncSession) -> None:
    """m1 (P3-T3 fix 1): an item that says what the edge's old item said IS the old item, its `at`
    included, so a run rewrites only the edges whose verdict moved."""
    project_id, _, arm = await _arm_project(db)
    first = await run_matrix(db, project_id)
    await db.commit()
    (row,) = await _commands_rows(db, project_id, arm.code_file, arm.parts[2])
    (said,) = _rule_items(row)

    again = await run_matrix(db, project_id)
    await db.commit()
    assert (first.edges_annotated, again.edges_annotated) == (6, 0)
    assert _rule_items(row) == [said]

    await _command_goal(db, project_id, arm, arm.parts[2])  # a goal is stated: one verdict moves
    await db.commit()
    moved = await run_matrix(db, project_id)
    await db.commit()
    assert moved.edges_annotated == 1 and [i["status"] for i in _rule_items(row)] == ["fail"]


async def test_a_writing_run_judges_the_shared_view_under_any_bound_scope(
    db: AsyncSession,
) -> None:
    """m2 (P3-T3 fix 1): what a writing run keeps is everyone's, so `run_matrix` itself judges the
    project's shared view, whatever read scope its caller bound; a dry run reads the caller's."""
    project_id, team_id, arm = await _arm_project(db)
    base, branch = (
        Source(
            project_id=project_id,
            team_id=team_id,
            type=SourceType.LOCAL,
            name=name,
            status=SourceStatus.CONNECTED,
            config={},
        )
        for name in ("fw", "fw on a branch")
    )
    db.add_all([base, branch])
    await db.flush()
    code = await db.get(GraphEntity, arm.code_file)
    assert code is not None
    code.source_id = base.id  # a branch view swaps `base` out, and the arm's code with it
    await db.commit()

    with bind_scope(GraphReadScope(project_id, replacements=((base.id, branch.id),))):
        dry = await run_matrix(db, project_id, dry_run=True)
        await run_matrix(db, project_id)
    await db.commit()

    assert all(result.edge_ref is None for result in dry.results[RULE])  # the branch's view
    (info,) = await _matrix_findings(db, project_id, RULE)
    assert info.attrs["subjects"] == [str(arm.code_file)]  # the shared view's


async def test_the_entity_cap_keeps_what_the_rules_read(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m8 (P3-T3 fix 1): when the entity cap binds, a run keeps first the kinds the facts are read
    off (robots, scene models, components, requirements), then the entities a judged relation
    touches, and only then the rest, oldest first. A project whose first sync brought a pile of
    vendored files still has its arm judged."""
    project_id, _ = await _matrix_project(db)
    vendored = [
        GraphEntity(
            project_id=project_id,
            kind=kinds.CODE_FILE,
            domain=Domain.CODE,
            origin="manual",
            name=f"vendor/lib_{n}.py",
        )
        for n in range(20)
    ]
    db.add_all(vendored)
    await db.flush()
    arm = await seed_fake_arm(db, project_id, user_id=None)
    await db.commit()
    monkeypatch.setattr(matrix_runner, "MAX_MATRIX_ENTITIES", 12)

    report = await run_matrix(db, project_id)
    await db.commit()

    (info,) = await _matrix_findings(db, project_id, RULE)
    assert report.truncated and info.attrs["subjects"] == [str(arm.code_file)]


async def test_a_fail_raised_on_a_former_info_stays_open(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NB2 (P3-T3 fix 2): a fail and a standing info of one rule on one subject share a node, and
    the evidence merge keeps the info's `missing` mark. A fail raised on a former info is no
    standing info: the run that raised it never resolves it."""
    project_id, _, arm = await _arm_project(db)
    need = FactNeed(name="divergences", set_in="the environment/divergences CONFIG")
    told = [
        RuleResult(
            status="unknown_input",
            message="divergences unknown",
            subjects=(arm.code_file,),
            missing=need,
        )
    ]

    def scripted(self: object, graph: object, facts: object) -> list[RuleResult]:
        return list(told)

    monkeypatch.setattr(PackageVersionConflict, "evaluate", scripted)
    await run_matrix(db, project_id)
    await db.commit()
    (node,) = await _matrix_findings(db, project_id, "package_version_conflict")
    assert node.attrs["severity"] == "info"

    told[:] = [
        RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message="drifted",
            subjects=(arm.code_file,),
        )
    ]
    report = await run_matrix(db, project_id)
    await db.commit()

    assert (node.attrs["severity"], node.attrs["status"]) == ("warning", "open")
    assert "missing" in node.attrs["evidence"] and report.infos_resolved == 0


async def test_a_run_never_touches_another_project(db: AsyncSession) -> None:
    """Tenant isolation (CLAUDE.md §7): a run over one project reads, annotates and raises within
    it alone. Another project holding the same arm and the same failing goal keeps its edges bare
    and has no finding."""
    mine, _, my_arm = await _arm_project(db)
    theirs, _, their_arm = await _arm_project(db)
    for project_id, arm in ((mine, my_arm), (theirs, their_arm)):
        await _command_goal(db, project_id, arm, arm.parts[2])
    await db.commit()

    report = await run_matrix(db, mine)
    await db.commit()

    assert report.findings_raised == 1 and await _matrix_findings(db, mine)
    assert await _matrix_findings(db, theirs) == []
    assert all("checker_results" not in row.attrs for row in await _project_edges(db, theirs))


async def test_a_rule_that_raises_no_findings_keeps_its_fail_on_the_edge(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R60: a rule whose `raises_findings` is False (another producer raises that problem) keeps
    its fail on the edge and in the report, and raises no finding for it."""
    monkeypatch.setattr(CommandedRangeVsJointLimit, "raises_findings", False)
    project_id, _, arm = await _arm_project(db)
    await _command_goal(db, project_id, arm, arm.parts[2])
    await db.commit()

    report = await run_matrix(db, project_id)
    await db.commit()

    assert [w.checker_id for w in report.warnings] == [RULE] and report.findings_raised == 0
    assert [f.attrs["severity"] for f in await _matrix_findings(db, project_id, RULE)] == ["info"]
    (row,) = await _commands_rows(db, project_id, arm.code_file, arm.parts[2])
    assert [item["status"] for item in _rule_items(row)] == ["fail"]


# ------------------------------------------- P3-T4: the netlist read and the motif writer


async def _netlist_rows(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEdge]:
    return list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == "connected_to",
                GraphEdge.deleted_at.is_(None),
            )
        )
    )


async def test_the_netlist_read_is_bounded_and_kept_off_the_edges(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R74: the run reads the schematic's `connected_to` edges in a second read of their own, so
    the motifs and an input's RC have their pins. That read is bounded by `MAX_EDGE_SCAN`, logged
    and `truncated` when it binds. No rule judges those edges, so they are never annotated."""
    divider = await seed_divider(db)

    report = await run_matrix(db, divider.project_id)
    await db.commit()

    rows = await _netlist_rows(db, divider.project_id)
    assert len(rows) == 13 and not report.truncated
    assert all("checker_results" not in row.attrs for row in rows)
    monkeypatch.setattr(matrix_runner, "MAX_EDGE_SCAN", 4)
    with caplog.at_level(logging.WARNING, logger="solus.checkers.matrix_runner"):
        capped = await run_matrix(db, divider.project_id, dry_run=True)
    assert capped.truncated and "netlist=4 (cap 4)" in caplog.text


async def test_motifs_are_kept_once_on_their_members_and_publish_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """R57/R78: a run keeps each motif on its members, and a second run with nothing changed
    writes none. A motif the netlist no longer holds is cleared from its members. No run
    publishes `graph.changed` or any frame about those entities: only findings' frames leave."""
    divider = await seed_divider(db)
    hub = RecordingHub()
    maker = build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]

    async def run() -> int:
        async with maker() as session:
            report = await run_matrix(session, divider.project_id)
            await commit_then_drain(session)
        return report.motifs_written

    assert (await run(), await run()) == (8, 0)
    leg = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == divider.parts["C2"],
            GraphEdge.dst_id == divider.nets["+3V3"],
            GraphEdge.relation_type == "connected_to",
        )
    )
    assert leg is not None
    leg.deleted_at = utcnow()  # the decoupling capacitor leaves the rail
    await db.commit()
    assert await run() == 4  # C2, +3V3 and GND lose the decoupling; U1 keeps its divider

    rail = await db.get(GraphEntity, divider.nets["+3V3"], populate_existing=True)
    u1 = await db.get(GraphEntity, divider.parts["U1"], populate_existing=True)
    assert rail is not None and "motifs" not in rail.attrs
    assert u1 is not None and [m["kind"] for m in u1.attrs["motifs"]] == ["divider_adc"]
    frames = {frame_type for _, frame_type in hub.seen()}
    assert "graph.changed" not in frames and all(f.startswith("finding.") for f in frames)


async def test_a_motif_on_a_row_another_writer_holds_is_skipped_not_waited_for(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """R78: as with edges, the run never waits for an entity row a sync holds. It skips the row
    (counted, logged), and the next run writes it."""
    divider = await seed_divider(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as sync:
        held = select(GraphEntity.id).where(GraphEntity.id == divider.parts["R1"])
        await sync.execute(held.with_for_update())
        with caplog.at_level(logging.WARNING, logger="solus.checkers.matrix_runner"):
            report = await asyncio.wait_for(run_matrix(db, divider.project_id), timeout=10)
            await db.commit()
        await sync.rollback()

    assert (report.motifs_written, report.motifs_skipped) == (7, 1)
    assert "motifs not kept for 1 entit" in caplog.text
    again = await run_matrix(db, divider.project_id)
    await db.commit()
    assert (again.motifs_written, again.motifs_skipped) == (1, 0)


async def test_a_truncated_run_keeps_no_motifs_and_clears_none(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """m5: a read cut at its cap may hold half a net. So a truncated run neither detects motifs
    nor rewrites the members' lists: they keep what the last whole run wrote, and the log says
    why."""
    divider = await seed_divider(db)
    assert (await run_matrix(db, divider.project_id)).motifs_written == 8
    await db.commit()
    r2 = await db.get(GraphEntity, divider.parts["R2"], populate_existing=True)
    assert r2 is not None
    kept = list(r2.attrs["motifs"])
    monkeypatch.setattr(matrix_runner, "MAX_EDGE_SCAN", 4)

    with caplog.at_level(logging.WARNING, logger="solus.checkers.matrix_runner"):
        capped = await run_matrix(db, divider.project_id)
        await db.commit()

    r2 = await db.get(GraphEntity, divider.parts["R2"], populate_existing=True)
    assert capped.truncated and (capped.motifs_written, capped.motifs_skipped) == (0, 0)
    assert r2 is not None and r2.attrs["motifs"] == kept
    assert "matrix motifs not kept: the run's read was truncated" in caplog.text


async def test_nets_wait_behind_what_the_rules_read_under_the_entity_cap(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m6: nets feed only the motifs. Under the entity cap they come after the fact kinds and the
    entities a judged relation touches, so a schematic's nets never crowd out the code a `reads`
    edge starts from. The motifs degrade first."""
    divider = await seed_divider(db)
    whole = await matrix_runner._project_graph(db, divider.project_id)
    others = {entity.id for entity in whole.entities if entity.kind != kinds.NET}
    assert not whole.truncated and others == {*divider.parts.values(), divider.code}
    monkeypatch.setattr(matrix_runner, "MAX_MATRIX_ENTITIES", len(others))

    capped = await matrix_runner._project_graph(db, divider.project_id)

    kept = {entity.id for entity in capped.entities}
    assert capped.truncated and kept == others


async def test_module_interface_holders_load_with_the_fact_kinds_under_the_entity_cap(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SOLUSDEV-321 P6: a file holding the software reader's `module_interfaces` loads with the
    fact kinds, so a large repository's other files never crowd a module contract out of a run.
    The entity cap itself stands."""
    team = Team(name="contract")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="contract")
    db.add(project)
    await db.flush()
    db.add_all(
        GraphEntity(
            project_id=project.id,
            kind=kinds.CODE_FILE,
            domain=Domain.CODE,
            origin="manual",
            name=f"lib_{n}.py",
        )
        for n in range(3)
    )
    await db.flush()
    holder = GraphEntity(
        project_id=project.id,
        kind=kinds.CODE_FILE,
        domain=Domain.CODE,
        origin="manual",
        name="policy.yaml",
        attrs={"module_interfaces": [{"role": "policy", "outputs": 6, "ref": "policy.yaml:1"}]},
    )
    db.add(holder)
    await db.commit()
    monkeypatch.setattr(matrix_runner, "MAX_MATRIX_ENTITIES", 1)

    capped = await matrix_runner._project_graph(db, project.id)

    assert capped.truncated and [entity.id for entity in capped.entities] == [holder.id]
