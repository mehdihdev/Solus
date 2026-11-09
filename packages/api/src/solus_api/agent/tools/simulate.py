"""SOLUSDEV-321 P4-T4 — SOL's simulation tools, `simulate` and `get_sim_result`
(docs/api/simulation.md §8).

`simulate(question, scope?, provider?, change?)` asks the ladder (`simulation/sim_ladder.py`)
which rung answers the person's question and whether it can run, then does only what that rung
allows. No rung makes a model call.

- **Rung 1 runs here**, in process: closed-form code, ungated, recorded through
  `record_sim_result`. A value inside its band then climbs: the ladder is asked again above rung 1.
- **Rung 3 is enqueued** as its bounded ARQ job (`run_mesh_sim`, `run_ngspice_sim`,
  `run_mujoco_sim`), which records its own run. The result names the job; nothing runs inline.
  With no job queue, or a queue that does not take the job, the result says so (`not_available`):
  a climb's failed enqueue never fails the rung-1 run already recorded.
- **Rungs 2 and 4 are routed, never run**: the result names the target's own gated routine tool
  (`simulation/providers/external_providers.py`). The model calls it next through the gated
  dispatcher, so the call keeps that tool's gate, and in the turn that routed it, its card even
  where Build would run the routine on its own (`routed_by_simulation`, M1). Nothing here invokes
  a tool.
- **`ask`** is recorded on the subject (`attrs.sim_asked[quantity]`, reassigned), so it is asked
  once; **`missing_input`** raises the ladder's standing info finding, and nothing runs.

A rung-1 value at or past a limit the result states itself (`yield_fraction >= 1`) fails, is noted
for the turn, and the backward loop starts (`agent/tools/apply_sim_change.py`): the subject's
`attrs.owning_domain` names the domain that owns the fix, else the cell of the rule that judges the
failing value does (M141), and there is no loop with neither. SOL
passes its change in that domain as `change`, and `simulate` dry-runs it against the turn's
failing result and returns it, applying nothing; `apply_sim_change` applies it behind a card. A
person's choice of `provider` is used for the run and, when it was not the
ladder's own choice and the run happened, remembered as a `constraints/style` entry.

`get_sim_result(id)` reads one `sim_result` of this project; any other id is not found. The
project and the person are bound at registration, and no argument names either.

`precheck_rows(session, project_id, user_id, touched, room=)` is the pre-check a gated real-world
action's preview makes (P4-T5, R99): the matrix judged over what the action touches, under the
person's own read scope, and one card row per simulation the ladder proposes for its
`inconclusive` results, within the room the card's own rows leave. It writes and runs nothing, on
its own connection and under its own timeout; one that fails adds no row and the card keeps its
others, and the gate's staleness check leaves these rows out (R118).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.confirmations import _VALUE_CAP, PRECHECK_LABEL
from solus_api.agent.tools.apply_sim_change import (
    YIELD_FRACTION,
    change_schema,
    dry_run_change,
    is_failing,
    note_failing,
    note_routed,
    owning_domain,
    parse_change,
    register_apply_sim_change_tool,
)
from solus_api.agent.tools.read_tool import (
    RESULT_CAP,
    ReadResult,
    bounded_read_tool,
    uuid_arg,
    uuid_params,
)
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.billing.development import SESSION_SETTINGS_KEY
from solus_api.checkers.fact_store import StyleEntry, build_fact_store, shipped_simulation
from solus_api.checkers.matrix_rule import RuleResult
from solus_api.checkers.matrix_runner import judge_matrix
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.findings import raise_finding
from solus_api.graph.neighborhood import load_neighborhood, to_graph_context
from solus_api.graph.read_scope import bind_scope, current_scope, resolve_scope
from solus_api.livebench.findings.rules.rule_base import shown
from solus_api.models import GraphEntity, SolusSection
from solus_api.services.solus_config import add_text_entry
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.mesh_job import run_mesh_sim
from solus_api.simulation.providers.external_providers import ExternalProviders
from solus_api.simulation.providers.mesh_interference import MeshInterference
from solus_api.simulation.providers.mujoco_job import RigidBodyTrajectory, run_mujoco_sim
from solus_api.simulation.providers.ngspice_provider import NgspiceProvider, run_ngspice_sim
from solus_api.simulation.sim_capability import SimProvider, SimQuestion
from solus_api.simulation.sim_facts import SimJobRequest, record_sim_result
from solus_api.simulation.sim_ladder import (
    LOCAL_PROVIDERS,
    STYLE_LINE,
    LadderContext,
    SimProposal,
    asked_names,
    available_targets,
    jobs_queued,
    ladder_context,
    missing_input_finding,
    precheck_real_world_action,
    proposal_line,
    propose_for,
    should_simulate,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from solus_api.agent.interfaces import EntityRead, GraphContext
    from solus_api.agent.tools.registry import ToolRegistry
    from solus_api.checkers.fact_store import FactStore
    from solus_api.graph.live import LiveHub
    from solus_api.orchestration.config import SimulationConfig
    from solus_api.simulation.sim_capability import SimInput, SimResult

logger = logging.getLogger("solus.agent.tools.simulate")

SIMULATE: Final = "simulate"
GET_SIM_RESULT: Final = "get_sim_result"
#: The bounded job that runs each rung-3 provider, by the provider's name. Each records its run.
RUNG_3_JOBS: Final[Mapping[str, str]] = {
    MeshInterference.name: run_mesh_sim.__name__,
    NgspiceProvider.name: run_ngspice_sim.__name__,
    RigidBodyTrajectory.name: run_mujoco_sim.__name__,
}
#: The most entities a question's scope names besides its subject, and how far around them the
#: facts a ladder and a dry run read reach.
MAX_SCOPE: Final = 16
SCOPE_DEPTH: Final = 2
#: The stress a yield fraction is the fraction of (the limit the result states for it).
STRESS: Final = "stress_mpa"
NO_QUEUE: Final = (
    "no job queue on this server: rung 3 runs only as its bounded job, never in a SOL request"
)
#: The style entry a person's `provider` choice adds for one run, before it is remembered.
_OVERRIDE: Final = uuid.UUID(int=0)
_API_CODES: Final = {404: ToolErrorCode.NOT_FOUND, 409: ToolErrorCode.TOOL_ERROR}

#: Enqueues one rung-3 job: (job name, project id, request) → the job's id.
type SimEnqueue = Callable[[str, str, dict[str, Any]], Awaitable[str]]


class _Runs(SimProvider, Protocol):
    """A provider that runs in a Solus process: it reads its inputs from a subject's facts."""

    def inputs_for(self, facts: Mapping[str, Any]) -> dict[str, SimInput]: ...


