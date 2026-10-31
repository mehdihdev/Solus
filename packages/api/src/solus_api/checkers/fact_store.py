"""SOLUSDEV-321 P3-T1 — the facts a matrix run reads besides the graph, gathered once per run.

`build_fact_store` reads them from the run's graph — the `GraphContext` the run built through
`to_graph_context`, so a candidate edge never reaches a fact — and from the project's own configs,
through the loaders the hardware and `.solus` routes use. It never calls a model and names no
vendor or connector. `FactStore` holds the result as plain data: a matrix rule reads the graph and
the store and nothing else (ADR-003). A fact the project does not state is absent, never guessed,
and a rule that needs it reports `unknown_input` (`checkers/matrix_rule.py`).

Each field is the name a rule's `FactNeed` uses for it (`has`):

- `definitions`: entity → the library part its `attrs.definition_id` names.
- `runtime_configs`: robot → its resolved runtime config (`part_config` finds a part's slot).
- `budgets`: the `constraints/budgets` CONFIG.
- `scene_joints`: part → the scene joint its scene model's bindings map it to.
- `pcb_positions`: component → where it sits on its board, when its attrs state it.
- `software_environments`, `divergences`: the `environment/software` and
  `environment/divergences` CONFIGs.
- `style`: the `constraints/style` entries a person typed or SOL filed.
- `expected_values`: part → quantity → what a simulation expects of it (`attrs.expected`, written
  by P4; read through `expected`).
- `motifs` (P3-T4): the netlist motifs the graph's schematic holds (`checkers/netlist_motifs.py`).
  They are found once a run, and the matrix job keeps them on their members.
- `rc_settling_s` (P3-T4, R73): each member of a settled ADC input (a divider or an RC filter)
  → the RC the input settles through.
- `proximity_clearance_mm` (P3-T4, R73): the largest lower bound in millimetres that a
  `constraints/rules` entry states for that quantity.
- `module_interfaces` (P6): each entity's `attrs.module_interfaces`, the policy and controller
  interfaces the software reader found in its file, with the source that landed it (one lookup
  of the holders' `source_id`), since a contract is judged within one source.

Beside the facts, `simulation` (P4-T5) holds the ladder's bands, the shipped `simulation:` section
of models.yaml: a rule judging a simulated value settles one with margin where the ladder stops.
It is configuration, never a fact: `FACT_NAMES` leaves it out, so no rule waits for it.

Graph facts come from the graph the run passes, so it must hold the entities they are read off
(the scene models, the components, and the schematic's nets and `connected_to` pins); config reads
are scoped by `project_id` alone.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from functools import cache
from typing import TYPE_CHECKING, Any, Final, NamedTuple
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from solus_api.checkers.netlist_motifs import INPUT_KINDS, NetMotif, detect_motifs
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.hardware.library import DefinitionError, load_library
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.livebench.scene.part_bindings import finite_number, scene_joint_for_part
from solus_api.models import GraphEntity, SolusEntry, SolusEntryKind, SolusSection
from solus_api.orchestration.config import SimulationConfig, load_orchestration_config
from solus_api.services.budgets import find_budgets_entry
from solus_api.services.code_env import list_code_environments
from solus_api.services.environment_divergence import find_divergences_entry
from solus_api.services.solus_payloads import Budgets, ConstraintMeta, EnvironmentDivergencesDoc
from solus_api.software.policy_reader import ModuleInterface

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.agent.interfaces import GraphContext
    from solus_api.hardware.config import HardwareConfig, PartConfig
    from solus_api.hardware.library import Library, PartDefinition
    from solus_api.livebench.scene.part_bindings import JointRange
    from solus_api.services.code_env import CodeEnvironment

logger = logging.getLogger("solus.checkers.fact_store")

_STYLE: Final = "style"
_RULES: Final = "rules"
#: The `constraints/rules` quantity a proximity clearance is stated under, and its unit.
CLEARANCE_QUANTITY: Final = "proximity_clearance_mm"
_MM: Final = "mm"
_LOWER_BOUNDS: Final = frozenset({">=", ">"})
#: The `attrs.module_interfaces` items one entity's file may state (the reader states at most 16).
MAX_MODULE_INTERFACES: Final = 16


class BoardPosition(NamedTuple):
    """Where a component sits on its board, in the units its source states."""

    x: float
    y: float
    rot: float | None


class StyleEntry(NamedTuple):
    """One `constraints/style` entry: its words and, when it states one, its constraint."""

    entry_id: UUID
    text: str
    meta: ConstraintMeta | None


class ExpectedValue(NamedTuple):
    """What a simulation expects of one quantity of a part, in the unit it states."""

    value: float
    unit: str | None
    sim_result_id: str | None


class RcSettling(NamedTuple):
    """The RC an ADC input settles through: the net it is on, the resistance its capacitance
    charges through (ohms) and that capacitance (farads)."""

    net_id: UUID
    r_ohm: float
    c_f: float

    @property
    def tau_s(self) -> float:
        """Its time constant, R · C."""
        return self.r_ohm * self.c_f


class ModuleFacts(NamedTuple):
    """The module interfaces one entity's file states, and the source that landed it."""

    source_id: UUID | None
    interfaces: tuple[ModuleInterface, ...]


