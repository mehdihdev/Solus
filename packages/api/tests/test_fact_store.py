"""SOLUSDEV-321 P3-T1 — the fact store: built once per matrix run from the run's graph and the
project's configs (never a model), and held as plain data the matrix rules read. A fact the
project does not state is absent, never guessed; `has` names only what the store holds."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from fixtures.fake_arm import LIMITS, seed_fake_arm
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers import fact_store
from solus_api.checkers.fact_store import (
    FACT_NAMES,
    BoardPosition,
    ExpectedValue,
    FactStore,
    ModuleFacts,
    RcSettling,
    build_fact_store,
)
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.neighborhood import Neighborhood, to_graph_context
from solus_api.hardware.library import (
    DefinitionError,
    Library,
    PartDefinition,
    PartLimitsSpec,
    PinSpec,
)
from solus_api.livebench.scene.part_bindings import JointRange
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    SourceType,
    Team,
)
from solus_api.orchestration.config import load_orchestration_config
from solus_api.services.code_env import (
    CodeEnvironment,
    EnvironmentProvenance,
    EnvironmentType,
    upsert_code_environment,
)
from solus_api.services.environment_divergence import recompute_divergences
from solus_api.services.solus_config import add_text_entry, put_config_entry
from solus_api.services.solus_payloads import Budgets, ConstraintMeta
from solus_api.software.policy_reader import ModuleInterface
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_inference_power_nets import seed_source
from test_netlist_motifs import _Schematic

_T0: Final = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
_SERVO: Final = PartDefinition(
    id="fake-servo",
    name="Fake servo",
    category="actuators",
    pins=[PinSpec(name="D9", capabilities=["pwm"])],
    limits=PartLimitsSpec(position_min=-150, position_max=150),
)
_LIBRARY: Final = Library(parts={"fake-servo": _SERVO}, platforms={})
_MASS: Final = ConstraintMeta(quantity="mass", limit=40, unit="g", comparator="<=")
_CLEARANCE: Final = ConstraintMeta(
    quantity="proximity_clearance_mm", limit=3, unit="mm", comparator=">="
)


async def _project(db: AsyncSession) -> uuid.UUID:
    team = Team(name="facts")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="facts")
    db.add(project)
    await db.flush()
    return project.id


async def _graph(db: AsyncSession, project_id: uuid.UUID) -> GraphContext:
    """The whole live project, through `to_graph_context` as a run reads it."""
    live = (GraphEntity.project_id == project_id, GraphEntity.deleted_at.is_(None))
    entities = list(await db.scalars(select(GraphEntity).where(*live)))
    edges = list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id, GraphEdge.deleted_at.is_(None)
            )
        )
    )
    return to_graph_context(Neighborhood(entities=entities, edges=edges, truncated=False))


async def _seed_configs(db: AsyncSession, project_id: uuid.UUID) -> None:
    """A budgets document, a software environment, the divergences table, a style entry and a
    rules entry stating the proximity clearance."""
    await add_text_entry(
        db,
        project_id,
        SolusSection.CONSTRAINTS,
        "switchers stay 3 mm from analog",
        author="user",
        created_by=None,
        subsection="rules",
        payload=_CLEARANCE.model_dump(mode="json"),
    )
    budgets = Budgets(computed_at=_T0, budgets=[])
    await put_config_entry(
        db,
        project_id,
        SolusSection.CONSTRAINTS,
        "budgets",
        budgets,
        text="Budgets",
        configured_entity_id=None,
        created_by=None,
        author="system",
    )
    env = CodeEnvironment(
        type=EnvironmentType.VENV,
        name="fw",
        provenance=EnvironmentProvenance.USER,
        captured_at=_T0,
    )
    await upsert_code_environment(db, project_id, env, created_by=None, author="user")
    await recompute_divergences(db, project_id)
    await add_text_entry(
        db,
        project_id,
        SolusSection.CONSTRAINTS,
        "brackets stay under 40 g",
        author="user",
        created_by=None,
        subsection="style",
        payload=_MASS.model_dump(mode="json"),
    )


async def test_facts_come_from_the_graph_and_the_configs(db: AsyncSession) -> None:
    pid = await _project(db)
    arm = await seed_fake_arm(db, pid, user_id=None)
    servo = await db.get(GraphEntity, arm.parts[2])
    assert servo is not None
    expected = {"torque": {"value": 0.4, "unit": "N*m", "sim_result_id": "s1"}}
    servo.attrs = {**servo.attrs, "definition_id": "fake-servo", "expected": expected}
    joint = {"name": "j3", "type": "revolute", "lower": -1.5, "upper": 1.5}
    scene = GraphEntity(
        project_id=pid,
        kind=kinds.BENCH_SCENE_MODEL,
        domain=Domain.SIMULATION,
        origin="manual",
        name="fake scene",
        attrs={
            "model": {"joints": [joint]},
            "bindings": [{"joint": "j3", "part_entity_id": str(servo.id)}],
        },
    )
    board = GraphEntity(
        project_id=pid,
        kind=kinds.COMPONENT,
        domain=Domain.ELECTRICAL,
        origin="manual",
        name="U1",
        attrs={"position": {"x": 12.5, "y": 30, "rot": 90}},
    )
    repo = await seed_source(db, pid, SourceType.GITHUB)
    policy = ModuleInterface(role="policy", outputs=6, ref="config/policy.yaml:5")
    module = GraphEntity(  # P6: what the software reader found in a file; a bad item is left out
        project_id=pid,
        source_id=repo.id,
        kind=kinds.CODE_FILE,
        domain=Domain.CODE,
        origin="manual",
        name="policy.yaml",
        attrs={"module_interfaces": [policy.model_dump(mode="json"), {"role": "planner"}]},
    )
    db.add_all([scene, board, module])
    rc = await _seed_rc_input(db, pid)
    await _seed_configs(db, pid)
    await db.flush()

    facts = await build_fact_store(db, pid, await _graph(db, pid), library=_LIBRARY)

    assert [(m.kind, m.net) for m in facts.motifs] == [("rc_on_input", rc["FILT"].id)]
    settling = RcSettling(rc["FILT"].id, 10_000.0, 1e-6)
    assert facts.rc_settling_s == {rc[name].id: settling for name in ("R9", "C9", "U9", "FILT")}
    assert facts.proximity_clearance_mm == 3.0
    assert facts.definitions == {servo.id: _SERVO}
    assert set(facts.runtime_configs) == {arm.robot}
    part = facts.part_config(servo.id)
    assert part is not None and part.limits is not None and part.limits.values == LIMITS
    assert facts.budgets is not None and facts.budgets.budgets == []
    assert facts.scene_joints == {servo.id: JointRange(scene.id, "j3", -1.5, 1.5, "rad")}
    assert facts.pcb_positions == {board.id: BoardPosition(12.5, 30.0, 90.0)}
    assert [env.name for env in facts.software_environments] == ["fw"]
    assert facts.divergences is not None and facts.divergences.machines == []
    assert [(entry.text, entry.meta) for entry in facts.style] == [
        ("brackets stay under 40 g", _MASS)
    ]
    assert facts.expected(servo.id, "torque") == ExpectedValue(0.4, "N*m", "s1")
    assert facts.expected(servo.id, "current") is None
    assert facts.module_interfaces == {module.id: ModuleFacts(repo.id, (policy,))}
    assert all(facts.has(name) for name in FACT_NAMES)


async def test_an_empty_project_holds_no_fact(db: AsyncSession) -> None:
    pid = await _project(db)
    facts = await build_fact_store(db, pid, GraphContext(entities=[], edges=[]), library=_LIBRARY)
    assert facts == FactStore()
    assert not any(facts.has(name) for name in FACT_NAMES)


async def test_another_projects_configs_are_never_read(db: AsyncSession) -> None:
    """Config reads are scoped by the run's project id, whatever ids its graph holds: their
    robot's config reads as empty and none of their documents reach the store."""
    mine, theirs = await _project(db), await _project(db)
    arm = await seed_fake_arm(db, theirs, user_id=None)
    await _seed_configs(db, theirs)
    await db.flush()

    facts = await build_fact_store(db, mine, await _graph(db, theirs), library=_LIBRARY)

    assert (facts.budgets, facts.divergences, facts.proximity_clearance_mm) == (None, None, None)
    assert (facts.software_environments, facts.style) == ((), ())
    assert facts.part_config(arm.parts[2]) is None
    assert all(not config.parts for config in facts.runtime_configs.values())