def _proposal_view(proposal: SimProposal) -> dict[str, Any]:
    """What a result says of the ladder's proposal."""
    view: dict[str, Any] = {
        "rung": proposal.rung,
        "provider": proposal.target,
        "reason": proposal.reason,
        "alternatives": list(proposal.alternatives),
    }
    if proposal.missing:
        view["missing"] = [need.model_dump() for need in proposal.missing]
    if proposal.leaves_out:
        view["leaves_out"] = list(proposal.leaves_out)
    return view


def _self_limited(result: SimResult, quantity: str) -> tuple[float, float] | None:
    """`quantity`'s value and the limit the result itself states for it: the fraction of yield
    against 1, or the stress against the yield it is that fraction of. None for anything else."""
    fraction = result.values.get(YIELD_FRACTION)
    if fraction is None or fraction.value <= 0:
        return None
    if quantity == YIELD_FRACTION:
        return fraction.value, 1.0
    stress = result.values.get(STRESS)
    if quantity == STRESS and stress is not None:
        return stress.value, stress.value / fraction.value
    return None


def _owning_loop(subject: EntityRead) -> dict[str, Any]:
    """Where the backward loop goes from a failing result: the domain that owns the fix, or what
    the person must state first."""
    owner = owning_domain(subject.attrs)
    if owner is not None:
        return {
            "owning_domain": owner,
            "next": (
                f"propose a change in the {owner} domain as `change` to simulate: it dry-runs the "
                "change and returns it for apply_sim_change, which asks the person"
            ),
        }
    return {
        "owning_domain": None,
        "next": (
            f"set attrs.owning_domain on {shown(subject.name)} to the domain that owns the fix: no "
            "change is proposed without it"
        ),
    }