@cache
def shipped_simulation() -> SimulationConfig:
    """The shipped `simulation:` section of models.yaml, read once a process: a deploy changes it,
    as it changes the rest of the orchestration config."""
    return load_orchestration_config().simulation


@dataclass(frozen=True, kw_only=True)
class FactStore:
    """One run's facts (the module docstring says what each holds); empty by default."""

    #: The ladder's bands (P4-T5): configuration a rule judging a simulated value reads, so it
    #: settles a value with margin where the ladder stops. Never a fact (`FACT_NAMES`).
    simulation: SimulationConfig = field(default_factory=shipped_simulation)
    definitions: Mapping[UUID, PartDefinition] = field(default_factory=dict)
    runtime_configs: Mapping[UUID, HardwareConfig] = field(default_factory=dict)
    budgets: Budgets | None = None
    scene_joints: Mapping[UUID, JointRange] = field(default_factory=dict)
    pcb_positions: Mapping[UUID, BoardPosition] = field(default_factory=dict)
    software_environments: tuple[CodeEnvironment, ...] = ()
    divergences: EnvironmentDivergencesDoc | None = None
    style: tuple[StyleEntry, ...] = ()
    expected_values: Mapping[UUID, Mapping[str, ExpectedValue]] = field(default_factory=dict)
    motifs: tuple[NetMotif, ...] = ()
    rc_settling_s: Mapping[UUID, RcSettling] = field(default_factory=dict)
    proximity_clearance_mm: float | None = None
    module_interfaces: Mapping[UUID, ModuleFacts] = field(default_factory=dict)

    def has(self, name: str) -> bool:
        """Whether the store holds the fact a `FactNeed` names: one of its fields, not empty.
        Any other name (a fact no source states yet) is never held."""
        return name in FACT_NAMES and bool(getattr(self, name))

    def part_config(self, part_id: UUID) -> PartConfig | None:
        """The part's slot in the resolved runtime config of the robot that lists it."""
        key = str(part_id)
        return next((c.parts[key] for c in self.runtime_configs.values() if key in c.parts), None)

    def expected(self, part_id: UUID, quantity: str) -> ExpectedValue | None:
        """What a simulation expects of the part's `quantity`; None until one has run (P4)."""
        return self.expected_values.get(part_id, {}).get(quantity)


#: The names a rule's `FactNeed` may hold: the store's fields, but its configuration.
FACT_NAMES: Final = frozenset(item.name for item in fields(FactStore)) - {"simulation"}


async def build_fact_store(
    session: AsyncSession,
    project_id: UUID,
    graph: GraphContext,
    *,
    library: Library | None = None,
) -> FactStore:
    """The run's facts, each read once. `library` defaults to the curated part library."""
    divergences = await find_divergences_entry(session, project_id)
    # m5: a read cut at its cap may hold half a net, and half a net can settle a wrong RC
    motifs = () if graph.truncated else detect_motifs(graph)
    return FactStore(
        definitions=_definitions(graph, library),
        runtime_configs=await _runtime_configs(session, project_id, graph),
        budgets=_config_doc(await find_budgets_entry(session, project_id), Budgets),
        scene_joints=_scene_joints(graph),
        pcb_positions=_pcb_positions(graph),
        software_environments=await _software_environments(session, project_id),
        divergences=_config_doc(divergences, EnvironmentDivergencesDoc),
        style=await _style(session, project_id),
        expected_values=_expected_values(graph),
        motifs=motifs,
        rc_settling_s=_rc_settling(motifs),
        proximity_clearance_mm=await _clearance(session, project_id),
        module_interfaces=await _module_interfaces(session, project_id, graph),
    )


