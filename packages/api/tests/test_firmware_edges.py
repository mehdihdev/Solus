"""SOLUSDEV-321 P3-T2 — the commanded fact: a literal goal a reviewed firmware row states becomes
`attrs.commanded = {min, max, unit, min_ref, max_ref}` on the `commands` edge
`graph/inference/firmware_edges` writes (R41), read off the accepted row the firmware extractor
made of the call (R52)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Final

from fixtures.fake_arm import FakeArm, seed_fake_arm
from livebench.hardware.topology_extractors import firmware_topology
from livebench.recognition.firmware import extract_firmware_bytes
from solus_api.checkers.cells.software_mechanical import COMMANDED, CommandedRangeVsJointLimit
from solus_api.checkers.fact_store import build_fact_store
from solus_api.checkers.matrix_rule import EdgeRef
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.graph import kinds
from solus_api.graph.edges import retire_edge, write_edge
from solus_api.graph.inference import firmware_edges
from solus_api.graph.neighborhood import load_neighborhood, to_graph_context
from solus_api.hardware.topology import EVIDENCE_MARKER, EVIDENCE_RELATION
from solus_api.hardware.topology_evidence import TopologyEvidence
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team
from sqlalchemy.ext.asyncio import AsyncSession
from test_inference_firmware_edges import inferred, seed_code_file, seed_evidence

SKETCH: Final = Path(__file__).parent / "fixtures" / "inference" / "bus_sketch_goal.ino"
#: The sketch's path in the graph and the token its extraction names the source by, so the rows'
#: `path:line` resolve to the code entity.
SKETCH_REF: Final = "bus_sketch_goal.ino"
GOALS_PATH: Final = "fw/goals.ino"


def goal_line(needle: str) -> int:
    """The 1-based line of the live (uncommented) `needle` in the goal sketch."""
    for number, text in enumerate(SKETCH.read_text().splitlines(), 1):
        if needle in text and not text.strip().startswith("//"):
            return number
    raise AssertionError(needle)


async def _arm_project(db: AsyncSession) -> tuple[uuid.UUID, FakeArm]:
    team = Team(name="goal team")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="goal arm")
    db.add(project)
    await db.flush()
    return project.id, await seed_fake_arm(db, project.id, user_id=None)


async def _accept(
    db: AsyncSession, project_id: uuid.UUID, arm: FakeArm, row: TopologyEvidence
) -> None:
    """`row` as `TopologyAcceptanceService.confirm` stores an accepted one."""
    marked = {"managed_by": EVIDENCE_MARKER, "nonoperational": True, "robot_id": str(arm.robot)}
    evidence = GraphEntity(
        project_id=project_id,
        kind=kinds.HARDWARE_EVIDENCE,
        domain=Domain.ELECTRICAL,
        origin="manual",
        name="Reviewed row",
        attrs=marked,
    )
    db.add(evidence)
    await db.flush()
    await write_edge(
        db,
        project_id=project_id,
        src_id=arm.brain,
        dst_id=evidence.id,
        relation_type=EVIDENCE_RELATION,
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=None,
        attrs={**marked, "source_kind": "firmware", "row": row.model_dump(mode="json")},
        edge_id=uuid.uuid4(),
        managed_by=EVIDENCE_MARKER,
    )


async def _reviewed_sketch(db: AsyncSession) -> tuple[uuid.UUID, FakeArm, GraphEntity]:
    """The fake arm, the goal sketch in its graph, and every row the extractor makes of the sketch
    accepted."""
    project_id, arm = await _arm_project(db)
    code = await seed_code_file(db, project_id, SKETCH_REF)
    findings = extract_firmware_bytes(SKETCH.read_bytes(), suffix=".ino", source_ref=SKETCH_REF)
    batch = firmware_topology(findings, source_namespace="extraction:test", source_ref="source:x")
    for row in batch.rows:
        await _accept(db, project_id, arm, row)
    return project_id, arm, code


async def test_literal_goal_becomes_commanded_fact(db: AsyncSession) -> None:
    project_id, arm, code = await _reviewed_sketch(db)

    await firmware_edges.infer(db, project_id)

    goal = [edge for edge in await inferred(db, project_id, "commands") if edge.src_id == code.id]
    assert [(edge.dst_id, edge.confidence) for edge in goal] == [(arm.parts[2], 0.8)]
    line = f"{SKETCH_REF}:{goal_line('setGoalPositionDeg(3, 200)')}"
    assert goal[0].attrs["commanded"] == {
        "min": 200.0,
        "max": 200.0,
        "unit": "deg",
        "min_ref": line,
        "max_ref": line,
    }


async def test_commanded_range_vs_joint_limit_fires_on_the_goal_sketch(db: AsyncSession) -> None:
    """The goal sketch end to end: its reviewed rows → the commanded fact on the `commands` edge →
    `commanded_range_vs_joint_limit`, over the graph and facts a run reads (`to_graph_context`,
    `build_fact_store`), fails on that edge: 200 deg past the fake arm's ±150 deg limit. The fake
    arm's own code commands its parts with no literal goal: each says where one is stated (M5)."""
    project_id, arm, code = await _reviewed_sketch(db)
    await firmware_edges.infer(db, project_id)
    neighborhood = await load_neighborhood(db, project_id, roots=[arm.robot, arm.parts[2]])
    graph = to_graph_context(neighborhood)
    facts = await build_fact_store(db, project_id, graph)
    rule = CommandedRangeVsJointLimit()

    results = rule.results(graph, facts)

    goal = EdgeRef(code.id, arm.parts[2], "commands")
    (result,) = [found for found in results if found.edge_ref == goal]
    others = [found for found in results if found is not result]
    assert others and all((r.status, r.missing) == ("unknown_input", COMMANDED) for r in others)
    assert result.status == "fail"
    assert (result.evidence["commanded_max"], result.evidence["unit"]) == (200.0, "deg")
    assert (result.evidence["limit_hi"], result.evidence["limit_source"]) == (150.0, "config")
    parts = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
    (warning,) = rule.check(graph, parts, facts)
    assert warning.entity_ids == (code.id, arm.parts[2])