class SimulationTools:
    """`simulate`, bound to ONE project and person (the module docstring)."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        hub: LiveHub,
        enqueue_sim: SimEnqueue | None,
        external: ExternalProviders,
        config: SimulationConfig,
    ) -> None:
        self.sessions, self.project_id, self.user_id = sessions, project_id, user_id
        self.hub, self.enqueue_sim, self.external, self.config = hub, enqueue_sim, external, config
        local: tuple[_Runs, ...] = LOCAL_PROVIDERS  # the ladder's one roster
        self.local = {provider.name: provider for provider in local}
        self.providers: tuple[SimProvider, ...] = (*local, *external.targets)
        self.available = available_targets(
            queued=enqueue_sim is not None, connected=external.connected
        )

    def descriptor(self) -> ToolDescriptor:
        quantities = sorted({q for provider in self.providers for q in provider.quantities})
        return ToolDescriptor(
            name=SIMULATE,
            description=(
                "Simulate ONE quantity of one entity in this project. Solus picks the "
                "cheapest rung that can answer and says why. Rung 1 (closed-form code) runs "
                "now and is recorded; a value inside its band climbs on its own. Rung 3 (the "
                "mesh check, a circuit transient, a rigid-body trajectory) is queued as a job "
                "that records its own result: read it later with get_sim_result. Rungs 2 and 4 "
                "(external simulators) are only named, with the gated tool to call next, which "
                "asks the person. An input nobody stated is asked for once, then raised as a "
                "finding. A rung-1 result at or past its own limit says which domain owns the "
                "fix: pass your proposed change there as `change` to dry-run it. Nothing is "
                "applied; apply_sim_change applies it once the person approves."
            ),
            params=_simulate_params(quantities, sorted(p.name for p in self.providers)),
            returns={"type": "object"},
            requires_confirmation=False,
            timeout_seconds=60,
            result_cap=RESULT_CAP,
        )

    async def simulate(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._simulate(args)
        except APIError as exc:  # a loader's 404, the facts writer's retryable 409: typed
            code = _API_CODES.get(exc.status_code, ToolErrorCode.TOOL_ERROR)
            raise ToolException(exc.message, code=code, retryable=exc.status_code == 409) from None

    async def _simulate(self, args: dict[str, Any]) -> dict[str, Any]:
        question = args["question"]
        subject_id = uuid_arg(question, "subject_id")
        quantity = str(question["quantity"])
        provider = args.get("provider")
        if provider is not None and not any(
            p.name == provider and quantity in p.quantities for p in self.providers
        ):
            raise ToolException(
                f"{provider} does not compute {quantity}", code=ToolErrorCode.INVALID_ARGS
            )
        change = parse_change(args["change"]) if "change" in args else None
        scope = [uuid.UUID(str(item)) for item in args.get("scope", [])][:MAX_SCOPE]
        graph, subject, facts = await self._read(subject_id, scope)
        if change is not None:
            return await dry_run_change(
                self.sessions,
                self.project_id,
                subject=subject,
                quantity=quantity,
                change=change,
                base=facts,
            )
        ladder = LadderContext(
            config=self.config,
            graph=graph,
            providers=self.providers,
            available=self.available,
            style=facts.style,
            asked=frozenset((subject.id, name) for name in asked_names(subject.attrs, quantity)),
        )
        asked = SimQuestion(subject_id=subject.id, quantity=quantity, facts=subject.attrs)
        chosen = dataclasses.replace(ladder, style=(*facts.style, *_choice(quantity, provider)))
        proposal = propose_for(asked, trigger="user", context=chosen)
        if proposal is None:
            return {"decision": "none", "reason": f"no provider computes {quantity}"}
        outcome = await self._act(proposal, subject, ladder)
        if provider is not None and outcome["decision"] in ("ran", "queued"):
            own = propose_for(asked, trigger="user", context=ladder)
            if own is None or own.target != provider:
                outcome["remembered_as"] = await self._remember(quantity, str(provider))
        return outcome

    async def _read(
        self, subject_id: uuid.UUID, scope: list[uuid.UUID]
    ) -> tuple[GraphContext, EntityRead, FactStore]:
        """The graph around the subject under the bound read scope, the subject in it, and the
        facts the matrix reads over it. A subject this project does not hold is not found."""
        async with self.sessions() as session:
            hood = await load_neighborhood(
                session, self.project_id, roots=[subject_id, *scope], depth=SCOPE_DEPTH
            )
            graph = to_graph_context(hood)
            subject = next((e for e in graph.entities if e.id == subject_id), None)
            if subject is None:
                raise APIError(404, "not_found", "Subject not found")
            facts = await build_fact_store(session, self.project_id, graph)
        return graph, subject, facts

    async def _act(
        self, proposal: SimProposal, subject: EntityRead, ladder: LadderContext
    ) -> dict[str, Any]:
        if proposal.decision == "ask":
            await self._record_asked(subject.id, proposal.quantity, proposal.missing)
            return {
                "decision": "ask",
                **_proposal_view(proposal),
                "next": "ask the person for these inputs: this question is not asked again",
            }
        if proposal.decision == "missing_input":
            return {
                "decision": "missing_input",
                **_proposal_view(proposal),
                "finding_id": await self._raise_missing(proposal, subject),
            }
        if proposal.rung == 1:
            return await self._run(self.local[proposal.target], proposal, subject, ladder)
        if proposal.rung == 3:
            return await self._enqueue(self.local[proposal.target], proposal, subject)
        return self._route(proposal)

    def _route(self, proposal: SimProposal) -> dict[str, Any]:
        """Rungs 2 and 4: the target's gated routine, named and never invoked. In this turn its
        call keeps its card even where Build would run it on its own (M1): the person asked to
        simulate, not to run a routine."""
        route = self.external.route(proposal.target)
        if route is not None:
            note_routed(route["tool"])
        return {"decision": "route", **_proposal_view(proposal), "route": route}

    async def _run(
        self, provider: _Runs, proposal: SimProposal, subject: EntityRead, ladder: LadderContext
    ) -> dict[str, Any]:
        """Rung 1, in process: closed-form code, milliseconds, no I/O; then recorded."""
        try:
            result = provider.run(provider.inputs_for(subject.attrs))
        except ValidationError:
            raise
        except ValueError as exc:  # the closed form's own "nothing to compute"
            raise ToolException(str(exc)[:200], code=ToolErrorCode.TOOL_ERROR) from None
        sim_id = await record_sim_result(
            self.sessions,
            self.hub,
            project_id=self.project_id,
            subject_id=subject.id,
            rung=provider.rung,
            result=result,
            created_by=self.user_id,
        )
        if is_failing(result):  # R112: the one result a change in this turn may answer
            note_failing(subject.id, proposal.quantity, sim_id)
        return {
            "decision": "ran",
            **_proposal_view(proposal),
            "sim_result_id": str(sim_id),
            "values": {name: value.model_dump() for name, value in result.values.items()},
            "inputs": {name: item.source for name, item in result.provenance.inputs.items()},
            "leaves_out": list(result.provenance.leaves_out),
            **await self._judged(result, proposal, subject, ladder),
        }

    async def _judged(
        self, result: SimResult, proposal: SimProposal, subject: EntityRead, ladder: LadderContext
    ) -> dict[str, Any]:
        """Whether the rung-1 value stops, climbs or fails (R112), by the ladder's own band."""
        quantity, rung = proposal.quantity, proposal.rung
        stated = _self_limited(result, quantity)
        if stated is None:
            judged: dict[str, Any] = {
                "verdict": "no_limit",
                "reason": (
                    f"rung {rung} states no limit for {quantity}: nothing says how close it is"
                ),
            }
        else:
            value, limit = stated
            check = RuleResult(
                status="inconclusive",
                message=f"{quantity} at rung {rung}",
                subjects=(subject.id,),
                evidence={"quantity": quantity, "value": value, "limit": limit, "rung": rung},
            )
            climbs = should_simulate([check], trigger="user", context=ladder)
            judged = (
                {
                    "verdict": "climbs",
                    "reason": climbs[0].reason,
                    "climb": await self._climb(climbs[0], subject),
                }
                if climbs
                else {
                    "verdict": "stops",
                    "reason": (
                        f"{quantity} is at {value / limit:.0%} of its limit at rung {rung}: with "
                        "margin, the ladder stops here"
                    ),
                }
            )
        if is_failing(result):
            judged = {**judged, "verdict": "fails", "backward_loop": _owning_loop(subject)}
        return judged

    async def _climb(self, proposal: SimProposal, subject: EntityRead) -> dict[str, Any]:
        """The rung the ladder climbs to: enqueued or routed when it can run, else only said."""
        if proposal.decision != "run":
            return {"decision": proposal.decision, **_proposal_view(proposal)}
        if proposal.rung == 3:
            return await self._enqueue(self.local[proposal.target], proposal, subject)
        return self._route(proposal)

    async def _enqueue(
        self, provider: _Runs, proposal: SimProposal, subject: EntityRead
    ) -> dict[str, Any]:
        """Rung 3: its bounded job, which records its own run. Never inline."""
        job = RUNG_3_JOBS.get(provider.name)
        if job is None or self.enqueue_sim is None:
            return {"decision": "not_available", **_proposal_view(proposal), "reason": NO_QUEUE}
        facts = {name: item.value for name, item in provider.inputs_for(subject.attrs).items()}
        try:
            request = SimJobRequest(
                project_id=self.project_id,
                subject_id=subject.id,
                requested_by=self.user_id,
                facts=facts,
            )
        except ValidationError:
            raise ToolException(
                "the subject's facts exceed what one simulation job may carry",
                code=ToolErrorCode.INVALID_ARGS,
            ) from None
        try:
            job_id = await self.enqueue_sim(
                job, str(self.project_id), request.model_dump(mode="json")
            )
        except Exception:  # another system: after rung 1 ran, its failure is this line (M4)
            logger.warning(
                "sim job not queued project=%s job=%s", self.project_id, job, exc_info=True
            )
            return {
                "decision": "not_available",
                **_proposal_view(proposal),
                "reason": "the job queue did not take the job: rung 3 has not run",
            }
        return {
            "decision": "queued",
            **_proposal_view(proposal),
            "job_id": job_id,
            "next": "the job records its own result: read it with get_sim_result once it lands",
        }

    async def _record_asked(
        self, subject_id: uuid.UUID, quantity: str, missing: tuple[Any, ...]
    ) -> None:
        """Note on the subject that the person was asked (`attrs.sim_asked[quantity]`), reassigned
        under the project lock. A subject another writer holds is not waited for: the next
        question then asks again."""
        names = {need.name for need in missing}
        async with self.sessions() as session:
            await lock_project(session, self.project_id)
            row = await session.scalar(
                select(GraphEntity)
                .where(
                    GraphEntity.id == subject_id,
                    GraphEntity.project_id == self.project_id,
                    GraphEntity.deleted_at.is_(None),
                )
                .with_for_update(skip_locked=True)
            )
            if row is None:
                logger.info("ask not recorded project=%s subject=%s", self.project_id, subject_id)
                return
            held = row.attrs.get("sim_asked")
            asked = dict(held) if isinstance(held, Mapping) else {}
            before = set(asked_names(row.attrs, quantity))
            row.attrs = {**row.attrs, "sim_asked": {**asked, quantity: sorted(before | names)}}
            row.version += 1
            await session.commit()

    async def _raise_missing(self, proposal: SimProposal, subject: EntityRead) -> str:
        async with self.sessions() as session:
            finding = await raise_finding(
                session, self.project_id, missing_input_finding(proposal, subject)
            )
            await session.commit()
            return str(finding.id)

    async def _remember(self, quantity: str, provider: str) -> str | None:
        """The person's choice of provider as a `constraints/style` entry, best effort: the run
        has already happened, so a full section is logged rather than failing it."""
        line = STYLE_LINE.format(quantity=quantity, target=provider)
        try:
            async with self.sessions() as session:
                await add_text_entry(
                    session,
                    self.project_id,
                    SolusSection.CONSTRAINTS,
                    line,
                    author="sol",
                    created_by=self.user_id,
                    subsection="style",
                )
                await session.commit()
        except APIError as exc:
            logger.warning("style not remembered project=%s: %s", self.project_id, exc.code)
            return None
        return line


