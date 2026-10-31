"""SOLUSDEV-321 P4-T4 (R91, R111, R112) — the simulation's backward loop: a change SOL proposes for
a failing result, dry-run, then applied behind a card (docs/api/simulation.md §8).

A result fails when a value reaches a limit the result itself states (`is_failing`:
`yield_fraction >= 1` today). A change answers only a failing result the same SOL turn holds for
that subject and quantity (`note_failing`, R112): without one, the dry run and the apply both say
"no failing result to fix". The subject's `attrs.owning_domain` names the domain that owns the
fix, else the destination side of the cell whose rule judges the failing value does (M141: the
bracket's yield, mechanical); with neither there is no loop. SOL proposes the change there as an
argument, and code decides the rest. The owner selects the ONE writer a change may go through
(`OWNER_WRITERS`), and the dry run, the preview and the handler all ask it through `writer_for`:

    owning_domain         change        writer
    runtime, electrical   config        put_entity_config (a field of the entity's v2 config)
    project               constraint    add_text_entry (a `.solus` constraints entry)
    any other owner       any           none: propose only
    any owner             another kind  none: propose only

1. **The dry run** (`dry_run_change`, which `simulate(change=…)` calls). The change is laid over a
   copy of the facts the matrix reads (`FactStore`), and the matrix judges the base and the copy,
   each with `run_matrix(facts=…, dry_run=True)`, which writes nothing. The verdicts that differ
   come back with what rung 1 predicts when the change is to an attr the subject's own rung-1
   provider reads, and with the writer the owner selects. Nothing is applied; a change with a
   writer is noted for the turn.
2. **The apply** (`apply_sim_change`). It is always gated (`requires_confirmation=True`) and never
   an owned routine, so no Build policy runs it without its card. Its preview shows the concrete
   change and admits only a change dry-run in the same turn, and only ONE apply per turn, claimed
   only once the card shows the change whole (M3). Its handler runs only after the person
   approves. It writes through the owner's writer, then re-runs rung 1 in process and records the
   result through `record_sim_result`. A re-run that fails after the write is its own line beside
   the applied change (M4).
3. **Propose only.** A change no writer of its owner makes (any change of a `code`, `mechanical` or
   `simulation` owner, an attr, a kind the owner does not write) comes back as text for the person,
   in the same words at every step: the dry run selects no writer, the preview parks nothing, and
   the handler refuses.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from sqlalchemy import select

from solus_api.agent.confirmations import _complete_preview
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.solus_tools import _leaf_value, _set_leaf
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.turn_context import current_turn_id
from solus_api.checkers.cells import fix_owner
from solus_api.checkers.fact_store import ExpectedValue, FactStore, StyleEntry
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig, FieldProvenance, HardwareConfig
from solus_api.hardware.store import hardware_entity, put_entity_config, read_entity_config
from solus_api.livebench.findings.rules.rule_base import shown
from solus_api.models import Domain, GraphEntity, SolusSection
from solus_api.orchestration.config import SimName
from solus_api.services.solus_config import add_text_entry
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.providers import ClosedForm
from solus_api.simulation.sim_capability import SimQuestion
from solus_api.simulation.sim_facts import record_sim_result
from solus_api.simulation.sim_ladder import LOCAL_PROVIDERS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.interfaces import EntityRead
    from solus_api.agent.tools.registry import ToolRegistry
    from solus_api.checkers.matrix_runner import MatrixReport
    from solus_api.graph.live import LiveHub
    from solus_api.simulation.sim_capability import SimResult, SimValue

logger = logging.getLogger("solus.agent.tools.apply_sim_change")

APPLY_SIM_CHANGE: Final = "apply_sim_change"
#: A config change sets one field of an entity's own v2 config, inside its `component` group.
CONFIG_PATH: Final = r"^component(\.[A-Za-z0-9_-]+){1,6}$"
#: The most of a change a card shows on one line, and of an attr value, as JSON.
MAX_SHOWN: Final = 480
MAX_VALUE_BYTES: Final = 4096
#: The most changed verdicts a dry run lists; the count says how many there were.
MAX_CHANGED: Final = 20
#: The most turns the ledger keeps (the oldest goes first), and config previews a tool keeps.
MAX_TURNS_TRACKED: Final = 1024
MAX_PREVIEWS: Final = 16
SOL_SOURCE: Final = "simulation backward loop"
#: The domains a fix can belong to (`attrs.owning_domain`).
OWNING_DOMAINS: Final = frozenset(d.value for d in Domain if d is not Domain.WORKSPACE)
#: The one value a result states its own limit for today (R112): the stress over its yield.
YIELD_FRACTION: Final = "yield_fraction"
#: The rung-1 providers: what a dry run predicts with and what the approved re-run runs. The
#: ladder's own roster's closed forms (Minor 8), never a second list.
RUNG_ONE: Final[tuple[ClosedForm, ...]] = tuple(
    provider
    for provider in LOCAL_PROVIDERS
    if isinstance(provider, ClosedForm) and provider.rung == 1
)
#: The style entry a dry run lays over the facts for a style change.
_DRY_RUN: Final = uuid.UUID(int=1)
_UNSET: Final = "(unset)"

type ConfigValue = (
    StrictBool | StrictInt | FiniteFloat | Annotated[StrictStr, Field(max_length=512)] | None
)
_Frozen: Final = ConfigDict(frozen=True, extra="forbid")


class ConfigChange(BaseModel):
    """One field of a part's or robot's own v2 config, written through `put_entity_config`."""

    model_config = _Frozen

    kind: Literal["config"]
    entity_id: uuid.UUID
    path: Annotated[str, StringConstraints(pattern=CONFIG_PATH, max_length=256)]
    value: ConfigValue


class ConstraintChange(BaseModel):
    """One line in the project's `.solus` constraints, written through `add_text_entry`. The
    `budgets` subsection is a config document with its own route, so it is not one of them."""

    model_config = _Frozen

    kind: Literal["constraint"]
    subsection: Literal["rules", "compliance", "style"]
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SHOWN)
    ]


class AttrChange(BaseModel):
    """An entity's attr. No Solus writer changes one, so it is proposed, never applied."""

    model_config = _Frozen

    kind: Literal["attr"]
    entity_id: uuid.UUID
    attr: SimName
    value: JsonValue

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(json.dumps(self.value)) > MAX_VALUE_BYTES:
            raise ValueError(f"an attr change's value exceeds {MAX_VALUE_BYTES} bytes as JSON")
        return self


