"""SOLUSDEV-321 P4-T4 — SOL's simulation tools, `simulate` and `get_sim_result` (R90).

`simulate` asks the ladder which rung answers the person's question and does only what that rung
allows, with no model call. Rung 1 runs in process and is recorded; a value inside its band climbs.
Rung 3 is enqueued as its bounded job and never runs inline. Rungs 2 and 4 are routed: the result
names the target's own gated routine tool, which the model calls next through the gated dispatcher,
and nothing here invokes it. A missing input is asked for once, then raised as the ladder's
standing finding. `get_sim_result` reads one `sim_result` of the project; any other id is not
found.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Final

import pytest
from solus_api.agent.confirmations import _VALUE_CAP, PRECHECK_LABEL, ParkedCall
from solus_api.agent.execution_policy import _AUTHORITY, BuildExecutionPolicy, _canonical
from solus_api.agent.modes import ActionMode
from solus_api.agent.runtime import build_dispatch
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools import apply_sim_change as apply_module
from solus_api.agent.tools import simulate as simulate_module
from solus_api.agent.tools.bench_scene import build_bench_scene_tools
from solus_api.agent.tools.shapes import ToolDescriptor, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.simulate import SimEnqueue, precheck_rows, register_simulation_tools
from solus_api.agent.tools.tool import InProcessTool
from solus_api.agent.turn_context import bind_turn_id
from solus_api.billing.development import SESSION_SETTINGS_KEY
from solus_api.checkers.fact_store import shipped_simulation
from solus_api.graph import kinds
from solus_api.graph.live import LiveHub
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusSection,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from solus_api.orchestration import gateway
from solus_api.orchestration.config import SimTargetConfig, SimulationConfig
from solus_api.simulation.providers.mesh_interference import MeshInterference
from solus_api.simulation.sim_capability import SimResult
from solus_api.simulation.sim_facts import record_sim_result
from solus_api.simulation.sim_ladder import LOCAL_PROVIDERS
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_mesh_interference import _attrs, _cube

MATERIAL: Final = {"name": "fake-6061", "yield_mpa": 276.0, "density_kg_m3": 2700.0, "fake": True}
SECTION: Final = {"shape": "rect", "dims_mm": [30.0, 5.0], "fake": True}
#: The bracket's loads: 15 % of yield, 85 %, and past it (300 MPa against 276).
AT_15: Final = 207.0
AT_85: Final = 1173.0
PAST_YIELD: Final = 1500.0
#: A CAD leaf's placement in its assembly: where it is, as measured.
IDENTITY: Final = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _bracket(force_n: float, **extra: Any) -> dict[str, Any]:
    """The P4 bracket's attrs at `force_n`, its fake material and section labelled as fake."""
    return {
        "section": SECTION,
        "load": {"force_n": force_n, "arm_m": 0.025, "fake": True},
        "material": MATERIAL,
        **extra,
    }


@dataclass(frozen=True)
class _SimProject:
    maker: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID


async def _seed_project(engine: AsyncEngine) -> _SimProject:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(supabase_user_id=f"sim-{uuid.uuid4().hex}", email="sim@example.com")
        team = Team(name="sim")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="sim")
        db.add(project)
        await db.commit()
        return _SimProject(maker, project.id, team.id, user.id)


async def _seed_part(project: _SimProject, name: str = "bracket", **attrs: Any) -> uuid.UUID:
    async with project.maker() as db:
        part = GraphEntity(
            project_id=project.project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name=name,
            attrs=attrs,
        )
        db.add(part)
        await db.commit()
        return part.id


@dataclass
class _Queue:
    """A sim-job enqueue that records what it was handed and runs nothing."""

    calls: list[tuple[str, str, dict[str, Any]]]

    async def __call__(self, job: str, project_id: str, request: dict[str, Any]) -> str:
        self.calls.append((job, project_id, request))
        return f"{job}:{project_id}:queued"