def _choice(quantity: str, provider: object) -> tuple[StyleEntry, ...]:
    """A person's `provider` for this run, as the newest style entry the ladder reads."""
    if not isinstance(provider, str):
        return ()
    return (StyleEntry(_OVERRIDE, STYLE_LINE.format(quantity=quantity, target=provider), None),)


def _simulate_params(quantities: list[str], providers: list[str]) -> dict[str, Any]:
    change, definitions = change_schema()
    return {
        "type": "object",
        "properties": {
            "question": {
                "type": "object",
                "properties": {
                    "subject_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "The entity to simulate: a part, a board, a scene model.",
                    },
                    "quantity": {
                        "type": "string",
                        "enum": quantities,
                        "description": "What to compute; the name carries its unit.",
                    },
                },
                "required": ["subject_id", "quantity"],
                "additionalProperties": False,
            },
            "scope": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "maxItems": MAX_SCOPE,
                "description": "Entities whose facts bear on the question besides the subject.",
            },
            "provider": {
                "type": "string",
                "enum": providers,
                "description": (
                    "Only when the person names one: the provider to use for this run, which "
                    "is then remembered as their preference."
                ),
            },
            "change": {
                **change,
                "description": (
                    "Your proposed fix for a failing result, in the domain that owns it: dry-run "
                    "here and returned, never applied."
                ),
            },
        },
        "required": ["question"],
        "additionalProperties": False,
        "$defs": definitions,
    }