SimChange = Annotated[ConfigChange | ConstraintChange | AttrChange, Field(discriminator="kind")]
_CHANGE: Final[TypeAdapter[ConfigChange | ConstraintChange | AttrChange]] = TypeAdapter(SimChange)


class ApplyArgs(BaseModel):
    """What `apply_sim_change` takes: the simulation the change answers, and the change."""

    model_config = _Frozen

    subject_id: uuid.UUID
    quantity: SimName
    change: SimChange

    def key(self) -> str:
        """The change as one canonical line: what a dry run notes and an apply claims."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def change_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    """The change's JSON schema and the definitions it refers to, which belong at the root of a
    tool's params."""
    schema = _CHANGE.json_schema()
    return {key: value for key, value in schema.items() if key != "$defs"}, schema.get("$defs", {})


def parse_change(raw: object) -> SimChange:
    try:
        return _CHANGE.validate_python(raw)
    except ValidationError:
        raise ToolException(
            "the change is not one Solus can describe", code=ToolErrorCode.INVALID_ARGS
        ) from None


def is_failing(result: SimResult) -> bool:
    """A value at or past a limit the result states itself (R112)."""
    fraction = result.values.get(YIELD_FRACTION)
    return fraction is not None and fraction.value >= 1.0


def owning_domain(attrs: Mapping[str, Any]) -> str | None:
    """The domain that owns a failing subject's fix: `attrs.owning_domain`, else the destination
    side of the cell whose rule judges the failing value (M141, `fix_owner`), else None. A stated
    value that names no owning domain is logged and read as absent (Minor 6)."""
    owner = attrs.get("owning_domain")
    if isinstance(owner, str) and owner in OWNING_DOMAINS:
        return owner
    if owner is not None:
        logger.warning("owning_domain %.80r names no owning domain: read as absent", owner)
    return fix_owner(YIELD_FRACTION)