def _registry_for(
    project: _SimProject,
    *,
    enqueue: SimEnqueue | None = None,
    before: tuple[InProcessTool, ...] = (),
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in before:
        registry.register(tool)
    register_simulation_tools(
        registry,
        project.maker,
        project.project_id,
        user_id=project.user_id,
        hub=LiveHub(),
        enqueue_sim=enqueue,
    )
    return registry


async def _simulate_call(registry: ToolRegistry, **args: Any) -> dict[str, Any]:
    result = await registry.invoke(ToolCall(tool="simulate", args=args))
    assert result.ok, result.error
    assert result.value is not None
    return result.value


def _question(subject: uuid.UUID, quantity: str) -> dict[str, str]:
    return {"subject_id": str(subject), "quantity": quantity}


async def _count_kind(project: _SimProject, kind: str) -> int:
    async with project.maker() as db:
        found = select(func.count()).select_from(GraphEntity)
        return await db.scalar(found.where(GraphEntity.kind == kind)) or 0


@pytest.fixture
def _forbid_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rungs 1 and 3 are code: any model call fails the test."""

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a simulation tool called a model")

    monkeypatch.setattr(gateway, "complete", forbidden)
    monkeypatch.setattr(gateway, "stream", forbidden)


@pytest.mark.usefixtures("_forbid_models")
async def test_rung_1_runs_in_process_is_recorded_and_stops_with_margin(
    engine: AsyncEngine,
) -> None:
    project = await _seed_project(engine)
    part = await _seed_part(project, **_bracket(AT_15))
    queue = _Queue([])
    registry = _registry_for(project, enqueue=queue)

    ran = await _simulate_call(registry, question=_question(part, "stress_mpa"))

    assert (ran["decision"], ran["rung"], ran["provider"]) == ("ran", 1, "deterministic_mech")
    assert ran["values"]["stress_mpa"] == {"value": pytest.approx(41.4), "unit": "MPa"}
    assert ran["inputs"]["material"] == "known"
    assert ran["leaves_out"]
    assert ran["verdict"] == "stops" and "stops" in ran["reason"]
    assert queue.calls == []  # with margin, nothing climbs
    async with project.maker() as db:
        recorded = await db.get(GraphEntity, uuid.UUID(ran["sim_result_id"]))
        subject = await db.get(GraphEntity, part)
        verified = await db.scalar(
            select(func.count())
            .select_from(GraphEdge)
            .where(GraphEdge.relation_type == "verified_by", GraphEdge.src_id == part)
        )
    assert recorded is not None and recorded.attrs["rung"] == 1
    assert subject is not None and subject.attrs["expected"]["stress_mpa"][
        "value"
    ] == pytest.approx(41.4)
    assert verified == 1


@pytest.mark.usefixtures("_forbid_models")
async def test_inside_its_band_rung_1_climbs_and_rung_3_is_enqueued_never_run_inline(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def inline(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the mesh check ran in the request path")

    monkeypatch.setattr(MeshInterference, "run", inline)
    project = await _seed_project(engine)
    mesh = _attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20)))
    part = await _seed_part(project, **_bracket(AT_85, **mesh))
    queue = _Queue([])

    ran = await _simulate_call(
        _registry_for(project, enqueue=queue), question=_question(part, "stress_mpa")
    )

    assert (ran["decision"], ran["verdict"]) == ("ran", "climbs")
    assert "85%" in ran["reason"]
    climb = ran["climb"]
    assert (climb["decision"], climb["rung"], climb["provider"]) == (
        "queued",
        3,
        "mesh_interference",
    )
    [(job, project_id, request)] = queue.calls
    assert (job, project_id) == ("run_mesh_sim", str(project.project_id))
    assert climb["job_id"] == f"run_mesh_sim:{project.project_id}:queued"
    assert request["subject_id"] == str(part) and request["requested_by"] == str(project.user_id)
    assert set(request["facts"]) == {"mesh", "load", "section", "material"}


@pytest.mark.usefixtures("_forbid_models")
async def test_without_a_job_queue_rung_3_is_not_available_and_never_runs_inline(
    engine: AsyncEngine,
) -> None:
    project = await _seed_project(engine)
    mesh = _attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20)))
    part = await _seed_part(project, **mesh)

    found = await _simulate_call(
        _registry_for(project), question=_question(part, "interference_mm")
    )

    assert (found["decision"], found["rung"], found["provider"]) == (
        "not_available",
        3,
        "mesh_interference",
    )
    assert "no job queue" in found["reason"]
    assert await _count_kind(project, kinds.SIM_RESULT) == 0


@pytest.mark.usefixtures("_forbid_models")
async def test_a_queue_that_fails_after_rung_1_ran_is_the_climbs_own_line(
    engine: AsyncEngine,
) -> None:
    """M4: rung 1 was recorded before the climb, so a job queue that fails is the climb's own line
    (`not_available`), never a failed call that would hide the run that was recorded."""

    async def down(job: str, project_id: str, request: dict[str, Any]) -> str:
        raise ConnectionError("the job queue is down")

    project = await _seed_project(engine)
    mesh = _attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20)))
    part = await _seed_part(project, **_bracket(AT_85, **mesh))

    ran = await _simulate_call(
        _registry_for(project, enqueue=down), question=_question(part, "stress_mpa")
    )

    assert (ran["decision"], ran["verdict"]) == ("ran", "climbs")
    assert ran["climb"]["decision"] == "not_available"
    assert "did not take the job" in ran["climb"]["reason"]
    assert await _count_kind(project, kinds.SIM_RESULT) == 1  # rung 1's run stands


def _gated_routine(name: str, ran: list[dict[str, Any]]) -> InProcessTool:
    """A gated routine tool, standing in for a connected target's own."""

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        ran.append(args)
        return {"ok": True}

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"label": "Routine", "before": None, "after": "a bounded joint trajectory"}]

    descriptor = ToolDescriptor(
        name=name,
        description="Run a bounded routine on the connected simulator.",
        params={"type": "object", "properties": {}, "additionalProperties": True},
        returns={"type": "object"},
        requires_confirmation=True,
    )
    return InProcessTool(descriptor, run, preview)