async def get_sim_result_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    sim_id = uuid_arg(args, "sim_result_id")
    async with sessions() as session:
        row = await session.scalar(
            select(GraphEntity).where(
                GraphEntity.id == sim_id,
                GraphEntity.project_id == project_id,
                GraphEntity.kind == kinds.SIM_RESULT,
                GraphEntity.deleted_at.is_(None),
                current_scope(project_id).entity_predicate(),
            )
        )
    if row is None:  # absent, another kind, deleted or another project's: one answer
        raise APIError(404, "not_found", "Simulation result not found")
    return _result_rows(row)


def _held(value: object) -> Mapping[str, Any]:
    """A stored attr as the mapping it should be; anything else holds nothing."""
    return value if isinstance(value, Mapping) else {}


def _result_rows(row: GraphEntity) -> list[Mapping[str, Any]]:
    """One row of what the result is about, then its values, what it leaves out, and its inputs
    with their sources: the inputs last, since a trajectory's are the long ones."""
    attrs = row.attrs
    provenance, values = _held(attrs.get("provenance")), _held(attrs.get("values"))
    inputs, leaves_out = _held(provenance.get("inputs")), provenance.get("leaves_out")
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "subject_id": attrs.get("subject_id"),
            "rung": attrs.get("rung"),
            "solver": provenance.get("solver"),
            "created_at": row.created_at,
        },
        *(
            {"quantity": name, "value": item.get("value"), "unit": item.get("unit")}
            for name, item in values.items()
            if isinstance(item, Mapping)
        ),
        *(
            {"leaves_out": line}
            for line in (leaves_out if isinstance(leaves_out, list) else [])
            if isinstance(line, str)
        ),
        *(
            {"input": name, "source": item.get("source"), "value": item.get("value")}
            for name, item in inputs.items()
            if isinstance(item, Mapping)
        ),
    ]