def rung_one_for(quantity: str) -> ClosedForm | None:
    return next((provider for provider in RUNG_ONE if quantity in provider.quantities), None)


#: The ONE writer each owning domain's fix goes through, by the change it writes (R111). Any other
#: owner (`code`, `mechanical` definitions, `simulation`), or another change, selects none.
OWNER_WRITERS: Final[Mapping[str, tuple[str, str]]] = {
    Domain.RUNTIME.value: ("config", "put_entity_config"),
    Domain.ELECTRICAL.value: ("config", "put_entity_config"),
    Domain.PROJECT.value: ("constraint", "add_text_entry"),
}


def writer_for(owner: str, change: SimChange) -> str | None:
    """The writer `owner`'s fix goes through when `change` is the kind it writes; None makes the
    change propose-only. The dry run, the preview and the handler all ask this one table."""
    kind, writer = OWNER_WRITERS.get(owner, (None, None))
    return writer if change.kind == kind else None


def _propose_only(owner: str, text: str) -> str:
    """What every step says of a change no writer of `owner` makes: the same words."""
    return (
        f"Propose only: {text}. The {owner} domain has no Solus writer for this change; tell the "
        "person where to make it"
    )


# --------------------------------------------------------------- the turn's ledger (R91)


#: What the loop says to a change that answers no failing result the turn holds (R112).
NO_FAILING: Final = "no failing result to fix"


@dataclass
class _TurnLedger:
    #: The turn's failing rung-1 results by (subject, quantity): the only ones a change answers.
    failing: dict[tuple[uuid.UUID, str], uuid.UUID] = field(default_factory=dict)
    dry_runs: set[str] = field(default_factory=set)
    applied: str | None = None
    #: The routine tools `simulate` routed the turn to: their calls keep their card (M1).
    routed: set[str] = field(default_factory=set)


#: Per SOL turn (`agent/turn_context.py`): the failing results, the changes dry-run, the one
#: change carded, and the routines routed to.
_LEDGER: Final[OrderedDict[uuid.UUID, _TurnLedger]] = OrderedDict()


def _this_turn() -> _TurnLedger | None:
    """The running turn's ledger, when it has one; reading never adds one."""
    turn = current_turn_id()
    return _LEDGER.get(turn) if turn is not None else None


def _ledger(turn: uuid.UUID) -> _TurnLedger:
    entry = _LEDGER.get(turn)
    if entry is None:
        entry = _LEDGER[turn] = _TurnLedger()
        while len(_LEDGER) > MAX_TURNS_TRACKED:
            _LEDGER.popitem(last=False)
    return entry


def note_failing(subject_id: uuid.UUID, quantity: str, sim_result_id: uuid.UUID) -> None:
    """A failing rung-1 result in the turn that runs; outside a turn nothing is noted."""
    turn = current_turn_id()
    if turn is not None:
        _ledger(turn).failing[(subject_id, quantity)] = sim_result_id


def failing_result(subject_id: uuid.UUID, quantity: str) -> uuid.UUID | None:
    """The failing result the running turn holds for the subject and quantity, or None."""
    held = _this_turn()
    return held.failing.get((subject_id, quantity)) if held is not None else None


def note_routed(tool: str) -> None:
    """`simulate` routed the turn that runs to `tool`, a target's routine (M1)."""
    turn = current_turn_id()
    if turn is not None:
        _ledger(turn).routed.add(tool)


def routed_by_simulation(tool: str) -> bool:
    """Whether `simulate` routed the running turn to `tool`. Such a call keeps its card even where
    Build would run it on its own: the person asked to simulate, not to run a routine."""
    held = _this_turn()
    return held is not None and tool in held.routed


def note_dry_run(key: str) -> None:
    """A dry run of `key` in the turn that runs; outside a turn nothing is noted."""
    turn = current_turn_id()
    if turn is not None:
        _ledger(turn).dry_runs.add(key)


