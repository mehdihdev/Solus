"""SOLUSDEV-321 P4-T1 — what a simulation run leaves in the graph:

- a `sim_result` carrying its solver, its inputs with their sources and what it leaves out;
- a `verified_by` edge from the subject to it;
- the subject's `attrs.expected`, which the envelopes and the matrix's fact store read back;
- a `graph.changed` published after the commit.

A result without its full provenance, or a subject that is not live in the project, writes
nothing."""

from __future__ import annotations

import uuid
from typing import Any, Final

import pytest
from pydantic import ValidationError
from solus_api.checkers.fact_store import ExpectedValue, build_fact_store
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.live import LiveHub
from solus_api.graph.neighborhood import Neighborhood, to_graph_context
from solus_api.livebench.findings.envelopes import build_envelope
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team, utcnow
from solus_api.orchestration.config import EnvelopesConfig
from solus_api.simulation.sim_capability import SimProvenance, SimResult
from solus_api.simulation.sim_facts import record_sim_result
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

RESULT: Final = SimResult.model_validate(
    {
        "values": {"stress_mpa": {"value": 41.4, "unit": "MPa"}},
        "provenance": {
            "solver": "beam_bending",
            "inputs": {
                "material": {"value": {"name": "fake-6061", "yield_mpa": 276}, "source": "known"},
                "section_modulus_mm3": {"value": 120.5, "source": "derived"},
                "load_factor": {"value": 1.0, "source": "assumed"},
            },
            "leaves_out": ["dynamic loads", "fatigue"],
        },
    }
)


def _counted(kind: str) -> Select[tuple[int]]:
    return select(func.count()).select_from(GraphEntity).where(GraphEntity.kind == kind)


class _Heard:
    """The hub's `on_graph_changed`, i.e. the fan-out a published `graph.changed` wakes. For each
    project it hears, it notes how many `sim_result` rows a session of its own reads at that
    moment. That is how a test sees the publish came after the commit."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine)
        self.heard: list[tuple[uuid.UUID, int]] = []

    async def __call__(self, project_id: uuid.UUID) -> None:
        async with self._sessions() as own:
            rows = await own.scalar(_counted(kinds.SIM_RESULT))
        self.heard.append((project_id, rows or 0))


class _DeadRelay(LiveHub):
    """A hub whose publish fails, like a relay that is down."""

    async def publish(self, project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        raise ConnectionError("relay down")


async def _seed(
    db: AsyncSession, name: str = "bracket", **attrs: Any
) -> tuple[uuid.UUID, uuid.UUID]:
    """A committed project holding one mechanical part."""
    team = Team(name=f"sim-{name}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"sim-{name}")
    db.add(project)
    await db.flush()
    part = GraphEntity(
        project_id=project.id,
        kind=kinds.PART,
        domain=Domain.MECHANICAL,
        name=name,
        origin="manual",
        attrs=attrs,
    )
    db.add(part)
    await db.commit()
    return project.id, part.id


async def _written(
    sessions: async_sessionmaker[AsyncSession], part_id: uuid.UUID
) -> tuple[int, int, dict[str, Any]]:
    """What the graph holds: its `sim_result` rows, its `verified_by` edges and the part's attrs."""
    async with sessions() as read:
        results = await read.scalar(_counted(kinds.SIM_RESULT))
        verified = select(func.count()).select_from(GraphEdge)
        edges = await read.scalar(verified.where(GraphEdge.relation_type == "verified_by"))
        part = await read.get(GraphEntity, part_id)
    assert part is not None
    return results or 0, edges or 0, part.attrs


def _listening(engine: AsyncEngine) -> tuple[LiveHub, _Heard]:
    hub, heard = LiveHub(), _Heard(engine)
    hub.on_graph_changed = heard
    return hub, heard