#: The most proposed-simulation rows one card carries (R99), within the room its own rows leave,
#: and how long the pre-check may take inside the preview's own bound, so a slow one costs the
#: card its advice, never its preview.
MAX_PRECHECK_ROWS: Final = 8
PRECHECK_TIMEOUT_SECONDS: Final = 3.0
#: What an action touches: its entities, or a read of them on the pre-check's session.
type Touched = Collection[uuid.UUID] | Callable[[AsyncSession], Awaitable[Collection[uuid.UUID]]]


async def precheck_rows(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    touched: Touched,
    *,
    room: int,
) -> list[dict[str, Any]]:
    """The pre-check a gated real-world action's preview makes (R99): the matrix judged over the
    touched entities' neighbourhood under the person's own read scope, and one card row per
    simulation the ladder proposes for their `inconclusive` results
    (`precheck_real_world_action`), at most `room` (what the card's row bound leaves) and
    `MAX_PRECHECK_ROWS`, each line within the card's value cap. It reads only, on its own
    connection to `session`'s database: a read cut short invalidates its connection, and the
    caller's may be an approval's, holding the card's row lock. One that fails or outlasts
    `PRECHECK_TIMEOUT_SECONDS` is logged and adds no row, so the card keeps its other rows; the
    gate leaves these rows out of its staleness check (R118). The preview's own cancellation
    still propagates."""
    limit = min(MAX_PRECHECK_ROWS, room)
    if limit <= 0:
        return []
    try:
        async with asyncio.timeout(PRECHECK_TIMEOUT_SECONDS), AsyncSession(session.bind) as own:
            with bind_scope(await resolve_scope(own, project_id, user_id)):
                roots = set(await touched(own) if callable(touched) else touched)
                hood = await load_neighborhood(own, project_id, roots=list(roots), depth=1)
                graph = to_graph_context(hood)
                facts = await build_fact_store(own, project_id, graph)
        report = judge_matrix(graph, facts)
        results = [result for found in report.results.values() for result in found]
        queued = jobs_queued(session.info.get(SESSION_SETTINGS_KEY))
        context = ladder_context(graph, facts, queued=queued)
        proposals = precheck_real_world_action(results, roots, context=context)
    except Exception:  # advisory: a failed pre-check never refuses the action's card
        logger.warning("simulation pre-check skipped project=%s", project_id, exc_info=True)
        return []
    if len(proposals) > limit:
        logger.info(
            "simulation pre-check shows %d of %d proposals project=%s",
            limit,
            len(proposals),
            project_id,
        )
    names = {entity.id: entity.name for entity in graph.entities}
    return [
        {
            "label": PRECHECK_LABEL,
            "before": None,
            "after": proposal_line(proposal, names[proposal.subject_id])[:_VALUE_CAP],
        }
        for proposal in proposals[:limit]
    ]