def _with_target(monkeypatch: pytest.MonkeyPatch, *targets: SimTargetConfig) -> SimulationConfig:
    """The shipped config with these targets added, as the tools read it at registration."""
    shipped = shipped_simulation()
    simulation = SimulationConfig(
        escalate_at=shipped.escalate_at,
        bands=dict(shipped.bands),
        targets=(*shipped.targets, *targets),
    )
    monkeypatch.setattr(simulate_module, "shipped_simulation", lambda: simulation)
    return simulation


def _owned_routine(name: str, ran: list[dict[str, Any]]) -> InProcessTool:
    """`_gated_routine`, owned as trusted assembly owns `isaac.run_routine`: a complete preview
    and the Build policy's own authority, so in Build mode it runs without its card."""
    tool = _gated_routine(name, ran)
    owned: Any = tool
    owned.requires_complete_preview = True
    owned._build_authority = _AUTHORITY, _canonical(tool.descriptor.model_dump())
    return tool


@pytest.mark.usefixtures("_forbid_models")
async def test_rung_2_and_4_are_gated(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rungs 2 and 4 run nowhere here: `simulate` names the target's own gated routine tool, and
    in the turn it routed, a call of that tool waits behind its card even where Build would run
    the routine on its own (M1): the person asked to simulate, not to run a routine."""
    simulation = _with_target(
        monkeypatch,
        SimTargetConfig(name="routing_x", rung=2, domain="mechanical", quantities=("ripple_v",)),
    )
    full = next(target for target in simulation.targets if target.rung == 4)
    project = await _seed_project(engine)
    part = await _seed_part(project)
    ran: list[dict[str, Any]] = []
    routine = f"{full.name}.run_routine"
    registry = _registry_for(project, before=(_owned_routine(routine, ran),))
    descriptors = {d.name: d for d in registry.list()}
    assert not descriptors["simulate"].requires_confirmation  # rungs 1 and 3 are ungated code
    assert not descriptors["get_sim_result"].requires_confirmation

    parked: list[ToolCall] = []

    async def park(call: ToolCall) -> ParkedCall:
        parked.append(call)
        waiting = ToolError(code=ToolErrorCode.UNAUTHORIZED, message="waiting for the person")
        return ParkedCall(
            uuid.uuid4(),
            call.tool,
            dict(call.args),
            "",
            [],
            ToolResult.failure(call.call_id, waiting),
        )

    with bind_turn_id(uuid.uuid4()):  # the person asks for the routine itself: Build runs it
        policy = BuildExecutionPolicy(registry, ActionMode.DO)
        asked = await build_dispatch(registry, park, routine_policy=policy)(
            ToolCall(tool=routine, args={})
        )
    assert asked.ok and len(ran) == 1 and parked == []

    with bind_turn_id(uuid.uuid4()):
        full_run = await _simulate_call(registry, question=_question(part, full.quantities[0]))
        assert full_run["decision"] == "route"
        assert full_run["route"] == {
            "rung": 4,
            "target": full.name,
            "tool": routine,
            "gate": "per call",
            "connected": True,
            "status": f"call {routine}: it previews the run and its gate decides per call",
        }
        routed = await _simulate_call(registry, question=_question(part, "ripple_v"))
        assert routed["route"]["rung"] == 2 and routed["route"]["tool"] == "routing_x.run_routine"
        assert (routed["route"]["connected"], routed["route"]["status"]) == (False, "not connected")
        assert len(ran) == 1  # naming a tool runs nothing
        policy = BuildExecutionPolicy(registry, ActionMode.DO)
        result = await build_dispatch(registry, park, routine_policy=policy)(
            ToolCall(tool=full_run["route"]["tool"], args={})
        )
    assert result.ok is False and [call.tool for call in parked] == [routine]
    assert len(ran) == 1  # the routine simulate routed waits behind its card, even in Build mode


@pytest.mark.usefixtures("_forbid_models")
async def test_ask_once_then_the_missing_input_is_a_finding_and_nothing_runs(
    engine: AsyncEngine,
) -> None:
    project = await _seed_project(engine)
    part = await _seed_part(project, section=SECTION, load={"force_n": AT_15, "arm_m": 0.025})
    registry = _registry_for(project)

    asked = await _simulate_call(registry, question=_question(part, "stress_mpa"))
    assert (asked["decision"], asked["provider"]) == ("ask", "deterministic_mech")
    assert [need["name"] for need in asked["missing"]] == ["material"]
    async with project.maker() as db:
        subject = await db.get(GraphEntity, part)
    assert subject is not None and subject.attrs["sim_asked"] == {"stress_mpa": ["material"]}

    stopped = await _simulate_call(registry, question=_question(part, "stress_mpa"))
    assert stopped["decision"] == "missing_input"
    async with project.maker() as db:
        finding = await db.get(GraphEntity, uuid.UUID(stopped["finding_id"]))
    assert finding is not None and finding.attrs["rule_id"] == "simulation_missing_input"
    assert "material unknown" in finding.attrs["headline"]
    assert await _count_kind(project, kinds.SIM_RESULT) == 0


async def _read_rows(registry: ToolRegistry, sim_result_id: str) -> ToolResult:
    return await registry.invoke(
        ToolCall(tool="get_sim_result", args={"sim_result_id": sim_result_id})
    )


async def test_get_sim_result_reads_this_projects_result_and_nothing_else(
    engine: AsyncEngine,
) -> None:
    project = await _seed_project(engine)
    part = await _seed_part(project, **_bracket(AT_15))
    registry = _registry_for(project)
    ran = await _simulate_call(registry, question=_question(part, "stress_mpa"))

    read = await _read_rows(registry, ran["sim_result_id"])
    assert read.ok and read.value is not None
    rows = [json.loads(line) for line in read.value["text"].splitlines()]
    assert rows[0]["id"] == ran["sim_result_id"] and rows[0]["subject_id"] == str(part)
    assert rows[0]["rung"] == 1 and rows[0]["solver"].startswith("deterministic_mech:")
    stress = next(row for row in rows if row.get("quantity") == "stress_mpa")
    assert stress == {"quantity": "stress_mpa", "value": pytest.approx(41.4), "unit": "MPa"}
    assert any("leaves_out" in row for row in rows)
    assert any(row.get("input") == "material" and row["source"] == "known" for row in rows)

    other = await _seed_project(engine)
    foreign_part = await _seed_part(other, **_bracket(AT_15))
    result = SimResult.model_validate(
        {
            "values": {"stress_mpa": {"value": 41.4, "unit": "MPa"}},
            "provenance": {
                "solver": "x",
                "inputs": {"a": {"value": 1, "source": "known"}},
                "leaves_out": ["y"],
            },
        }
    )
    foreign = await record_sim_result(
        other.maker,
        LiveHub(),
        project_id=other.project_id,
        subject_id=foreign_part,
        rung=1,
        result=result,
        created_by=None,
    )
    for missing in (str(foreign), str(part), str(uuid.uuid4())):
        refused = await _read_rows(registry, missing)
        assert refused.ok is False and refused.error is not None
        assert refused.error.code is ToolErrorCode.NOT_FOUND


@pytest.mark.usefixtures("_forbid_models")
async def test_a_failing_result_names_the_domain_that_owns_its_fix_or_says_to_set_it(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subject's `attrs.owning_domain` names the domain that owns the fix. Without it, the
    destination side of the cell whose rule judges the failing value does (M141): the bracket's
    yield, mechanical. With neither, the loop says to set the attr."""
    project = await _seed_project(engine)
    owned = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="runtime"))
    unowned = await _seed_part(project, name="unowned", **_bracket(PAST_YIELD))
    registry = _registry_for(project)

    failing = await _simulate_call(registry, question=_question(owned, "stress_mpa"))
    assert failing["verdict"] == "fails"
    assert failing["values"]["yield_fraction"]["value"] >= 1
    loop = failing["backward_loop"]
    assert loop["owning_domain"] == "runtime" and "change" in loop["next"]

    derived = await _simulate_call(registry, question=_question(unowned, "stress_mpa"))
    assert derived["verdict"] == "fails"
    assert derived["backward_loop"]["owning_domain"] == "mechanical"

    monkeypatch.setattr(apply_module, "fix_owner", lambda quantity: None)
    alone = await _simulate_call(registry, question=_question(unowned, "stress_mpa"))
    assert alone["backward_loop"]["owning_domain"] is None
    assert "attrs.owning_domain" in alone["backward_loop"]["next"]