def _definitions(graph: GraphContext, library: Library | None) -> dict[UUID, PartDefinition]:
    """The library part each entity's `attrs.definition_id` names; an unknown id names none."""
    named = {entity.id: entity.attrs.get("definition_id") for entity in graph.entities}
    wanted = {entity_id: did for entity_id, did in named.items() if isinstance(did, str)}
    if not wanted:
        return {}
    try:
        parts = (library if library is not None else load_library()).parts
    except DefinitionError:
        logger.warning("the part library does not load; no definitions", exc_info=True)
        return {}
    return {entity_id: parts[did] for entity_id, did in wanted.items() if did in parts}


async def _runtime_configs(
    session: AsyncSession, project_id: UUID, graph: GraphContext
) -> dict[UUID, HardwareConfig]:
    """Each robot's resolved runtime config; one that does not read is left out and logged."""
    configs: dict[UUID, HardwareConfig] = {}
    for robot in (entity for entity in graph.entities if entity.kind == kinds.PHYSICAL_ROBOT):
        try:
            configs[robot.id] = await resolve_runtime_config(session, project_id, robot.id)
        except (APIError, ValidationError):
            logger.warning(
                "runtime config left out project=%s robot=%s", project_id, robot.id, exc_info=True
            )
    return configs


def _config_doc[M: BaseModel](entry: SolusEntry | None, model: type[M]) -> M | None:
    """A stored CONFIG document as its model; None without one, or when it does not read."""
    if entry is None or entry.payload is None:
        return None
    try:
        return model.model_validate(entry.payload)
    except ValidationError:
        logger.warning("config left out project=%s entry=%s", entry.project_id, entry.id)
        return None


def _scene_joints(graph: GraphContext) -> dict[UUID, JointRange]:
    """Each part's scene joint, by the rule the first tier and the envelopes share."""
    scenes = [(e.id, e.attrs) for e in graph.entities if e.kind == kinds.BENCH_SCENE_MODEL]
    joints = {e.id: scene_joint_for_part(scenes, e.id) for e in graph.entities} if scenes else {}
    return {part_id: joint for part_id, joint in joints.items() if joint is not None}


def _pcb_positions(graph: GraphContext) -> dict[UUID, BoardPosition]:
    """Each component's `attrs.position` whose `x` and `y` are finite numbers."""
    found: dict[UUID, BoardPosition] = {}
    for entity in graph.entities:
        raw = entity.attrs.get("position")
        if entity.kind != kinds.COMPONENT or not isinstance(raw, Mapping):
            continue
        x, y = finite_number(raw.get("x")), finite_number(raw.get("y"))
        if x is not None and y is not None:
            found[entity.id] = BoardPosition(x, y, finite_number(raw.get("rot")))
    return found


async def _software_environments(
    session: AsyncSession, project_id: UUID
) -> tuple[CodeEnvironment, ...]:
    try:
        return tuple(await list_code_environments(session, project_id))
    except ValidationError:
        logger.warning("software environments left out project=%s", project_id, exc_info=True)
        return ()


async def _stated(session: AsyncSession, project_id: UUID, subsection: str) -> list[StyleEntry]:
    """The live `constraints/<subsection>` entries a person typed or SOL filed, oldest first. An
    imported file filed there is a document, not a stated constraint (the budgets rule)."""
    rows = await session.scalars(
        select(SolusEntry)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == SolusSection.CONSTRAINTS,
            SolusEntry.subsection == subsection,
            SolusEntry.kind.in_((SolusEntryKind.TEXT, SolusEntryKind.SOL)),
            SolusEntry.deleted_at.is_(None),
        )
        .order_by(SolusEntry.created_at, SolusEntry.id)
    )
    return [StyleEntry(row.id, row.text or "", _constraint(row.payload)) for row in rows]


async def _style(session: AsyncSession, project_id: UUID) -> tuple[StyleEntry, ...]:
    """The `constraints/style` entries a person typed or SOL filed."""
    return tuple(await _stated(session, project_id, _STYLE))


