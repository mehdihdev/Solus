"""SOLUSDEV-321 P3-T4 — `sample_rate_vs_adc_settling` (software → electrical).

The rule compares how often the code samples an ADC input with the 5·RC its net settles through.

- **The RC** belongs to the settled divider or RC filter on the net the confirmed `reads` edge
  lands on (`FactStore.rc_settling_s`, built from the schematic's motifs).
- **The rate** is the code entity's `loop_rate_hz`.

A sample period shorter than 5·RC fails, because the code reads the input before it has settled.
"""

from __future__ import annotations

import uuid
from typing import Final

import pytest
from fixtures.matrix_divider import seed_divider
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.cells.software_electrical import (
    LOOP_RATE,
    RC_SETTLING,
    SampleRateVsAdcSettling,
)
from solus_api.checkers.fact_store import build_fact_store
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.graph import kinds
from solus_api.models import GraphEdge, GraphEntity, Project, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_netlist_motifs import _fixture_context

RULE: Final = SampleRateVsAdcSettling()


async def _empty_project(db: AsyncSession) -> uuid.UUID:
    team = Team(name="adc")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="adc")
    db.add(project)
    await db.flush()
    return project.id


def _sampled_divider(
    loop_rate_hz: float | None, *, onto: str = "R2", confidence: float = 1.0
) -> tuple[GraphContext, EdgeRead]:
    """The divider fixture's graph, plus the firmware sampling it: a code entity stating its
    `loop_rate_hz`, and a `reads` edge onto `onto` (by default the divider's bottom leg, on the
    ADC net)."""
    graph, ids = _fixture_context()
    attrs = {"loop_rate_hz": loop_rate_hz} if loop_rate_hz is not None else {}
    code = EntityRead(id=uuid.uuid4(), kind="code_file", domain="code", name="fw.ino", attrs=attrs)
    read = EdgeRead(
        src_id=code.id,
        dst_id=ids[onto],
        relation_type="reads",
        domain_pair="code<->electrical",
        confidence=confidence,
        attrs={"pin": "A0"},
    )
    return GraphContext(entities=[*graph.entities, code], edges=[*graph.edges, read]), read


async def test_fires_above_5rc(db: AsyncSession) -> None:
    """The P3 acceptance's netlist half, through the matrix job. The divider fixture is synced
    and its reads edge confirmed, with the code sampling at 100 Hz.

    - The run keeps `divider_adc` on the ADC net's members.
    - It fails the read, because 5·RC = 25 ms > 10 ms. The verdict goes on the edge and
      becomes a checker finding.
    - At 10 Hz the same read passes.
    """
    divider = await seed_divider(db, loop_rate_hz=100.0)

    report = await run_matrix(db, divider.project_id)
    await db.commit()

    (result,) = report.results[RULE.rule_id]
    assert (result.status, result.subjects) == ("fail", (divider.code, divider.parts["R2"]))
    assert result.evidence["settle_s"] == pytest.approx(0.025)
    read = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.project_id == divider.project_id, GraphEdge.relation_type == "reads"
        )
    )
    assert read is not None
    (item,) = [i for i in read.attrs["checker_results"] if i["rule_id"] == RULE.rule_id]
    assert (item["status"], item["severity"]) == ("fail", "warning")
    finding = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == divider.project_id,
            GraphEntity.kind == kinds.FINDING,
            GraphEntity.attrs["rule_id"].astext == RULE.rule_id,
        )
    )
    assert finding is not None
    assert finding.attrs["subjects"] == [str(divider.code), str(divider.parts["R2"])]
    r2 = await db.get(GraphEntity, divider.parts["R2"])
    assert r2 is not None
    assert [m["kind"] for m in r2.attrs["motifs"]] == ["divider_adc"]

    slow = await seed_divider(db, loop_rate_hz=10.0)
    (passed,) = (await run_matrix(db, slow.project_id)).results[RULE.rule_id]
    await db.commit()
    assert passed.status == "pass"


async def test_a_sample_period_inside_5rc_fails_and_one_past_it_passes(db: AsyncSession) -> None:
    """R1‖R2 = 50 kΩ into C1 = 100 nF: τ = 5 ms, so the input settles in 25 ms. Sampling at
    100 Hz (every 10 ms) reads it unsettled. At 10 Hz (every 100 ms) it has settled."""
    pid = await _empty_project(db)
    fast, read = _sampled_divider(100.0)

    (result,) = RULE.results(fast, await build_fact_store(db, pid, fast))

    assert (result.status, result.severity) == ("fail", Severity.WARNING)
    assert result.subjects == (read.src_id, read.dst_id)
    assert result.edge_ref == EdgeRef.of(read)
    assert result.evidence["settle_s"] == pytest.approx(0.025)
    assert result.evidence["sample_period_s"] == pytest.approx(0.01)
    assert result.evidence["tau_s"] == pytest.approx(0.005)
    assert (result.evidence["r_ohm"], result.evidence["c_f"]) == pytest.approx((50e3, 100e-9))
    assert result.evidence["loop_rate_hz"] == 100.0
    assert "25 ms" in result.message and "10 ms" in result.message

    slow, _ = _sampled_divider(10.0)
    (settled,) = RULE.results(slow, await build_fact_store(db, pid, slow))
    assert settled.status == "pass" and settled.evidence["sample_period_s"] == pytest.approx(0.1)


async def test_an_unstated_rate_or_rc_cannot_check_that_read(db: AsyncSession) -> None:
    """Each gap is the read's own `unknown_input`, naming the fact and carrying the edge:
    - a code entity that states no rate (or a zero one) names `loop_rate_hz`;
    - a read onto a part no settled input holds names `rc_settling_s`;
    - a graph with no stated RC anywhere is the base's one store-wide unknown;
    - a read nobody confirmed is no read: the relation gap names `reads`."""
    pid = await _empty_project(db)
    for rate in (None, 0.0):
        graph, read = _sampled_divider(rate)
        (unknown,) = RULE.results(graph, await build_fact_store(db, pid, graph))
        assert (unknown.status, unknown.missing) == ("unknown_input", LOOP_RATE)
        assert unknown.edge_ref == EdgeRef.of(read)

    graph, read = _sampled_divider(100.0, onto="J1")
    (elsewhere,) = RULE.results(graph, await build_fact_store(db, pid, graph))
    assert (elsewhere.missing, elsewhere.subjects) == (RC_SETTLING, (read.src_id, read.dst_id))

    bare = GraphContext(entities=graph.entities, edges=[read])
    (store_wide,) = RULE.results(bare, await build_fact_store(db, pid, bare))
    assert (store_wide.missing, store_wide.subjects) == (RC_SETTLING, ())

    graph, _ = _sampled_divider(100.0, confidence=0.55)
    (gap,) = RULE.results(graph, await build_fact_store(db, pid, graph))
    assert gap.missing is not None and gap.missing.name == "reads"