@pytest.mark.usefixtures("_forbid_models")
async def test_a_persons_provider_choice_is_used_and_remembered_as_a_style_entry(
    engine: AsyncEngine,
) -> None:
    project = await _seed_project(engine)
    mesh = _attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20)))
    part = await _seed_part(project, **_bracket(AT_15, **mesh))
    queue = _Queue([])
    registry = _registry_for(project, enqueue=queue)

    chosen = await _simulate_call(
        registry, question=_question(part, "stress_mpa"), provider="mesh_interference"
    )

    assert (chosen["decision"], chosen["provider"]) == ("queued", "mesh_interference")
    assert chosen["remembered_as"] == "simulate stress_mpa with mesh_interference"
    async with project.maker() as db:
        entries = list(
            await db.scalars(
                select(SolusEntry).where(
                    SolusEntry.project_id == project.project_id,
                    SolusEntry.section == SolusSection.CONSTRAINTS,
                    SolusEntry.subsection == "style",
                )
            )
        )
    assert [(entry.text, entry.author) for entry in entries] == [
        ("simulate stress_mpa with mesh_interference", "sol")
    ]
    refused = await registry.invoke(
        ToolCall(
            tool="simulate",
            args={"question": _question(part, "stress_mpa"), "provider": "deterministic_elec"},
        )
    )
    assert refused.ok is False and refused.error is not None
    assert refused.error.code is ToolErrorCode.INVALID_ARGS