def _claim_apply(args: ApplyArgs) -> None:
    """Admit one complete card for the turn (M3): a change answering a failing result the turn
    holds, dry-run in it, with nothing carded before. The approval re-builds the card outside any
    turn, and that card was admitted when it was parked."""
    turn = current_turn_id()
    if turn is None:
        return
    ledger, key = _ledger(turn), args.key()
    if (args.subject_id, args.quantity) not in ledger.failing:
        raise PreviewRefusal(
            f"{NO_FAILING.capitalize()} in this turn: simulate {args.quantity} first. "
            "Nothing was parked."
        )
    if key not in ledger.dry_runs:
        raise PreviewRefusal(
            "Dry-run this change with simulate in this turn first. Nothing was parked."
        )
    if ledger.applied is not None:
        raise PreviewRefusal(
            "One simulation change per turn is already waiting for the person's approval. "
            "Nothing was parked."
        )
    ledger.applied = key


# --------------------------------------------------------------------------- the dry run


def describe_change(change: SimChange, name: str | None = None) -> str:
    """The change in the words a person reads, its entity named."""
    label = shown(name) if name else "the entity"
    if isinstance(change, ConstraintChange):
        return f"add to the project's constraints/{change.subsection}: {change.text}"
    value = json.dumps(change.value)[:MAX_SHOWN]
    if isinstance(change, ConfigChange):
        return f"set {change.path} of {label} to {value}"
    return f"set {change.attr} of {label} to {value}, where that attr is kept"


async def _target_name(
    session: AsyncSession, project_id: uuid.UUID, change: SimChange
) -> str | None:
    """The changed entity's name; a config change's entity must hold a v2 config. Another
    project's entity, or none, is not found."""
    if isinstance(change, ConstraintChange):
        return None
    if isinstance(change, ConfigChange):
        entity = await hardware_entity(session, project_id, change.entity_id)
        entry, config = await read_entity_config(session, project_id, entity.id)
        if entry is None or config is None:
            raise APIError(404, "not_found", "Hardware config not found")
        return entity.name
    row = await _live_subject(session, project_id, change.entity_id)
    if row is None:
        raise APIError(404, "not_found", "Entity not found")
    return row.name


def _with_prediction(
    base: FactStore, subject: EntityRead, quantity: str, facts: Mapping[str, Any]
) -> tuple[FactStore, dict[str, SimValue] | None]:
    """The facts with what rung 1 now expects of the subject, when its rung-1 provider runs on the
    changed attrs; the facts unchanged otherwise."""
    provider = rung_one_for(quantity)
    if provider is None:
        return base, None
    try:
        result = provider.run(provider.inputs_for(facts))
    except ValueError:  # the changed attrs leave it nothing to compute
        return base, None
    expected = {q: ExpectedValue(v.value, v.unit, None) for q, v in result.values.items()}
    held = dict(base.expected_values)
    held[subject.id] = {**held.get(subject.id, {}), **expected}
    return replace(base, expected_values=held), dict(result.values)


def _configs_with(
    configs: Mapping[uuid.UUID, HardwareConfig], change: ConfigChange
) -> dict[uuid.UUID, HardwareConfig]:
    """Each robot's resolved config with a part's changed field: its `component` is the part's
    slot there (`parts.<id>`)."""
    updated = dict(configs)
    path = f"parts.{change.entity_id}.{change.path.removeprefix('component.')}"
    for robot, config in configs.items():
        if str(change.entity_id) not in config.parts:
            continue
        document = config.model_dump(mode="json")
        _set_leaf(document, path, change.value)
        document["provenance"][path] = {"by": FieldProvenance.SOL.value, "source": SOL_SOURCE}
        try:
            updated[robot] = HardwareConfig.model_validate(document)
        except ValidationError:
            raise ToolException(
                "the change does not make a valid configuration", code=ToolErrorCode.INVALID_ARGS
            ) from None
    return updated


def _overridden(
    base: FactStore, change: SimChange, subject: EntityRead, quantity: str
) -> tuple[FactStore, dict[str, SimValue] | None]:
    """The facts as they would be after the change. A rules or compliance line states no fact the
    matrix reads, so it leaves them as they are."""
    if isinstance(change, AttrChange):
        if change.entity_id != subject.id:
            return base, None
        return _with_prediction(
            base, subject, quantity, {**subject.attrs, change.attr: change.value}
        )
    if isinstance(change, ConfigChange):
        return replace(base, runtime_configs=_configs_with(base.runtime_configs, change)), None
    if change.subsection == "style":
        return replace(base, style=(*base.style, StyleEntry(_DRY_RUN, change.text, None))), None
    return base, None