async def _clearance(session: AsyncSession, project_id: UUID) -> float | None:
    """The largest `proximity_clearance_mm` a `constraints/rules` entry states as a lower bound
    (`>=` or `>`) in millimetres. A bound in another unit, or an upper bound, is not one."""
    limits = [
        limit
        for entry in await _stated(session, project_id, _RULES)
        if (limit := lower_bound_mm(entry.meta, CLEARANCE_QUANTITY)) is not None
    ]
    return max(limits, default=None)


def lower_bound_mm(meta: ConstraintMeta | None, quantity: str) -> float | None:
    """The limit a constraint states for `quantity` as a lower bound (`>=` or `>`) in millimetres,
    above zero. None for anything else: another unit, an upper bound, no bound. Shared with the
    manufacturing rules' minimum wall (m12)."""
    if meta is None or meta.quantity != quantity or meta.unit != _MM:
        return None
    if meta.comparator not in _LOWER_BOUNDS or meta.limit is None or meta.limit <= 0:
        return None
    return meta.limit


def _constraint(payload: Mapping[str, Any] | None) -> ConstraintMeta | None:
    """An entry's payload as its constraint; None without one, or when it does not read."""
    if payload is None:
        return None
    try:
        return ConstraintMeta.model_validate(payload)
    except ValidationError:
        return None


def _rc_settling(motifs: Sequence[NetMotif]) -> dict[UUID, RcSettling]:
    """Each member of a settled ADC input whose RC is stated → that RC. A candidate's members
    state none: a rule never reads an unsettled motif. A member two such inputs share states
    neither, since it cannot say which input a read samples."""
    found: dict[UUID, RcSettling] = {}
    shared: set[UUID] = set()
    for motif in motifs:
        if motif.kind not in INPUT_KINDS or not motif.settled or motif.rc is None:
            continue
        settling = RcSettling(motif.net, *motif.rc)
        for member in motif.members:
            if found.setdefault(member, settling) != settling:
                shared.add(member)
    return {member: settling for member, settling in found.items() if member not in shared}


def _expected_values(graph: GraphContext) -> dict[UUID, dict[str, ExpectedValue]]:
    """Each entity's `attrs.expected` quantities whose value is a finite number."""
    found: dict[UUID, dict[str, ExpectedValue]] = {}
    for entity in graph.entities:
        raw = entity.attrs.get("expected")
        stated = {
            quantity: value
            for quantity, item in (raw.items() if isinstance(raw, Mapping) else ())
            if isinstance(quantity, str) and (value := _expected(item)) is not None
        }
        if stated:
            found[entity.id] = stated
    return found


def _expected(item: object) -> ExpectedValue | None:
    """`{value, unit, sim_result_id}` as P4 writes it; None unless `value` is a finite number."""
    value = finite_number(item.get("value")) if isinstance(item, Mapping) else None
    if value is None or not isinstance(item, Mapping):
        return None
    unit, source = item.get("unit"), item.get("sim_result_id")
    return ExpectedValue(
        value, unit if isinstance(unit, str) else None, source if isinstance(source, str) else None
    )


async def _module_interfaces(
    session: AsyncSession, project_id: UUID, graph: GraphContext
) -> dict[UUID, ModuleFacts]:
    """Each entity's valid `attrs.module_interfaces` items, with the source that landed it, read
    in one lookup scoped to the project. An item that does not validate is left out."""
    stated = {
        entity.id: _interfaces(entity.attrs.get("module_interfaces")) for entity in graph.entities
    }
    held = {entity_id: found for entity_id, found in stated.items() if found}
    if not held:
        return {}
    rows = await session.execute(
        select(GraphEntity.id, GraphEntity.source_id).where(
            GraphEntity.project_id == project_id, GraphEntity.id.in_(held)
        )
    )
    sources = {row[0]: row[1] for row in rows.all()}
    return {
        entity_id: ModuleFacts(sources.get(entity_id), found) for entity_id, found in held.items()
    }


def _interfaces(raw: object) -> tuple[ModuleInterface, ...]:
    """The `attrs.module_interfaces` items that validate, at most MAX_MODULE_INTERFACES."""
    if not isinstance(raw, list):
        return ()
    found: list[ModuleInterface] = []
    for item in raw[:MAX_MODULE_INTERFACES]:
        try:
            found.append(ModuleInterface.model_validate(item))
        except ValidationError:
            continue
    return tuple(found)