async def test_a_subject_outside_the_project_is_not_found(engine: AsyncEngine) -> None:
    project = await _seed_project(engine)
    other = await _seed_project(engine)
    theirs = await _seed_part(other, **_bracket(AT_15))
    for subject in (theirs, uuid.uuid4()):
        result = await _registry_for(project).invoke(
            ToolCall(tool="simulate", args={"question": _question(subject, "stress_mpa")})
        )
        assert result.ok is False and result.error is not None
        assert result.error.code is ToolErrorCode.NOT_FOUND
    assert await _count_kind(project, kinds.SIM_RESULT) == 0


async def test_the_tools_register_only_with_a_person_and_the_hub(engine: AsyncEngine) -> None:
    """R90: both tools act as the requesting person, so a bare registry is still the reference
    tool alone, whatever else is bound; `simulate` and its gated apply also need the app's hub,
    which every recorded run publishes through (M69)."""
    from solus_api.agent.runtime import build_sol_registry

    project = await _seed_project(engine)
    hub = LiveHub()

    def names(**bound: Any) -> set[str]:
        registry = build_sol_registry(project.maker, project.project_id, **bound)
        return {descriptor.name for descriptor in registry.list()}

    assert names() == {"get_entity"}
    assert names(graph_hub=hub, enqueue_sim=_Queue([])) == {"get_entity"}
    person = names(user_id=project.user_id)
    assert "get_sim_result" in person and not {"simulate", "apply_sim_change"} & person
    wired = build_sol_registry(
        project.maker, project.project_id, user_id=project.user_id, graph_hub=hub
    )
    gates = {d.name: d.requires_confirmation for d in wired.list()}
    assert (gates["simulate"], gates["apply_sim_change"], gates["get_sim_result"]) == (
        False,
        True,
        False,
    )


async def _written(project: _SimProject) -> tuple[int, int, int, int]:
    """What a dry run must leave alone: findings, sim results, edges and `.solus` entries."""
    async with project.maker() as db:
        entities = select(func.count()).select_from(GraphEntity)
        findings = await db.scalar(entities.where(GraphEntity.kind == kinds.FINDING))
        results = await db.scalar(entities.where(GraphEntity.kind == kinds.SIM_RESULT))
        edges = await db.scalar(select(func.count()).select_from(GraphEdge))
        solus = await db.scalar(select(func.count()).select_from(SolusEntry))
    return findings or 0, results or 0, edges or 0, solus or 0