def _verdict_keys(report: MatrixReport) -> dict[tuple[str, tuple[str, ...], str], str]:
    return {
        (rule, tuple(str(s) for s in result.subjects), str(result.edge_ref)): result.status
        for rule, results in report.results.items()
        for result in results
    }


def _changed_verdicts(before: MatrixReport, after: MatrixReport) -> dict[str, Any]:
    old, new = _verdict_keys(before), _verdict_keys(after)
    changed = [
        {"rule": key[0], "subjects": list(key[1]), "before": old.get(key), "after": new.get(key)}
        for key in sorted(set(old) | set(new))
        if old.get(key) != new.get(key)
    ]
    return {
        "changed": changed[:MAX_CHANGED],
        "changed_count": len(changed),
        "truncated": after.truncated,
    }


async def dry_run_change(
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    subject: EntityRead,
    quantity: str,
    change: SimChange,
    base: FactStore,
) -> dict[str, Any]:
    """The change laid over the facts and judged by the matrix twice, writing nothing (the module
    docstring). Only a failing result the running turn holds for the subject and quantity has a
    fix to dry-run (R112), and there is no loop without the subject's owning domain."""
    failing = failing_result(subject.id, quantity)
    if failing is None:
        return {
            "decision": "no_failing_result",
            "next": (
                f"{NO_FAILING}: simulate {quantity} of {shown(subject.name)} in this turn first; "
                "only a failing result's fix is dry-run"
            ),
        }
    owner = owning_domain(subject.attrs)
    if owner is None:
        return {
            "decision": "no_loop",
            "next": (
                f"set attrs.owning_domain on {shown(subject.name)} to the domain that owns the "
                "fix: no change is dry-run or applied without it"
            ),
        }
    async with sessions() as session:
        text = describe_change(change, await _target_name(session, project_id, change))
        override, predicted = _overridden(base, change, subject, quantity)
        before = await run_matrix(session, project_id, facts=base, dry_run=True)
        after = await run_matrix(session, project_id, facts=override, dry_run=True)
    args = ApplyArgs(subject_id=subject.id, quantity=quantity, change=change)
    writer = writer_for(owner, change)
    if writer is not None:
        note_dry_run(args.key())
    return {
        "decision": "dry_run",
        "owning_domain": owner,
        "failing_result_id": str(failing),
        "change": change.model_dump(mode="json"),
        "change_text": text,
        "writer": writer,
        "appliable": writer is not None,
        "predicted": {q: v.model_dump() for q, v in predicted.items()} if predicted else None,
        "matrix": _changed_verdicts(before, after),
        "apply": {"tool": APPLY_SIM_CHANGE, "args": args.model_dump(mode="json")}
        if writer is not None
        else None,
        "next": (
            "call apply_sim_change with these args: the person sees the change and it is "
            "applied only if they approve"
            if writer is not None
            else _propose_only(owner, text)
        ),
    }


# ------------------------------------------------------------------------------ the apply


async def _live_subject(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == entity_id,
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
        )
    )
    return row


def _apply_args(args: Mapping[str, Any]) -> ApplyArgs:
    try:
        return ApplyArgs.model_validate(dict(args))
    except ValidationError:
        raise ToolException(
            "the change is not one Solus can apply", code=ToolErrorCode.INVALID_ARGS
        ) from None


def _shown_value(value: Any) -> str:
    return (value if isinstance(value, str) else json.dumps(value))[:MAX_SHOWN]


