"""IMP-01 impact engine: bounded traversal → ImpactResult assembly (SOLUSDEV-197).

The engine layers on `load_neighborhood` (the ONE traversal) plus canonical
identity: real `same_as` edges are traversed like any edge, and FK-only
canonical siblings (stamped by FP-02 but not yet edged) enter as a synthetic
`same_as` hop at distance 1. Consequences come from a pluggable async provider
(IMP-02 supplies the checker-backed one); these tests inject known consequences
and pin the assembly: paths start at the focus, distance == len(path), node
severity is the worst consequence, truncation propagates, and every result
validates against the frozen CTR-04 contract.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import pytest
from solus_api.checkers.interface import Severity
from solus_api.contracts.action_gate import DiffRow
from solus_api.contracts.impact import Consequence, ImpactResult
from solus_api.graph.neighborhood import Neighborhood
from solus_api.impact import compute_impact
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team
from sqlalchemy.ext.asyncio import AsyncSession

# --- Helpers -----------------------------------------------------------------------


async def _project(db: AsyncSession, suffix: str) -> Project:
    team = Team(name=f"T-{suffix}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"P-{suffix}")
    db.add(project)
    await db.flush()
    return project


async def _entity(
    db: AsyncSession,
    project: Project,
    name: str,
    *,
    domain: Domain = Domain.ELECTRICAL,
    kind: str = "component",
    origin: str = "connector",
    canonical_part_id: UUID | None = None,
) -> GraphEntity:
    row = GraphEntity(
        project_id=project.id,
        kind=kind,
        domain=domain,
        name=name,
        origin=origin,
        canonical_part_id=canonical_part_id,
        attrs={},
        modality_hints={},
    )
    db.add(row)
    await db.flush()
    return row


async def _edge(
    db: AsyncSession,
    project: Project,
    src: GraphEntity,
    dst: GraphEntity,
    relation: str,
) -> GraphEdge:
    row = GraphEdge(
        project_id=project.id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type=relation,
        domain_pair=f"{src.domain.value}<->{dst.domain.value}",
        confidence=1.0,
        origin="connector",
        attrs={},
    )
    db.add(row)
    await db.flush()
    return row


def _cons(cid: str, severity: Severity = Severity.WARNING) -> Consequence:
    return Consequence(
        id=cid,
        severity=severity,
        headline=f"{cid} headline",
        rationale=f"{cid}: a change upstream makes this marginal in a way worth reading about.",
    )


def _provider(mapping: Mapping[UUID, Sequence[Consequence]]) -> Any:
    async def provide(
        neighborhood: Neighborhood, focus_id: UUID
    ) -> Mapping[UUID, Sequence[Consequence]]:
        return mapping

    return provide


_CHANGE = [DiffRow(label="stall_current_a", before="1.1", after="3.0")]


async def _impact(
    db: AsyncSession,
    project: Project,
    focus: GraphEntity,
    mapping: Mapping[UUID, Sequence[Consequence]],
    **kwargs: Any,
) -> ImpactResult:
    return await compute_impact(
        db,
        project.id,
        focus_id=focus.id,
        change=_CHANGE,
        provider=_provider(mapping),
        **kwargs,
    )


# --- Assembly ----------------------------------------------------------------------


async def test_no_consequences_is_an_empty_honest_answer(db: AsyncSession) -> None:
    project = await _project(db, "imp-empty")
    motor = await _entity(db, project, "drive_motor", domain=Domain.MECHANICAL)
    result = await _impact(db, project, motor, {})

    assert result.nodes == []
    assert result.truncated is False
    assert result.focus.label == "drive_motor"
    assert result.focus.entity.entity_id == str(motor.id)
    ImpactResult.model_validate(result.model_dump())  # frozen-contract round trip


async def test_direct_neighbor_distance_one_path_starts_at_focus(db: AsyncSession) -> None:
    project = await _project(db, "imp-one")
    motor = await _entity(db, project, "drive_motor", domain=Domain.MECHANICAL)
    driver = await _entity(db, project, "U3 TB6612FNG")
    await _edge(db, project, driver, motor, "driven_by")

    result = await _impact(db, project, motor, {driver.id: [_cons("c1", Severity.CRITICAL)]})

    assert len(result.nodes) == 1
    node = result.nodes[0]
    assert node.entity.entity_id == str(driver.id)
    assert node.distance == 1 and len(node.path) == 1
    assert node.path[0].entity.entity_id == str(motor.id)
    assert node.path[0].relation == "driven_by"
    assert node.severity is Severity.CRITICAL
    ImpactResult.model_validate(result.model_dump())


async def test_two_hop_path_carries_each_relation(db: AsyncSession) -> None:
    project = await _project(db, "imp-two")
    motor = await _entity(db, project, "drive_motor", domain=Domain.MECHANICAL)
    driver = await _entity(db, project, "driver")
    mcu = await _entity(db, project, "motor_ctl.cpp", domain=Domain.CODE)
    await _edge(db, project, driver, motor, "driven_by")
    await _edge(db, project, mcu, driver, "controlled_by")

    result = await _impact(db, project, motor, {mcu.id: [_cons("pwm")]})

    node = result.nodes[0]
    assert node.distance == 2
    assert [s.relation for s in node.path] == ["driven_by", "controlled_by"]
    assert [s.entity.entity_id for s in node.path] == [str(motor.id), str(driver.id)]
    assert node.domain is Domain.CODE


async def test_fk_only_canonical_sibling_is_a_same_as_hop(db: AsyncSession) -> None:
    # FP-02 stamped both observations onto one canonical row but no linker edge
    # exists yet: the sibling is still the same physical part, reached as a
    # synthetic same_as hop at distance 1.
    project = await _project(db, "imp-fk")
    canonical = await _entity(db, project, "LM358", kind="canonical_part", origin="fingerprint")
    sch = await _entity(db, project, "U1", canonical_part_id=canonical.id)
    cad = await _entity(
        db, project, "cad_body", domain=Domain.MECHANICAL, canonical_part_id=canonical.id
    )

    result = await _impact(db, project, sch, {cad.id: [_cons("clearance")]})

    assert len(result.nodes) == 1
    node = result.nodes[0]
    assert node.entity.entity_id == str(cad.id)
    assert node.distance == 1
    assert node.path[0].relation == "same_as"
    assert node.path[0].entity.entity_id == str(sch.id)


async def test_canonical_bookkeeping_row_is_never_a_node(db: AsyncSession) -> None:
    project = await _project(db, "imp-canon")
    canonical = await _entity(db, project, "LM358", kind="canonical_part", origin="fingerprint")
    sch = await _entity(db, project, "U1", canonical_part_id=canonical.id)

    result = await _impact(db, project, sch, {canonical.id: [_cons("noise")]})

    assert result.nodes == []


async def test_same_as_edge_extends_the_walk_across_domains(db: AsyncSession) -> None:
    # linker edge (electrical<->mechanical) then a mechanical relation: the
    # identity hop is a real edge and participates in depth like any other.
    project = await _project(db, "imp-sameas")
    sch = await _entity(db, project, "U7")
    cad = await _entity(db, project, "part_body", domain=Domain.MECHANICAL)
    casing = await _entity(db, project, "casing", domain=Domain.MECHANICAL)
    await _edge(db, project, sch, cad, "same_as")
    await _edge(db, project, cad, casing, "mates_with")

    result = await _impact(db, project, sch, {casing.id: [_cons("blocked_port")]})

    node = result.nodes[0]
    assert node.distance == 2
    assert [s.relation for s in node.path] == ["same_as", "mates_with"]


async def test_unreached_and_cross_project_consequences_are_dropped(db: AsyncSession) -> None:
    project_a = await _project(db, "imp-iso-a")
    project_b = await _project(db, "imp-iso-b")
    motor = await _entity(db, project_a, "motor", domain=Domain.MECHANICAL)
    foreign = await _entity(db, project_b, "foreign")
    orphan = await _entity(db, project_a, "orphan")  # no path from focus

    result = await _impact(
        db,
        project_a,
        motor,
        {foreign.id: [_cons("leak")], orphan.id: [_cons("island")]},
    )

    assert result.nodes == []


async def test_truncation_propagates_from_the_traversal(db: AsyncSession) -> None:
    project = await _project(db, "imp-trunc")
    motor = await _entity(db, project, "motor", domain=Domain.MECHANICAL)
    parts = [await _entity(db, project, f"p{i}") for i in range(4)]
    for part in parts:
        await _edge(db, project, motor, part, "drives")

    result = await _impact(db, project, motor, {}, max_entities=2)

    assert result.truncated is True


async def test_nodes_sorted_worst_first_then_nearest(db: AsyncSession) -> None:
    project = await _project(db, "imp-sort")
    motor = await _entity(db, project, "motor", domain=Domain.MECHANICAL)
    near = await _entity(db, project, "near")
    far = await _entity(db, project, "far", domain=Domain.CODE)
    await _edge(db, project, near, motor, "driven_by")
    await _edge(db, project, far, near, "controlled_by")

    result = await _impact(
        db,
        project,
        motor,
        {
            near.id: [_cons("warn", Severity.WARNING)],
            far.id: [_cons("crit", Severity.CRITICAL), _cons("info", Severity.INFO)],
        },
    )

    assert [n.severity for n in result.nodes] == [Severity.CRITICAL, Severity.WARNING]
    assert result.nodes[0].severity is Severity.CRITICAL  # worst of its consequences
    assert result.nodes[0].distance == 2


async def test_multi_hop_path_through_a_synthetic_sibling_seed(db: AsyncSession) -> None:
    # FK sibling (no real edge to the focus) followed by a real edge: the path
    # must chain the synthetic same_as hop with the traversed relation.
    project = await _project(db, "imp-sibhop")
    canonical = await _entity(db, project, "PART", kind="canonical_part", origin="fingerprint")
    focus = await _entity(db, project, "U1", canonical_part_id=canonical.id)
    cad = await _entity(
        db, project, "cad_body", domain=Domain.MECHANICAL, canonical_part_id=canonical.id
    )
    casing = await _entity(db, project, "casing", domain=Domain.MECHANICAL)
    await _edge(db, project, cad, casing, "mates_with")

    result = await _impact(db, project, focus, {casing.id: [_cons("blocked")]})

    node = result.nodes[0]
    assert node.distance == 2
    assert [s.relation for s in node.path] == ["same_as", "mates_with"]
    assert [s.entity.entity_id for s in node.path] == [str(focus.id), str(cad.id)]


async def test_focus_truncated_out_of_roots_still_returns(db: AsyncSession) -> None:
    # More canonical siblings than max_entities, all created BEFORE the focus:
    # the ordered roots load truncates the focus itself out of the neighborhood.
    # Paths still anchor at the focus (the engine holds its row) — the request
    # returns a truncated result instead of a KeyError.
    project = await _project(db, "imp-focustrunc")
    canonical = await _entity(db, project, "PART", kind="canonical_part", origin="fingerprint")
    siblings = [
        await _entity(db, project, f"sib{i}", canonical_part_id=canonical.id) for i in range(6)
    ]
    focus = await _entity(db, project, "late_focus", canonical_part_id=canonical.id)

    result = await _impact(
        db,
        project,
        focus,
        {siblings[0].id: [_cons("late")]},
        max_entities=3,
    )

    assert result.truncated is True
    for node in result.nodes:  # may or may not include sib0 under truncation —
        assert node.path[0].entity.entity_id == str(focus.id)  # but never crashes


async def test_missing_focus_raises(db: AsyncSession) -> None:
    project = await _project(db, "imp-missing")
    with pytest.raises(ValueError, match="focus"):
        await compute_impact(
            db,
            project.id,
            focus_id=uuid.uuid4(),
            change=_CHANGE,
            provider=_provider({}),
        )


async def test_hero_shaped_scenario_spans_three_domains(db: AsyncSession) -> None:
    """The acceptance shape: a motor-current change reaches electrical, code and
    mechanical consequences with explainable paths. Consequences are injected
    here; IMP-02's checker-backed provider makes them real."""
    project = await _project(db, "imp-hero")
    motor = await _entity(db, project, "drive_motor", domain=Domain.MECHANICAL)
    driver = await _entity(db, project, "U3 TB6612FNG")
    firmware = await _entity(db, project, "motor_ctl.cpp", domain=Domain.CODE)
    harness = await _entity(db, project, "drive_harness", domain=Domain.MECHANICAL)
    await _edge(db, project, driver, motor, "driven_by")
    await _edge(db, project, firmware, driver, "controlled_by")
    await _edge(db, project, harness, motor, "connected_to")

    result = await _impact(
        db,
        project,
        motor,
        {
            driver.id: [_cons("driver-underrated", Severity.CRITICAL)],
            firmware.id: [_cons("pwm-ceiling")],
            harness.id: [_cons("harness-gauge")],
        },
    )

    assert {n.domain for n in result.nodes} == {
        Domain.ELECTRICAL,
        Domain.CODE,
        Domain.MECHANICAL,
    }
    by_label = {n.label: n for n in result.nodes}
    assert by_label["U3 TB6612FNG"].distance == 1
    assert by_label["motor_ctl.cpp"].distance == 2
    assert by_label["drive_harness"].distance == 1
    assert result.nodes[0].label == "U3 TB6612FNG"  # critical sorts first
    validated = ImpactResult.model_validate(result.model_dump())
    assert validated.change[0].label == "stall_current_a"