async def test_backward_loop_dry_runs_applies_once_behind_a_card_and_reruns(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R91: a failing result names its owning domain; SOL proposes a change there; `simulate`
    dry-runs it on a pair of fact stores and returns it, reaching no writer (M7: the writers are
    watched, over a project a writing matrix run would write to); `apply_sim_change` waits behind
    a card even in Build mode, at most once per turn; and only the approval writes the change and
    re-runs rung 1."""
    from fixtures.fake_arm import seed_fake_arm
    from solus_api.agent.confirmations import decide_confirmation, request_confirmation
    from solus_api.agent.tools import apply_sim_change as apply_module
    from solus_api.checkers import matrix_runner
    from solus_api.checkers.fact_store import FactStore

    project = await _seed_project(engine)
    async with project.maker() as db:  # commands edges and a standing info a writing run keeps
        await seed_fake_arm(db, project.project_id, user_id=None)
        await db.commit()
    part = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="project"))
    registry = _registry_for(project)
    dry_runs: list[dict[str, Any]] = []
    matrix = matrix_runner.run_matrix

    async def counted(session: AsyncSession, project_id: uuid.UUID, **kwargs: Any) -> Any:
        dry_runs.append(kwargs)
        return await matrix(session, project_id, **kwargs)

    monkeypatch.setattr(apply_module, "run_matrix", counted)
    writes: list[str] = []

    def watched(module: Any, name: str) -> None:
        real = getattr(module, name)

        async def seam(*args: Any, **kwargs: Any) -> Any:
            writes.append(name)
            return await real(*args, **kwargs)

        monkeypatch.setattr(module, name, seam)

    for module, name in (
        (apply_module, "put_entity_config"),
        (apply_module, "add_text_entry"),
        (matrix_runner, "annotate_edge"),
        (matrix_runner, "raise_finding"),
    ):
        watched(module, name)
    parked: list[ParkedCall] = []

    async def park(call: ToolCall) -> ParkedCall | None:
        async with project.maker() as db:
            found = await request_confirmation(
                db,
                registry,
                call,
                project_id=project.project_id,
                team_id=project.team_id,
                user_id=project.user_id,
            )
            await db.commit()
        if found is not None:
            parked.append(found)
        return found

    dispatch = build_dispatch(
        registry, park, routine_policy=BuildExecutionPolicy(registry, ActionMode.DO)
    )
    change = {"kind": "constraint", "subsection": "rules", "text": "keep the load under 900 N"}
    other = {"kind": "constraint", "subsection": "rules", "text": "keep the load under 800 N"}
    question = _question(part, "stress_mpa")
    with bind_turn_id(uuid.uuid4()):
        failing = await _simulate_call(registry, question=question)
        assert failing["verdict"] == "fails"
        assert failing["backward_loop"]["owning_domain"] == "project"
        before = await _written(project)

        dry = await _simulate_call(registry, question=question, change=change)

        assert writes == []  # a dry run reaches no writer: no config, entry, edge or finding
        assert (dry["decision"], dry["owning_domain"], dry["appliable"]) == (
            "dry_run",
            "project",
            True,
        )
        assert [kwargs["dry_run"] for kwargs in dry_runs] == [True, True]
        assert all(isinstance(kwargs["facts"], FactStore) for kwargs in dry_runs)
        assert dry["apply"]["tool"] == "apply_sim_change"

        first = await dispatch(ToolCall(tool="apply_sim_change", args=dry["apply"]["args"]))
        assert first.ok is False  # behind a card, in Build mode too
        [card] = parked
        assert card.confirmation_id is not None
        assert any(row["after"] == change["text"] for row in card.preview)
        assert writes == [] and await _written(project) == before  # nothing before the approval

        again = await _simulate_call(registry, question=question, change=other)
        second = await dispatch(ToolCall(tool="apply_sim_change", args=again["apply"]["args"]))
        assert second.ok is False and second.error is not None
        assert "one simulation change per turn" in second.error.message.lower()
        assert [found.confirmation_id is not None for found in parked] == [True, False]

    async with project.maker() as db:
        approved = await decide_confirmation(
            db,
            registry,
            card.confirmation_id,
            approve=True,
            project_id=project.project_id,
            user_id=project.user_id,
        )
        await db.commit()

    assert approved.ok, approved.error
    assert writes == ["add_text_entry"]  # the approval's one write, through the owner's writer
    assert approved.value is not None and approved.value["applied"] == dry["change_text"]
    findings, results, _, solus = await _written(project)
    assert (findings, results, solus) == (before[0], before[1] + 1, before[3] + 1)
    rerun = approved.value["rerun"]
    assert rerun["sim_result_id"] and rerun["verdict"] == "fails"  # the rule changed no attr
    async with project.maker() as db:
        rules = list(
            await db.scalars(
                select(SolusEntry).where(
                    SolusEntry.project_id == project.project_id,
                    SolusEntry.subsection == "rules",
                )
            )
        )
    assert [(entry.text, entry.author) for entry in rules] == [(change["text"], "sol")]


@pytest.mark.usefixtures("_forbid_models")
async def test_a_gated_actions_pre_check_shows_what_the_ladder_proposes_and_runs_nothing(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R99: the pre-check a gated real-world action's preview makes is one card row per proposal
    the ladder makes for the matrix's inconclusive results about what the action touches. The
    bracket at 85 % of its yield is one, the bracket with margin is none, and a card with no room
    left gets none. It writes and runs nothing."""
    project = await _seed_project(engine)
    near = await _seed_part(project, name="near", **_bracket(AT_85))
    easy = await _seed_part(project, name="easy", **_bracket(AT_15))
    registry = _registry_for(project)
    for part in (near, easy):
        await _simulate_call(registry, question=_question(part, "yield_fraction"))
    ran = await _count_kind(project, kinds.SIM_RESULT)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a pre-check ran a simulation")

    for provider in LOCAL_PROVIDERS:
        monkeypatch.setattr(type(provider), "run", forbidden)
    # Minor 8: rung 3 runs only as a job, so the line says so where no queue takes one, read as
    # `simulate` reads it: the settings the session runs under.
    queue = SimpleNamespace(redis_url="redis://queue", sync_inline=False)
    queued = async_sessionmaker(engine, info={SESSION_SETTINGS_KEY: queue})
    async with queued() as db:
        rows = await precheck_rows(db, project.project_id, project.user_id, [near, easy], room=8)
        beside = await precheck_rows(db, project.project_id, project.user_id, [easy], room=8)
        full = await precheck_rows(db, project.project_id, project.user_id, [near], room=0)
    async with project.maker() as db:
        unqueued = await precheck_rows(db, project.project_id, project.user_id, [near], room=8)

    line = (
        "near: yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band. "
        "Simulate yield_fraction at rung 3 with mesh_interference first"
    )
    assert rows == [{"label": PRECHECK_LABEL, "before": None, "after": line}]
    assert [row["after"] for row in unqueued] == [f"{line}; no job queue runs it here"]
    assert beside == full == [] and await _count_kind(project, kinds.SIM_RESULT) == ran
    assert "simulation pre-check skipped" not in caplog.text


@pytest.mark.usefixtures("_forbid_models")
async def test_a_pre_check_fits_the_room_and_the_value_cap_its_card_leaves(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor 3 and 4: the rows stay within the room the card's own rows leave, and each line
    within the card's value cap, so the pre-check alone can never make the gate refuse a card."""
    project = await _seed_project(engine)
    parts = [await _seed_part(project, name=name, **_bracket(AT_85)) for name in ("a", "b")]
    registry = _registry_for(project)
    for part in parts:
        await _simulate_call(registry, question=_question(part, "yield_fraction"))
    monkeypatch.setattr(simulate_module, "proposal_line", lambda proposal, subject: "x" * 600)

    async with project.maker() as db:
        both = await precheck_rows(db, project.project_id, project.user_id, parts, room=8)
        one = await precheck_rows(db, project.project_id, project.user_id, parts, room=1)

    assert [len(row["after"]) for row in both] == [_VALUE_CAP, _VALUE_CAP]
    assert one == both[:1]


@pytest.mark.usefixtures("_forbid_models")
@pytest.mark.parametrize("failure", ["raises", "outlasts its timeout"])
async def test_a_pre_check_that_fails_adds_no_row_and_leaves_its_callers_session_usable(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    """Important 2: a pre-check that raises, or whose read outlasts its own timeout, is logged
    and adds no row. It reads on its own connection, so a read cut short mid-query never
    invalidates the caller's session (an approval's holds the card's row lock)."""
    project = await _seed_project(engine)
    near = await _seed_part(project, name="near", **_bracket(AT_85))
    await _simulate_call(_registry_for(project), question=_question(near, "yield_fraction"))

    async def stalled(session: AsyncSession, *args: Any) -> Any:
        await session.execute(select(func.pg_sleep(5)))

    def broken(*args: Any) -> Any:
        raise RuntimeError("the facts did not read")

    monkeypatch.setattr(simulate_module, "PRECHECK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(
        simulate_module, "build_fact_store", broken if failure == "raises" else stalled
    )
    async with project.maker() as db:
        assert await precheck_rows(db, project.project_id, project.user_id, [near], room=8) == []
        assert await db.scalar(select(GraphEntity.name).where(GraphEntity.id == near)) == "near"
    assert "simulation pre-check skipped" in caplog.text


@pytest.mark.usefixtures("_forbid_models")
async def test_a_pre_check_reads_nothing_of_another_project(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Minor 9: an id of project B, pre-checked under project A's scope, yields no row and no
    error, though B's own pre-check of it proposes a run."""
    mine, theirs = await _seed_project(engine), await _seed_project(engine)
    near = await _seed_part(theirs, name="near", **_bracket(AT_85))
    await _simulate_call(_registry_for(theirs), question=_question(near, "yield_fraction"))

    async with mine.maker() as db:
        foreign = await precheck_rows(db, mine.project_id, mine.user_id, [near], room=8)
        own = await precheck_rows(db, theirs.project_id, theirs.user_id, [near], room=8)

    assert foreign == [] and [row["label"] for row in own] == [PRECHECK_LABEL]
    assert "simulation pre-check skipped" not in caplog.text


async def _cad_leaf(project: _SimProject, **attrs: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """A robot, and a synced CAD leaf the Bench can import as static geometry."""
    async with project.maker() as db:
        source = Source(
            project_id=project.project_id,
            team_id=project.team_id,
            name="CAD",
            type=SourceType.ONSHAPE,
            status=SourceStatus.CONNECTED,
            secret_ref="test-reference",
            config={"documents": ["doc"]},
        )
        db.add(source)
        await db.flush()
        robot = GraphEntity(
            project_id=project.project_id,
            kind=kinds.PHYSICAL_ROBOT,
            domain=Domain.RUNTIME,
            origin="manual",
            name="robot",
        )
        leaf = GraphEntity(
            project_id=project.project_id,
            source_id=source.id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="connector",
            name="CAD leaf",
            external_ref="doc:element:shape",
            attrs={
                "is_assembly": False,
                "document_id": "doc",
                "element_id": "element",
                "observed_microversion": "r1",
                "parent_transform": {"length_unit": "mm", "matrix": IDENTITY},
                **attrs,
            },
        )
        db.add_all([robot, leaf])
        await db.commit()
        return robot.id, leaf.id


@pytest.mark.usefixtures("_forbid_models")
async def test_the_cad_import_card_shows_the_simulation_the_ladder_proposes_first(
    engine: AsyncEngine,
) -> None:
    """R99, wired into a gated tool: `bench.import_cad_scene`'s preview gains one row per
    simulation the ladder proposes for the parts the import touches, here a leaf a rung-1 run found
    at 85 % of its yield. Its own rows lead unchanged, and before the run there is no such row."""
    project = await _seed_project(engine)
    robot, leaf = await _cad_leaf(project, **_bracket(AT_85))

    async def never(session: AsyncSession, row: GraphEntity) -> uuid.UUID:
        raise AssertionError("a preview enqueued the import")

    tools = {
        tool.descriptor.name: tool
        for tool in build_bench_scene_tools(
            project.maker, project.project_id, project.user_id, never
        )
    }
    tool = tools["bench.import_cad_scene"]
    args = {"robot_id": str(robot), "source_entity_id": str(leaf), "expected_revision": "r1"}

    before = await tool.preview(args)
    await _simulate_call(_registry_for(project), question=_question(leaf, "yield_fraction"))
    after = await tool.preview(args)

    assert [row["label"] for row in before] == [
        "Robot",
        "CAD source",
        "Source revision",
        "Geometry",
    ]
    assert after[:4] == before and tool.descriptor.requires_confirmation
    assert after[4:] == [
        {
            "label": PRECHECK_LABEL,
            "before": None,
            "after": (
                "CAD leaf: yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band. "
                "Simulate yield_fraction at rung 3 with mesh_interference first; no job queue "
                "runs it here"
            ),
        }
    ]