class SimChangeTool:
    """`apply_sim_change`, bound to ONE project and person: the card's preview and the handler the
    approval runs (the module docstring). Never an owned routine: Build mode parks its card, and
    Guide mode refuses it before any card (`build_mode_dispatch`)."""

    #: A preview that cannot be built refuses the park, never falls back to argument rows.
    requires_complete_preview = True

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        hub: LiveHub,
    ) -> None:
        self.sessions, self.project_id, self.user_id, self.hub = sessions, project_id, user_id, hub
        #: A config preview's (entry, version), so the approved write lands on what was shown.
        self._revisions: dict[str, tuple[uuid.UUID, int]] = {}
        self._descriptor = ToolDescriptor(
            name=APPLY_SIM_CHANGE,
            description=(
                "Apply ONE change that simulate dry-ran in this turn, in the domain that owns a "
                "failing simulation's fix: a config field of a part or robot, or a line in the "
                "project's constraints. The person sees the change and approves it first; then "
                "rung 1 re-runs and is recorded. One per turn. An attr change is proposed only."
            ),
            params=ApplyArgs.model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary="Apply one fix the simulation proposed, then re-run its simulation",
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            parsed = _apply_args(args)
            async with self.sessions() as session:
                rows = await self._rows(session, parsed)
        except APIError as exc:
            raise PreviewRefusal(f"{exc.message}. Nothing was parked.") from None
        if not _complete_preview(rows):  # M3: the turn's apply is claimed only for a whole card
            raise PreviewRefusal(
                "The change cannot be shown in full on its card. Nothing was parked."
            )
        _claim_apply(parsed)
        return rows

    async def _rows(self, session: AsyncSession, parsed: ApplyArgs) -> list[dict[str, Any]]:
        subject = await _live_subject(session, self.project_id, parsed.subject_id)
        if subject is None:
            raise APIError(404, "not_found", "Subject not found")
        owner = owning_domain(subject.attrs)
        if owner is None:
            raise PreviewRefusal(
                f"Set attrs.owning_domain on {shown(subject.name)} first: no change is applied "
                "without it. Nothing was parked."
            )
        change = parsed.change
        if isinstance(change, AttrChange) or writer_for(owner, change) is None:  # no attr writer
            text = describe_change(change, await _target_name(session, self.project_id, change))
            raise PreviewRefusal(f"{_propose_only(owner, text)}. Nothing was parked.")
        return [
            {
                "label": "Simulation",
                "before": None,
                "after": f"{shown(subject.name)}: {parsed.quantity}",
            },
            {"label": "Owning domain", "before": None, "after": owner},
            *await self._change_rows(session, parsed, change),
            {
                "label": "After approval",
                "before": None,
                "after": f"rung 1 re-runs {parsed.quantity} and records the result",
            },
        ]

    async def _change_rows(
        self, session: AsyncSession, parsed: ApplyArgs, change: ConfigChange | ConstraintChange
    ) -> list[dict[str, Any]]:
        if isinstance(change, ConstraintChange):
            return [
                {"label": f"constraints/{change.subsection}", "before": None, "after": change.text}
            ]
        entity = await hardware_entity(session, self.project_id, change.entity_id)
        entry, config = await read_entity_config(session, self.project_id, entity.id)
        if entry is None or config is None:
            raise APIError(404, "not_found", "Hardware config not found")
        before = _leaf_value(config.model_dump(mode="json"), change.path)
        if len(self._revisions) >= MAX_PREVIEWS:
            self._revisions.pop(next(iter(self._revisions)))
        self._revisions[parsed.key()] = (entry.id, entry.config_version)
        return [
            {
                "label": f"{shown(entity.name)}: {change.path}",
                "before": before if before == _UNSET else _shown_value(before),
                "after": _shown_value(change.value),
            },
            {
                "label": "Config version",
                "before": str(entry.config_version),
                "after": str(entry.config_version + 1),
            },
        ]

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        """Only ever after the person approved the card (the confirmation flow runs it). Once the
        change is written, a re-run that fails is its own line, never the call's failure (M4)."""
        parsed = _apply_args(args)
        try:
            applied = await self._apply(parsed)
        except APIError as exc:
            code = ToolErrorCode.NOT_FOUND if exc.status_code == 404 else ToolErrorCode.INVALID_ARGS
            raise ToolException(exc.message, code=code) from None
        try:
            rerun = await self._rerun(parsed)
        except Exception:  # the change has landed: say so beside the re-run that did not happen
            logger.warning(
                "re-run failed after an applied change project=%s subject=%s quantity=%s",
                self.project_id,
                parsed.subject_id,
                parsed.quantity,
                exc_info=True,
            )
            rerun = {
                "decision": "failed",
                "reason": f"the change was applied; rung 1 could not re-run {parsed.quantity}",
            }
        return {"applied": applied, "rerun": rerun}

    async def _apply(self, parsed: ApplyArgs) -> str:
        change = parsed.change
        async with self.sessions() as session:
            subject = await _live_subject(session, self.project_id, parsed.subject_id)
            owner = None if subject is None else owning_domain(subject.attrs)
            if owner is None:
                raise APIError(404, "not_found", "Subject not found")
            if isinstance(change, AttrChange) or writer_for(owner, change) is None:
                text = describe_change(change, await _target_name(session, self.project_id, change))
                raise ToolException(
                    f"{_propose_only(owner, text)}. Nothing was applied.",
                    code=ToolErrorCode.INVALID_ARGS,
                )
            if isinstance(change, ConstraintChange):
                await add_text_entry(
                    session,
                    self.project_id,
                    SolusSection.CONSTRAINTS,
                    change.text,
                    author="sol",
                    created_by=self.user_id,
                    subsection=change.subsection,
                )
                await session.commit()
                return describe_change(change)
            name = await self._write_config(session, parsed, change)
            return describe_change(change, name)

    async def _write_config(
        self, session: AsyncSession, parsed: ApplyArgs, change: ConfigChange
    ) -> str:
        """The field set through the config writer, on the version the card showed."""
        revision = self._revisions.pop(parsed.key(), None)
        await lock_project(session, self.project_id)
        entity = await hardware_entity(session, self.project_id, change.entity_id)
        entry, config = await read_entity_config(session, self.project_id, entity.id)
        if entry is None or config is None:
            raise APIError(404, "not_found", "Hardware config not found")
        if revision != (entry.id, entry.config_version):
            raise ToolException(
                "The configuration changed since the card was shown. Nothing was applied.",
                code=ToolErrorCode.UNAUTHORIZED,
            )
        document = config.model_dump(mode="json")
        _set_leaf(document, change.path, change.value)
        document["provenance"][change.path] = {
            "by": FieldProvenance.SOL.value,
            "source": SOL_SOURCE,
        }
        try:
            validated = EntityHardwareConfig.model_validate(document)
        except ValidationError:
            raise ToolException(
                "Invalid hardware configuration value", code=ToolErrorCode.INVALID_ARGS
            ) from None
        await put_entity_config(
            session,
            self.project_id,
            entity,
            validated,
            expected_version=entry.config_version,
            created_by=self.user_id,
        )
        await session.commit()
        return entity.name

    async def _rerun(self, parsed: ApplyArgs) -> dict[str, Any]:
        """Rung 1 again for the question, on the subject's facts as they now are, and recorded.
        The change has landed, so a re-run that cannot happen says why instead of failing it."""
        provider = rung_one_for(parsed.quantity)
        async with self.sessions() as session:
            subject = await _live_subject(session, self.project_id, parsed.subject_id)
        if provider is None or subject is None:
            return {"decision": "not_run", "reason": f"no rung-1 run answers {parsed.quantity}"}
        question = SimQuestion(subject_id=subject.id, quantity=parsed.quantity, facts=subject.attrs)
        lacks = provider.can_answer(question)
        if lacks.missing:
            return {"decision": "not_run", "missing": [need.model_dump() for need in lacks.missing]}
        result = provider.run(provider.inputs_for(subject.attrs))
        try:
            sim_id = await record_sim_result(
                self.sessions,
                self.hub,
                project_id=self.project_id,
                subject_id=subject.id,
                rung=provider.rung,
                result=result,
                created_by=self.user_id,
            )
        except APIError as exc:
            return {"decision": "not_run", "reason": exc.message}
        return {
            "decision": "ran",
            "sim_result_id": str(sim_id),
            "values": {name: value.model_dump() for name, value in result.values.items()},
            "verdict": "fails" if is_failing(result) else "passes",
        }


def register_apply_sim_change_tool(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    hub: LiveHub,
) -> None:
    """Add `apply_sim_change`, gated, for ONE project and person. It is never passed to
    `register_owned_routine`, so no Build policy runs it without its card."""
    registry.register(SimChangeTool(sessions, project_id, user_id=user_id, hub=hub))
