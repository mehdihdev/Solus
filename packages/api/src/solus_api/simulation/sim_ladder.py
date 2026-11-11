"""SOLUSDEV-321 P4-T1 — the simulation ladder (docs/api/simulation.md §2): when a simulation would
settle something, which rung and target to use, and whether it can run. It is the spec's
`router.py`; the stem differs because a `router` stem pairs with a vendored test under H9.

It only PROPOSES. A provider is asked `can_answer`, never `run`; nothing is written and no model is
called. A sync or a save is never a trigger: `SimTrigger` holds the four triggers there are, and
any other value raises.

**When.**
- `rule` and `real_world_action` read an `inconclusive` result that is inside its band. Its
  evidence must state a `quantity`, a `value` and a `limit`, and may state a `comparator`, the
  `rung` the value came from and a `unit`.
- `expected_value` reads an `unknown_input` whose missing fact is a quantity some provider
  computes.
- `user` reads both.

Any other result proposes nothing: empty beats invented.

**Cheap first.** A question's candidates are the providers that compute its quantity at a rung
above the one its value came from. They are ranked in where-order (below): when no style entry
prefers one and availability does not separate them, the cheapest goes first, which by default
is the lowest rung. A value with margin proposes nothing, so the ladder stops where it is.

**Whether.** The chosen provider's `can_answer` decides, for the asked quantity:
- nothing missing → run;
- only what it can derive → derive;
- an input nobody was asked for yet → ask for it, once (`asked` names what was asked);
- the asked quantity it still covers without the rest → run, with the rest stated in
  `leaves_out`. Covering only other quantities is not covering the question;
- otherwise → `missing_input`, which `missing_input_finding` words as the finding the caller
  raises.

**Where.** Candidates are ordered by:
1. a `constraints/style` entry `simulate <quantity> with <target>` (`*` for any quantity; the
   newest wins);
2. connected and configured (`available`, which the caller computes);
3. cost;
4. fidelity;
5. name.

Cost and fidelity are a target's ordinals in `simulation.targets`, else its rung. A proposal
carries the line a confirmed override is remembered as (`remember_as`).

**The matrix and the gated actions (P4-T5).** `LOCAL_PROVIDERS` are the providers Solus runs.
`ladder_context(graph, facts, queued=)` is the ladder a matrix run asks about its `inconclusive`
results (`rule`), and the one a gated real-world action's pre-check asks about the results whose
subject it touches (`precheck_real_world_action`, `real_world_action`). `proposal_line` words a
proposal for that action's card. None of them runs anything. Which providers can run now
(`available_targets`) and what a person was asked per quantity (`asked_names`) are read one way
here and in `simulate`, so a card never proposes a run `simulate` would call unavailable; `climbs`
says whether any rung above a value's computes its quantity.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Literal, NamedTuple, Self, TypeGuard
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec
from solus_api.livebench.findings.rules.rule_base import FactNeed, shown
from solus_api.livebench.scene.part_bindings import finite_number
from solus_api.models import Domain
from solus_api.orchestration.config import SIM_NAME_PATTERN, SimName
from solus_api.simulation.providers.deterministic_elec import DeterministicElec
from solus_api.simulation.providers.deterministic_mech import DeterministicMech
from solus_api.simulation.providers.deterministic_robot import DeterministicRobot
from solus_api.simulation.providers.external_providers import ExternalProviders
from solus_api.simulation.providers.mesh_interference import MeshInterference
from solus_api.simulation.providers.mujoco_job import RigidBodyTrajectory
from solus_api.simulation.providers.ngspice_provider import NgspiceProvider
from solus_api.simulation.sim_capability import MissingInputs, SimQuestion

if TYPE_CHECKING:
    from solus_api.checkers.fact_store import FactStore, StyleEntry
    from solus_api.checkers.matrix_rule import RuleResult
    from solus_api.core.config import Settings
    from solus_api.orchestration.config import SimulationConfig
    from solus_api.simulation.sim_capability import SimProvider

type SimTrigger = Literal["rule", "expected_value", "user", "real_world_action"]
type SimDecision = Literal["run", "derive", "ask", "missing_input"]

#: The result statuses each trigger reads. An `inconclusive` is read only inside its band, and an
#: `unknown_input` only when a provider computes the quantity it lacks.
_READS: Final[Mapping[str, frozenset[str]]] = {
    "rule": frozenset({"inconclusive"}),
    "real_world_action": frozenset({"inconclusive"}),
    "expected_value": frozenset({"unknown_input"}),
    "user": frozenset({"inconclusive", "unknown_input"}),
}
#: Why a question asked straight (`propose_for`) is proposed, when its caller says nothing.
_WHY: Final[Mapping[str, str]] = {
    "rule": "a matrix rule could not settle it",
    "real_world_action": "a real-world action is about to run",
    "expected_value": "a change needs an expected value",
    "user": "the person asked for it",
}
#: The style line that states, and remembers, which target simulates a quantity.
STYLE_LINE: Final = "simulate {quantity} with {target}"
_STYLE: Final = re.compile(r"^\s*simulate\s+(\S+)\s+with\s+(\S+)\s*$", re.IGNORECASE)
ANY_QUANTITY: Final = "*"
_NAME: Final = re.compile(SIM_NAME_PATTERN)
#: The `rule_id` of the standing info a `missing_input` proposal words.
MISSING_INPUT_RULE: Final = "simulation_missing_input"


@dataclass(frozen=True, kw_only=True)
class LadderContext:
    """Everything the ladder decides with, all of it supplied by the caller:
    - the config's bands and targets;
    - the graph the results are about (the subjects' attrs and names);
    - the providers;
    - which providers are connected and configured;
    - the project's `constraints/style` entries (`FactStore.style`, oldest first);
    - the inputs a person was already asked for, as (subject, input) pairs."""

    config: SimulationConfig
    graph: GraphContext = field(default_factory=lambda: GraphContext(entities=[], edges=[]))
    providers: tuple[SimProvider, ...] = ()
    available: frozenset[str] = frozenset()
    style: tuple[StyleEntry, ...] = ()
    asked: frozenset[tuple[UUID, str]] = frozenset()


class SimProposal(BaseModel):
    """One simulation the ladder proposes. Nothing runs until a caller runs it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger: SimTrigger
    subject_id: UUID
    quantity: SimName
    rung: int
    target: str
    available: bool
    decision: SimDecision
    missing: tuple[FactNeed, ...] = ()
    leaves_out: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    reason: str
    remember_as: str

    @model_validator(mode="after")
    def _names_what_it_lacks(self) -> Self:
        if self.decision != "run" and not self.missing:
            raise ValueError(f"a {self.decision} proposal names the inputs it is about")
        return self


class _Asked(NamedTuple):
    """What one result asks of the ladder: its subject, the quantity, the rung its value came
    from, and why."""

    subject_id: UUID
    quantity: str
    above_rung: int
    reason: str


def should_simulate(
    results: list[RuleResult], *, trigger: SimTrigger, context: LadderContext
) -> list[SimProposal]:
    """The proposals that `trigger`'s results call for, at most one per (subject, quantity): the
    first result that asks wins. A result whose subject `context.graph` does not hold has no facts
    to ask with, so it proposes nothing. What the subject records a person was asked for that
    quantity (`asked_names`) counts as asked, beside `context.asked`."""
    reads = _reads(trigger)
    subjects = {entity.id: entity for entity in context.graph.entities}
    proposals: dict[tuple[UUID, str], SimProposal] = {}
    for result in results:
        asked = _asked(result, reads, context)
        subject = subjects.get(asked.subject_id) if asked is not None else None
        if asked is None or subject is None or (subject.id, asked.quantity) in proposals:
            continue
        question = SimQuestion(subject_id=subject.id, quantity=asked.quantity, facts=subject.attrs)
        record = {(subject.id, name) for name in asked_names(subject.attrs, asked.quantity)}
        proposal = propose_for(
            question,
            trigger=trigger,
            context=replace(context, asked=context.asked | record),
            above_rung=asked.above_rung,
            reason=asked.reason,
        )
        if proposal is not None:
            proposals[(subject.id, asked.quantity)] = proposal
    return list(proposals.values())


def propose_for(
    question: SimQuestion,
    *,
    trigger: SimTrigger,
    context: LadderContext,
    above_rung: int = 0,
    reason: str = "",
) -> SimProposal | None:
    """The proposal for one question: the first candidate above `above_rung` in where-order, and
    whether it can run. None when no provider computes the quantity up there. The person's own
    question and a change that needs a value arrive here directly; `should_simulate` maps each
    result onto it."""
    _reads(trigger)
    ranked = _ranked(question.quantity, above_rung, context)
    if not ranked:
        return None
    chosen = ranked[0]
    decision, missing, leaves_out = _whether(chosen.can_answer(question), question, context.asked)
    return SimProposal(
        trigger=trigger,
        subject_id=question.subject_id,
        quantity=question.quantity,
        rung=chosen.rung,
        target=chosen.name,
        available=chosen.name in context.available,
        decision=decision,
        missing=missing,
        leaves_out=leaves_out,
        alternatives=tuple(provider.name for provider in ranked[1:]),
        reason=reason or _WHY[trigger],
        remember_as=STYLE_LINE.format(quantity=question.quantity, target=chosen.name),
    )


def missing_input_finding(proposal: SimProposal, subject: EntityRead) -> FindingSpec:
    """A `missing_input` proposal worded as the standing `info` finding the caller raises through
    `raise_finding`. There is one per (subject, quantity), naming each missing input and where a
    person states it. Nothing is raised here and nothing runs."""
    if proposal.decision != "missing_input" or subject.id != proposal.subject_id:
        raise ValueError("a missing_input finding words a missing_input proposal about its subject")
    first = proposal.missing[0]
    return FindingSpec(
        rule_id=MISSING_INPUT_RULE,
        severity=Severity.INFO,
        source="simulation",
        headline=(
            f"could not simulate {proposal.quantity} for {subject.name}: {first.name} unknown; "
            f"set it in {first.set_in}"
        ),
        subjects=[subject.id],
        evidence={
            "missing": [need.model_dump() for need in proposal.missing],
            "quantity": proposal.quantity,
            "rung": proposal.rung,
            "target": proposal.target,
        },
        domain=Domain(subject.domain),
        bucket=proposal.quantity,
    )


def _reads(trigger: str) -> frozenset[str]:
    """The statuses `trigger` reads. Any other value, such as a sync or a save, is refused."""
    try:
        return _READS[trigger]
    except KeyError:
        raise ValueError(
            f"{trigger!r} is not a simulation trigger: a sync or a save never is"
        ) from None


def _asked(result: RuleResult, reads: frozenset[str], context: LadderContext) -> _Asked | None:
    """What `result` asks the ladder, when its trigger reads its status (module docstring)."""
    if result.status not in reads or not result.subjects:
        return None
    if result.status == "inconclusive":
        return _in_band(result, context.config)
    need = result.missing
    if need is None or not _named(need.name):
        return None
    if not any(need.name in provider.quantities for provider in context.providers):
        return None
    return _Asked(result.subjects[0], need.name, 0, f"{need.name} has no expected value yet")


def _in_band(result: RuleResult, config: SimulationConfig) -> _Asked | None:
    """The question an `inconclusive` result asks when its value is at or past its quantity's
    band of the limit. None when its evidence states no quantity, value and limit, or when the
    value has margin."""
    evidence = result.evidence
    quantity, rung = evidence.get("quantity"), evidence.get("rung", 0)
    value, limit = finite_number(evidence.get("value")), finite_number(evidence.get("limit"))
    if not _named(quantity) or value is None or not limit or type(rung) is not int:
        return None
    ratio = _ratio(value, limit, evidence.get("comparator", "<="))
    band = config.band(quantity)
    if ratio is None or ratio < band:
        return None
    reason = f"{quantity} is at {ratio:.0%} of its limit at rung {rung}: inside its {band:g} band"
    return _Asked(result.subjects[0], quantity, rung, reason)


def _ratio(value: float, limit: float, comparator: object) -> float | None:
    """How far toward its limit a value is: value / limit under a ceiling (`<=`), limit / value
    above a floor (`>=`). None for any other comparator, or for a zero value above a floor."""
    if comparator == "<=":
        return value / limit
    if comparator == ">=" and value:
        return limit / value
    return None


def _named(name: object) -> TypeGuard[str]:
    """A quantity name that a style line and a finding headline read back whole."""
    return isinstance(name, str) and _NAME.fullmatch(name) is not None


def _ranked(quantity: str, above_rung: int, context: LadderContext) -> list[SimProvider]:
    """The providers that compute `quantity` above `above_rung`, in where-order."""
    preferred = _style_target(quantity, context.style)
    found = [p for p in context.providers if quantity in p.quantities and p.rung > above_rung]
    return sorted(found, key=lambda provider: _order(provider, preferred, context))


def _order(
    provider: SimProvider, preferred: str | None, context: LadderContext
) -> tuple[bool, bool, float, float, str]:
    """Where-order: preferred by a style entry, then connected and configured, then cheaper, then
    more faithful, then by name, so the order is total."""
    cost, fidelity = _rank(provider, context.config)
    return (
        provider.name != preferred,
        provider.name not in context.available,
        cost,
        -fidelity,
        provider.name,
    )


def _rank(provider: SimProvider, config: SimulationConfig) -> tuple[float, float]:
    """A candidate's (cost, fidelity): its target's ordinals in the yaml, else its rung."""
    target = config.target(provider.name)
    cost = target.cost if target is not None else None
    fidelity = target.fidelity if target is not None else None
    return (
        provider.rung if cost is None else cost,
        provider.rung if fidelity is None else fidelity,
    )


def _style_target(quantity: str, style: tuple[StyleEntry, ...]) -> str | None:
    """The target the newest `simulate <quantity> with <target>` style entry names (`*` stands for
    any quantity). None when no entry states one."""
    for entry in reversed(style):
        match = _STYLE.match(entry.text)
        if match and match.group(1).lower() in (quantity, ANY_QUANTITY):
            return match.group(2).lower()
    return None


def _whether(
    lacks: MissingInputs, question: SimQuestion, asked: frozenset[tuple[UUID, str]]
) -> tuple[SimDecision, tuple[FactNeed, ...], tuple[str, ...]]:
    """The decision table (module docstring), for the question's own quantity: the decision, the
    inputs it is about, and the gap a covered run states. Covering only other quantities is not
    covering the question."""
    if not lacks.missing:
        return "run", (), ()
    needed = tuple(need for need in lacks.missing if need.name not in lacks.derivable)
    if not needed:
        return "derive", lacks.missing, ()
    unasked = tuple(need for need in needed if (question.subject_id, need.name) not in asked)
    if unasked:
        return "ask", unasked, ()
    if question.quantity in lacks.covered:
        return "run", needed, tuple(need.name for need in needed)
    return "missing_input", needed, ()


# ------------------------------------------ the matrix's ladder and a gated action's (P4-T5)

#: Every provider that runs in a Solus process: rung 1 in process, and rung 3 as its bounded job.
#: `simulate` runs them (P4-T4); a matrix run and a gated action's pre-check rank them beside the
#: yaml's external targets.
LOCAL_PROVIDERS: Final = (
    DeterministicMech(),
    DeterministicElec(),
    DeterministicRobot(),
    MeshInterference(),
    NgspiceProvider(None),
    RigidBodyTrajectory(),
)


def ladder_context(graph: GraphContext, facts: FactStore, *, queued: bool) -> LadderContext:
    """The ladder a matrix run asks about its `inconclusive` results, and a gated real-world
    action's pre-check about the ones it touches:

    - the store's bands and its `constraints/style` entries;
    - every provider the ladder ranks (`ladder_providers`), and which can run now as `simulate`
      reads it (`available_targets`): the rung-3 jobs as `queued` says (the deployment's job
      queue), and no external target, since no turn's registry holds their gated routine tools
      here;
    - the inputs a person was asked for are read off each subject per quantity, as `simulate`
      reads them (`should_simulate`)."""
    return LadderContext(
        config=facts.simulation,
        graph=graph,
        providers=ladder_providers(facts.simulation),
        available=available_targets(queued=queued),
        style=facts.style,
    )


def ladder_providers(config: SimulationConfig) -> tuple[SimProvider, ...]:
    """Every provider the ladder ranks: each one Solus runs, then the yaml's external targets."""
    return (*LOCAL_PROVIDERS, *ExternalProviders.of(config, registered=()).targets)


def available_targets(*, queued: bool, connected: Collection[str] = ()) -> frozenset[str]:
    """Which providers can run now, the one reading `simulate` and the ladder's other callers
    share (Minor 8): every rung-1 provider, in process; the rung-3 ones only with a job queue to
    take their bounded jobs; and the external targets whose gated routine tools are registered."""
    local = frozenset(p.name for p in LOCAL_PROVIDERS if p.rung == 1 or queued)
    return local | frozenset(connected)


def jobs_queued(settings: Settings | None) -> bool:
    """Whether a deployment queues simulation jobs: a Redis URL and not inline, as the registry's
    `enqueue_sim` is given (`deps.py`). No settings, no queue."""
    return settings is not None and bool(settings.redis_url) and not settings.sync_inline


def climbs(quantity: str, rung: int, config: SimulationConfig) -> bool:
    """Whether a provider the ladder ranks computes `quantity` above `rung`: whether a higher rung
    can settle a value inside its band."""
    return any(quantity in p.quantities and p.rung > rung for p in ladder_providers(config))


def asked_names(attrs: Mapping[str, Any], quantity: str) -> list[str]:
    """The inputs a person was already asked for `quantity` (`attrs.sim_asked[quantity]`, P4-T4):
    the one reading `simulate` and the ladder share."""
    held = attrs.get("sim_asked")
    listed = held.get(quantity) if isinstance(held, Mapping) else None
    return [name for name in listed if isinstance(name, str)] if isinstance(listed, list) else []


def precheck_real_world_action(
    results: Iterable[RuleResult], touched: Collection[UUID], *, context: LadderContext
) -> list[SimProposal]:
    """The pre-check before a gated real-world action (R99): what the ladder proposes for the
    matrix's `inconclusive` results whose subject the action touches. It only proposes: the caller
    shows each proposal on the action's card, and changes no gate."""
    about = [result for result in results if result.subjects and result.subjects[0] in touched]
    return should_simulate(about, trigger="real_world_action", context=context)


def proposal_line(proposal: SimProposal, subject: str) -> str:
    """One proposal as a gated action's card shows it (R99): whose quantity and why, and the run
    the ladder proposes first, with what it still needs, or why it cannot run now: no job queue
    for a run Solus does, or a target not connected."""
    line = (
        f"{shown(subject)}: {proposal.reason}. Simulate {proposal.quantity} at rung "
        f"{proposal.rung} with {proposal.target} first"
    )
    if proposal.decision in ("ask", "missing_input"):
        line += f"; it needs {', '.join(need.name for need in proposal.missing)}"
    if not proposal.available:
        local = any(provider.name == proposal.target for provider in LOCAL_PROVIDERS)
        line += "; no job queue runs it here" if local else "; that target is not connected"
    return line