async def test_sim_result_carries_solver_inputs_leaves_out_and_verified_by(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    earlier = {"value": 0.2, "unit": "kg", "sim_result_id": "an-earlier-run"}
    project_id, part_id = await _seed(
        db, material={"name": "fake-6061"}, expected={"mass_kg": earlier}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    hub, heard = _listening(engine)

    sim_id = await record_sim_result(
        sessions,
        hub,
        project_id=project_id,
        subject_id=part_id,
        rung=1,
        result=RESULT,
        created_by=None,
    )

    async with sessions() as read:
        row = await read.get(GraphEntity, sim_id)
        part = await read.get(GraphEntity, part_id)
        edges = list(await read.scalars(select(GraphEdge).where(GraphEdge.dst_id == sim_id)))
    assert row is not None and part is not None
    assert (row.kind, row.domain, row.origin, row.name) == (
        kinds.SIM_RESULT,
        Domain.SIMULATION,
        "system",
        "stress_mpa — bracket",
    )
    provenance = row.attrs["provenance"]
    assert provenance["solver"] == "beam_bending"
    assert {name: given["source"] for name, given in provenance["inputs"].items()} == {
        "material": "known",
        "section_modulus_mm3": "derived",
        "load_factor": "assumed",
    }
    assert provenance["leaves_out"] == ["dynamic loads", "fatigue"]
    assert (row.attrs["subject_id"], row.attrs["rung"], row.attrs["values"]) == (
        str(part_id),
        1,
        {"stress_mpa": {"value": 41.4, "unit": "MPa"}},
    )
    [edge] = edges
    assert (edge.src_id, edge.relation_type, edge.origin, edge.confidence) == (
        part_id,
        "verified_by",
        "system",
        1.0,
    )
    assert edge.attrs["evidence"] == [{"kind": "sim", "ref": str(sim_id), "detail": "beam_bending"}]
    assert "matrix_cell" not in edge.attrs  # simulation is none of the three worlds
    assert part.attrs == {
        "material": {"name": "fake-6061"},
        "expected": {
            "mass_kg": earlier,
            "stress_mpa": {"value": 41.4, "unit": "MPa", "sim_result_id": str(sim_id)},
        },
    }  # persisted, so it was reassigned: a JSONB dict mutated in place is never flushed
    assert part.version == 2
    assert heard.heard == [(project_id, 1)]  # its own session saw the committed row

    graph = to_graph_context(Neighborhood(entities=[part, row], edges=edges, truncated=False))
    async with sessions() as read:
        facts = await build_fact_store(read, project_id, graph)
        envelope = await build_envelope(
            read,
            project_id,
            part_id,
            "stress_mpa",
            config=None,
            definition=None,
            scene_joint=None,
            expected=part.attrs["expected"],
            baseline_run=None,
            envelopes=EnvelopesConfig(),
        )
    assert facts.expected(part_id, "stress_mpa") == ExpectedValue(41.4, "MPa", str(sim_id))
    assert envelope is not None and envelope.nominal is not None
    assert (envelope.nominal.lo, envelope.nominal.hi, envelope.unit) == (41.4, 41.4, "MPa")
    assert envelope.bounds_source == {"nominal": "sim"}


async def test_no_provenance_no_write(db: AsyncSession, engine: AsyncEngine) -> None:
    """A result without its full provenance is refused before a session opens: no `sim_result`,
    no edge, no expected value, nothing published. That includes a result with no provenance and
    one holding an empty `model_construct`ed provenance."""
    project_id, part_id = await _seed(db, material={"name": "fake-6061"})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    hub, heard = _listening(engine)
    empty = SimProvenance.model_construct(solver="", inputs={}, leaves_out=())
    for shell in (
        SimResult.model_construct(values=RESULT.values, provenance=None),
        SimResult.model_construct(values=RESULT.values, provenance=empty),
    ):
        with pytest.raises(ValidationError):
            await record_sim_result(
                sessions,
                hub,
                project_id=project_id,
                subject_id=part_id,
                rung=1,
                result=shell,
                created_by=None,
            )
    assert await _written(sessions, part_id) == (0, 0, {"material": {"name": "fake-6061"}})
    assert heard.heard == []


async def test_a_result_that_cannot_serialise_is_refused_as_a_validation_error(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """M127: a malformed constructed result fails its own JSON dump with pydantic's
    `PydanticSerializationError`; the writer refuses it as the `ValidationError` it documents,
    before a session opens — nothing written, nothing published."""
    project_id, part_id = await _seed(db)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    hub, heard = _listening(engine)
    broken = SimResult.model_construct(values={"stress_mpa": object()}, provenance=None)

    with pytest.raises(ValidationError):
        await record_sim_result(
            sessions,
            hub,
            project_id=project_id,
            subject_id=part_id,
            rung=1,
            result=broken,
            created_by=None,
        )
    assert await _written(sessions, part_id) == (0, 0, {})
    assert heard.heard == []


async def test_a_rung_outside_the_ladder_writes_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Only the rungs the config names (1-4) are recorded. P4-T5 reads a rung back as the band's
    `rung` evidence, and a recorded 0 would propose rung 1 again."""
    project_id, part_id = await _seed(db)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    hub, heard = _listening(engine)
    for rung in (0, 5):
        with pytest.raises(ValidationError):
            await record_sim_result(
                sessions,
                hub,
                project_id=project_id,
                subject_id=part_id,
                rung=rung,
                result=RESULT,
                created_by=None,
            )
    assert await _written(sessions, part_id) == (0, 0, {})
    assert heard.heard == []


async def test_a_subject_not_live_in_the_project_writes_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """A subject of another project, a deleted subject or an unknown id is a 404, and nothing is
    written."""
    project_id, part_id = await _seed(db)
    _, foreign = await _seed(db, "elsewhere")
    gone = GraphEntity(
        project_id=project_id,
        kind=kinds.PART,
        domain=Domain.MECHANICAL,
        name="gone",
        origin="manual",
        attrs={},
        deleted_at=utcnow(),
    )
    db.add(gone)
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    hub, heard = _listening(engine)
    for subject in (foreign, gone.id, uuid.uuid4()):
        with pytest.raises(APIError) as refused:
            await record_sim_result(
                sessions,
                hub,
                project_id=project_id,
                subject_id=subject,
                rung=1,
                result=RESULT,
                created_by=None,
            )
        assert (refused.value.status_code, refused.value.code) == (404, "not_found")
    assert await _written(sessions, part_id) == (0, 0, {})
    assert heard.heard == []


async def test_a_subject_another_writer_holds_is_refused_not_waited_for(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """A subject row that another transaction holds is a retryable 409, returned at once. The
    writer holds the project lock, and waiting for the row could deadlock with a sync (R68)."""
    project_id, part_id = await _seed(db)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    hub, heard = _listening(engine)
    async with sessions() as holder:
        await holder.execute(
            select(GraphEntity.id).where(GraphEntity.id == part_id).with_for_update()
        )
        with pytest.raises(APIError) as refused:
            await record_sim_result(
                sessions,
                hub,
                project_id=project_id,
                subject_id=part_id,
                rung=1,
                result=RESULT,
                created_by=None,
            )
        assert (refused.value.status_code, refused.value.code) == (409, "conflict")
    assert await _written(sessions, part_id) == (0, 0, {})
    assert heard.heard == []


async def test_a_failed_publish_leaves_the_run_recorded(
    db: AsyncSession, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Fan-out is never worth a lie about a committed run: a publish that fails is logged with the
    project, and the run stands."""
    project_id, part_id = await _seed(db)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    sim_id = await record_sim_result(
        sessions,
        _DeadRelay(),
        project_id=project_id,
        subject_id=part_id,
        rung=1,
        result=RESULT,
        created_by=None,
    )
    results, edges, attrs = await _written(sessions, part_id)
    assert (results, edges, attrs["expected"]["stress_mpa"]["sim_result_id"]) == (1, 1, str(sim_id))
    assert f"graph fan-out failed project={project_id}" in caplog.text