def register_simulation_tools(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    hub: LiveHub | None,
    enqueue_sim: SimEnqueue | None,
) -> None:
    """Add `get_sim_result`, a read, and, with the app's hub (every recorded run publishes
    through it, M69), `simulate` and the gated `apply_sim_change`. Which external targets are
    connected is read off the gated tools registered before these: the bridge's."""
    registry.register(
        bounded_read_tool(
            GET_SIM_RESULT,
            "Read one simulation result in this project by id: the subject it verifies, its rung "
            "and solver, its values with units, what it leaves out, and each input with whether "
            "it was known, derived or assumed.",
            uuid_params("sim_result_id", "The sim_result's UUID."),
            partial(get_sim_result_handler, sessions=sessions, project_id=project_id),
        )
    )
    if hub is None:
        return
    config = shipped_simulation()  # the fact store's own read: one cache of the bands
    gated = frozenset(d.name for d in registry.list() if d.requires_confirmation)
    tools = SimulationTools(
        sessions,
        project_id,
        user_id=user_id,
        hub=hub,
        enqueue_sim=enqueue_sim,
        external=ExternalProviders.of(config, gated=gated),
        config=config,
    )
    registry.register(InProcessTool(tools.descriptor(), tools.simulate))
    register_apply_sim_change_tool(registry, sessions, project_id, user_id=user_id, hub=hub)