def _goal(name: str, value: object) -> dict[str, Any]:
    detail = json.dumps({"kind": "goal_call", "language": "cpp", "value": value})
    return {"provenance": {"entity_ref": name, "detail": detail}}


async def test_raw_rate_and_symbolic_goals_state_only_what_they_say(db: AsyncSession) -> None:
    """`raw` without `deg` in the call name; a rate goal, or one without a literal, commands the
    part and states no position; one file's goals to one address are one range whose `min_ref` and
    `max_ref` are its ends' lines; goals in two units state none; a rerun changes nothing."""
    project_id, arm = await _arm_project(db)
    code = await seed_code_file(db, project_id, GOALS_PATH)
    rows = (
        (20, "4", _goal("writePosition", 2048)),
        (21, "5", _goal("setGoalVelocityDeg", 300)),
        (22, "6", _goal("setGoal", None)),
        (23, "1", _goal("setGoalDeg", -170)),
        (24, "1", _goal("setGoalDeg", 90)),
        (25, "2", _goal("setGoalDeg", 10)),
        (26, "2", _goal("writePosition", 500)),
    )
    for line, address, row in rows:
        source_ref = f"{GOALS_PATH}:{line}"
        await seed_evidence(
            db, project_id, arm.robot, arm.brain, source_ref=source_ref, address=address, **row
        )

    await firmware_edges.infer(db, project_id)

    commanded = {
        edge.dst_id: edge.attrs.get("commanded")
        for edge in await inferred(db, project_id, "commands")
        if edge.src_id == code.id
    }
    part = dict(enumerate(arm.parts, start=1))
    at = {line: f"{GOALS_PATH}:{line}" for line in (20, 23, 24)}
    assert commanded == {
        part[4]: {
            "min": 2048.0,
            "max": 2048.0,
            "unit": "raw",
            "min_ref": at[20],
            "max_ref": at[20],
        },
        part[5]: None,
        part[6]: None,
        part[1]: {"min": -170.0, "max": 90.0, "unit": "deg", "min_ref": at[23], "max_ref": at[24]},
        part[2]: None,
    }
    again = await firmware_edges.infer(db, project_id)
    assert (again.created, again.updated) == (0, 0)


async def _commanded_by_part(
    db: AsyncSession, project_id: uuid.UUID, code: GraphEntity
) -> dict[uuid.UUID, Any]:
    edges = await inferred(db, project_id, "commands")
    return {e.dst_id: e.attrs.get("commanded", "absent") for e in edges if e.src_id == code.id}


async def test_a_goal_that_no_longer_stands_clears_the_commanded_fact(db: AsyncSession) -> None:
    """I1: `write_edge` merges attrs, so `commanded` is always written. On the next run it is None
    when the literal row is retired while a symbolic row still writes the edge (the fix accepted
    as a variable), or when an address's goals come to state two units. No old range outlives
    the code it described."""
    project_id, arm = await _arm_project(db)
    code = await seed_code_file(db, project_id, GOALS_PATH)

    async def accept(line: int, address: str, name: str, value: object) -> GraphEdge:
        source_ref = f"{GOALS_PATH}:{line}"
        row = _goal(name, value)
        return await seed_evidence(
            db, project_id, arm.robot, arm.brain, source_ref=source_ref, address=address, **row
        )

    literal = await accept(20, "3", "setGoalPositionDeg", 200)
    await accept(21, "3", "setGoalPositionDeg", None)
    await accept(30, "4", "setGoalDeg", 10)
    await firmware_edges.infer(db, project_id)
    part = dict(enumerate(arm.parts, start=1))
    before = await _commanded_by_part(db, project_id, code)
    assert isinstance(before[part[3]], dict) and isinstance(before[part[4]], dict)

    retire_edge(literal)
    await accept(31, "4", "writePosition", 2048)
    await db.flush()
    await firmware_edges.infer(db, project_id)

    assert await _commanded_by_part(db, project_id, code) == {part[3]: None, part[4]: None}