async def test_an_unreadable_or_malformed_fact_is_left_out(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pid = await _project(db)
    robot = EntityRead(id=uuid.uuid4(), kind=kinds.PHYSICAL_ROBOT, domain="project", name="r")

    def entity(kind: str, **attrs: Any) -> EntityRead:
        return EntityRead(id=uuid.uuid4(), kind=kind, domain="electrical", name=kind, attrs=attrs)

    odd = [
        entity(kinds.COMPONENT, position={"x": float("nan"), "y": 1}),
        entity(kinds.COMPONENT, position={"x": True, "y": 1}),
        entity(kinds.PART, position={"x": 1, "y": 2}),  # a part's position is no board position
        entity(kinds.PART, definition_id="not-in-library", expected={"torque": {"value": "hi"}}),
        entity(kinds.PART, expected={"speed": 3, "torque": {"value": float("inf")}}),
    ]

    async def refuse(*_: object) -> None:
        raise APIError(409, "config_upgrade_required", "needs review")

    monkeypatch.setattr(fact_store, "resolve_runtime_config", refuse)
    with caplog.at_level(logging.WARNING, logger="solus.checkers.fact_store"):
        graph = GraphContext(entities=[robot, *odd], edges=[])
        facts = await build_fact_store(db, pid, graph, library=_LIBRARY)

    assert facts == FactStore()
    assert f"project={pid} robot={robot.id}" in caplog.text


async def test_style_reads_only_what_a_person_or_sol_wrote(db: AsyncSession) -> None:
    """An imported file filed under `constraints/style` is a document, not a stated style: only
    TEXT and SOL entries become style facts, as the budgets and sourcing readers keep them."""
    pid = await _project(db)
    for text, author in (("print brackets in PETG", "user"), ("prefer M3 fasteners", "sol")):
        await add_text_entry(
            db,
            pid,
            SolusSection.CONSTRAINTS,
            text,
            author=author,
            created_by=None,
            subsection="style",
        )
    imported = SolusEntry(
        project_id=pid,
        section=SolusSection.CONSTRAINTS,
        subsection="style",
        kind=SolusEntryKind.ARTIFACT,
        text="style-guide.pdf",
    )
    db.add(imported)
    await db.flush()

    facts = await build_fact_store(db, pid, GraphContext(entities=[], edges=[]), library=_LIBRARY)

    assert [entry.text for entry in facts.style] == [
        "print brackets in PETG",
        "prefer M3 fasteners",
    ]


async def test_a_source_that_does_not_read_answers_no_fact(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A library that does not load, a stored document its model refuses, a malformed environment
    and a malformed style payload each answer "no fact" (logged where a source is lost), and the
    run never raises. `list_code_environments` validates every row, so one bad row hides every
    environment: that source reads as empty."""
    pid = await _project(db)

    def no_library(*_: object) -> None:
        raise DefinitionError("fake.yaml: does not parse")

    monkeypatch.setattr(fact_store, "load_library", no_library)
    good = CodeEnvironment(
        type=EnvironmentType.VENV, name="fw", provenance=EnvironmentProvenance.USER, captured_at=_T0
    )
    await upsert_code_environment(db, pid, good, created_by=None, author="user")
    bad_budgets, bad_env = (
        SolusEntry(
            project_id=pid,
            section=section,
            subsection=subsection,
            kind=SolusEntryKind.CONFIG,
            text="malformed",
            payload=payload,
        )
        for section, subsection, payload in (
            (SolusSection.CONSTRAINTS, "budgets", {"budgets": "not a list"}),
            (SolusSection.ENVIRONMENT, "software", {"type": "not an environment"}),
        )
    )
    db.add_all([bad_budgets, bad_env])
    half_bound = {"quantity": "mass"}  # a quantity without its limit, unit and comparator
    await add_text_entry(
        db,
        pid,
        SolusSection.CONSTRAINTS,
        "keep brackets light",
        author="user",
        created_by=None,
        subsection="style",
        payload=half_bound,
    )
    await db.flush()
    part = EntityRead(
        id=uuid.uuid4(),
        kind=kinds.PART,
        domain="mechanical",
        name="p",
        attrs={"definition_id": "x"},
    )

    with caplog.at_level(logging.WARNING, logger="solus.checkers.fact_store"):
        facts = await build_fact_store(db, pid, GraphContext(entities=[part], edges=[]))

    assert (facts.definitions, facts.budgets, facts.software_environments) == ({}, None, ())
    assert [(entry.text, entry.meta) for entry in facts.style] == [("keep brackets light", None)]
    assert not any(facts.has(name) for name in ("definitions", "budgets", "software_environments"))
    assert "the part library does not load; no definitions" in caplog.text
    assert f"config left out project={pid} entry={bad_budgets.id}" in caplog.text
    assert f"software environments left out project={pid}" in caplog.text


def test_has_names_only_a_held_fact() -> None:
    facts = FactStore(budgets=Budgets(computed_at=_T0, budgets=[]))
    assert facts.has("budgets")
    assert not facts.has("style")  # a source that states nothing
    for name in ("resonance_hz", "has", "part_config", "expected"):  # no source / not a fact
        assert not facts.has(name), name
    assert "budgets" in FACT_NAMES and "has" not in FACT_NAMES


def test_the_store_carries_the_shipped_simulation_bands_and_they_are_no_fact() -> None:
    """P4-T5: a rule judging a simulated value reads the ladder's own bands from the store (the
    shipped `simulation:` section of models.yaml), so it settles a value with margin where the
    ladder stops. They are configuration, never a fact a rule waits for."""
    shipped = load_orchestration_config().simulation
    assert FactStore().simulation == shipped
    assert FactStore().simulation.band("yield_fraction") == shipped.escalate_at
    assert "simulation" not in FACT_NAMES and not FactStore().has("simulation")


# --------------------------------------------- P3-T4: motifs, an input's RC, the clearance


async def _seed_rc_input(db: AsyncSession, project_id: uuid.UUID) -> dict[str, GraphEntity]:
    """An RC input as the schematic connector lands it: R9 from SIG into FILT, C9 from FILT to
    ground, and U9's ADC0 pin on FILT. The rows are returned by name."""

    def node(kind: str, name: str, **attrs: Any) -> GraphEntity:
        return GraphEntity(
            project_id=project_id,
            kind=kind,
            domain=Domain.ELECTRICAL,
            origin="connector",
            name=name,
            attrs=attrs,
        )

    rows = {
        "R9": node(kinds.COMPONENT, "R9", value="10k"),
        "C9": node(kinds.COMPONENT, "C9", value="1uF"),
        "U9": node(kinds.COMPONENT, "U9", value="fake MCU"),
        **{net: node(kinds.NET, net) for net in ("SIG", "FILT", "GND")},
    }
    db.add_all(rows.values())
    await db.flush()
    pins = (("R9", "SIG", "1"), ("R9", "FILT", "2"), ("C9", "FILT", "1"), ("C9", "GND", "2"))
    db.add_all(
        GraphEdge(
            project_id=project_id,
            src_id=rows[part].id,
            dst_id=rows[net].id,
            relation_type="connected_to",
            domain_pair="electrical<->electrical",
            confidence=1.0,
            origin="connector",
            attrs={"net": net, "pins": [pin], **extra},
        )
        for part, net, pin, extra in (
            *((part, net, pin, {}) for part, net, pin in pins),
            ("U9", "FILT", "4", {"pin_functions": {"4": "ADC0"}}),
        )
    )
    await db.flush()
    return rows


async def test_a_truncated_graph_states_no_motifs(db: AsyncSession) -> None:
    """m5: a read cut at its cap may hold half a net, which could settle a wrong RC. A truncated
    graph therefore detects no motifs and states no RC; the whole one does."""
    pid = await _project(db)
    divider = (
        _Schematic()
        .part("R1", "100k")
        .part("R2", "100k")
        .part("C1", "100nF")
        .part("U1")
        .wire("R1", "VBAT", "1")
        .wire("R1", "VSENSE", "2")
        .wire("R2", "VSENSE", "1")
        .wire("R2", "GND", "2")
        .wire("C1", "VSENSE", "1")
        .wire("C1", "GND", "2")
        .wire("U1", "VSENSE", "10", function="ADC0")
    )
    whole = divider.graph()

    stated = await build_fact_store(db, pid, whole, library=_LIBRARY)
    cut = await build_fact_store(
        db, pid, whole.model_copy(update={"truncated": True}), library=_LIBRARY
    )

    assert stated.motifs and stated.rc_settling_s
    assert cut.motifs == () and dict(cut.rc_settling_s) == {}


async def test_rc_settling_comes_from_a_settled_divider_or_rc_input(db: AsyncSession) -> None:
    """R73: each member of a SETTLED divider or RC input is keyed to the RC its input settles
    through: R_top‖R_bottom or the series R, and the capacitance to ground. A candidate states
    none. A member two inputs share states neither, because it cannot say which one a read
    samples."""
    pid = await _project(db)
    divider = (
        _Schematic()
        .part("R1", "100k")
        .part("R2", "100k")
        .part("C1", "100nF")
        .part("U1")
        .wire("R1", "VBAT", "1")
        .wire("R1", "VSENSE", "2")
        .wire("R2", "VSENSE", "1")
        .wire("R2", "GND", "2")
        .wire("C1", "VSENSE", "1")
        .wire("C1", "GND", "2")
        .wire("U1", "VSENSE", "10", function="ADC0")
    )

    facts = await build_fact_store(db, pid, divider.graph(), library=_LIBRARY)

    (motif,) = facts.motifs
    assert set(facts.rc_settling_s) == set(motif.members)
    for settling in facts.rc_settling_s.values():
        assert settling.net_id == divider.ids("VSENSE")[0]
        assert (settling.r_ohm, settling.c_f) == pytest.approx((50_000.0, 100e-9))
    assert facts.rc_settling_s[divider.ids("R2")[0]].tau_s == pytest.approx(5e-3)

    # A second ADC input on U1: U1 is then shared, so it names neither input's RC.
    divider.part("R3", "10k").part("C3", "1uF").wire("R3", "SIG", "1").wire("R3", "FILT", "2")
    divider.wire("C3", "FILT", "1").wire("C3", "GND", "2").wire("U1", "FILT", "11", function="ADC1")
    both = await build_fact_store(db, pid, divider.graph(), library=_LIBRARY)
    assert divider.ids("U1")[0] not in both.rc_settling_s
    filt = RcSettling(divider.ids("FILT")[0], 10_000.0, 1e-6)
    assert both.rc_settling_s[divider.ids("R3")[0]] == filt

    unnamed = (
        _Schematic()
        .part("R1", "10k")
        .part("C1", "1uF")
        .part("U1")
        .wire("R1", "X", "1")
        .wire("R1", "Y", "2")
        .wire("C1", "Y", "1")
        .wire("C1", "GND", "2")
        .wire("U1", "Y", "3")
    )
    candidate = await build_fact_store(db, pid, unnamed.graph(), library=_LIBRARY)
    assert candidate.motifs and candidate.rc_settling_s == {}
    assert not candidate.has("rc_settling_s")


async def test_the_clearance_is_the_largest_lower_bound_in_mm_a_rules_entry_states(
    db: AsyncSession,
) -> None:
    """R73: `proximity_clearance_mm` comes from the live `constraints/rules` entries a person
    typed or SOL filed. Only a lower bound in millimetres counts, and the largest one stated wins.
    Another cell's entries and another project's are never read."""
    pid, other = await _project(db), await _project(db)

    def bound(limit: float, unit: str = "mm", comparator: str = ">=") -> dict[str, Any]:
        meta = {"quantity": "proximity_clearance_mm", "limit": limit, "unit": unit}
        return ConstraintMeta.model_validate({**meta, "comparator": comparator}).model_dump(
            mode="json"
        )

    for text, payload, subsection, project in (
        ("keep switchers 2 mm from analog", bound(2.0), "rules", pid),
        ("and 5 mm from the ADC input", bound(5.0, comparator=">"), "rules", pid),
        ("stated in cm", bound(9.0, unit="cm"), "rules", pid),
        ("an upper bound", bound(20.0, comparator="<="), "rules", pid),
        ("a style preference", bound(30.0), "style", pid),
        ("their clearance", bound(50.0), "rules", other),
    ):
        await add_text_entry(
            db,
            project,
            SolusSection.CONSTRAINTS,
            text,
            author="user",
            created_by=None,
            subsection=subsection,
            payload=payload,
        )
    await db.flush()
    empty = GraphContext(entities=[], edges=[])

    assert (await build_fact_store(db, pid, empty, library=_LIBRARY)).proximity_clearance_mm == 5.0
    bare = await build_fact_store(db, await _project(db), empty, library=_LIBRARY)
    assert bare.proximity_clearance_mm is None and not bare.has("proximity_clearance_mm")
