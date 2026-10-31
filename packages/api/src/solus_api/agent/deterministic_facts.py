"""SOLUSDEV-321 P1-T2 — the facts SOL's first tier reads (`agent/deterministic.py`).

Their shapes, the `FactSources` seams the first tier reads them through, and `GraphFactSources`,
those seams over the project's own data. Each seam is one short read in its own session from the
request's sessionmaker (never the request session, which is gone by the time the turn streams),
and every query is scoped to the project the route bound (§7): an id from another project reads
as nothing. The edges read here pass `is_candidate`, so a candidate never reaches an answer as a
fact. A machine's recent commands reach only the member who owns it (the project card's rule). A
list read returns its first rows and whether more exist (`FactPage`), so an answer can say it
was cut. `robot_of` and `contents_of` are the pure graph reads over the planned scope. Nothing
here calls a model.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, Protocol

from solus_contracts.relations import RelationType
from sqlalchemy import select

from solus_api.agent.project_card import owned_commands
from solus_api.agent.solus_layer import _scoped_errors
from solus_api.graph import kinds
from solus_api.graph.edges import is_candidate
from solus_api.graph.findings import list_findings
from solus_api.hardware.library import PartDefinition, load_library
from solus_api.hardware.runtime import resolve_runtime_config

# re-exported on purpose: the name moved to part_bindings, P1's tests still import it from here
from solus_api.livebench.scene.part_bindings import JointRange as JointRange
from solus_api.livebench.scene.part_bindings import (
    bound_scenes,
    channel_for_quantity,
    scene_joint_for_part,
)
from solus_api.models import Activity, GraphEdge, GraphEntity
from solus_api.services.budgets import find_budgets_entry
from solus_api.services.environment_divergence import find_divergences_entry
from solus_api.services.machines import find_machine
from solus_api.services.solus_config import load_sections
from solus_api.services.solus_payloads import (
    BudgetLine,
    Budgets,
    EnvironmentDivergencesDoc,
    MachineDivergences,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.interfaces import EntityRead, GraphContext
    from solus_api.agent.turn_scope import TurnScope
    from solus_api.graph.telemetry import TelemetryPlumbing
    from solus_api.hardware.config import PartConfig
    from solus_api.hardware.library import Library
    from solus_api.livebench.sessions import BenchSessionOut, SessionManager

#: How much one answer reads: open findings, history rows, a machine's recent commands.
_FINDINGS: Final = 5
_HISTORY: Final = 5
_COMMANDS: Final = 5
_CONTAINS: Final = RelationType.CONTAINS.value


@dataclass(frozen=True)
class FactPage[T]:
    """The first rows of a list read, and whether more exist past them."""

    rows: tuple[T, ...]
    more: bool


@dataclass(frozen=True)
class Reading:
    """The newest buffered sample of one part's channel, with the unit it came with."""

    signal: str
    value: float
    unit: str | None
    at: datetime


@dataclass(frozen=True)
class FindingFact:
    id: uuid.UUID
    severity: str
    headline: str


@dataclass(frozen=True)
class ErrorFact:
    """One `.solus` `errors` entry that blames the entity."""

    id: uuid.UUID
    text: str
    status: str
    count: int


@dataclass(frozen=True)
class HistoryFact:
    type: str
    at: datetime


@dataclass(frozen=True)
class MachineFact:
    """A machine of the project. `recent_commands` (newest first, redacted and capped) are its
    owner's alone: for anyone else the tuple is empty."""

    id: uuid.UUID
    hostname: str
    os: str
    arch: str
    recent_commands: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class BudgetsFact:
    entry_id: uuid.UUID
    computed_at: datetime
    lines: tuple[BudgetLine, ...]


@dataclass(frozen=True)
class DivergencesFact:
    """The stored divergences table, kept to the asker's own machines: "here" is where they
    work."""

    entry_id: uuid.UUID
    computed_at: datetime
    machines: tuple[MachineDivergences, ...]


class FactSources(Protocol):
    """What the first tier reads (`GraphFactSources` over the database): each seam one short
    read, every query scoped to the project the route bound."""

    #: The project every read is scoped to; a failed read's warning names it.
    project_id: uuid.UUID

    async def definition(self, entity: EntityRead) -> PartDefinition | None:
        """The library part `attrs.definition_id` names (`limits`, `pins`, …); None without."""
        ...

    async def part_limits(self, entity: EntityRead) -> Mapping[str, float | int]:
        """`limits.values` of the part in its robot's resolved runtime config; {} without."""
        ...

    async def scene_joint(self, entity: EntityRead) -> JointRange | None: ...

    def edges(self, scope: TurnScope) -> GraphContext:
        """The turn's planned graph: the ONE pull, never a second."""
        ...

    async def latest(self, entity: EntityRead, quantity: str) -> Reading | None:
        """The newest sample of the part's one telemetry channel for `quantity`."""
        ...

    async def findings(self, subject: uuid.UUID) -> FactPage[FindingFact]:
        """The open findings observing the subject, newest first: the first five, and whether
        more exist."""
        ...

    async def errors(self, entity: uuid.UUID) -> Sequence[ErrorFact]: ...

    async def budgets(self) -> BudgetsFact | None: ...

    async def divergences(self) -> DivergencesFact | None: ...

    async def history(self, since: datetime | None, entity: uuid.UUID) -> FactPage[HistoryFact]:
        """The project history rows naming the entity, newest first: the first five, and
        whether more exist."""
        ...

    async def machine(self, companion_id: str) -> MachineFact | None: ...

    async def sessions(self, robot: EntityRead) -> Sequence[BenchSessionOut] | None:
        """The active bench sessions streaming the robot's device ref; None without a source."""
        ...


class GraphFactSources:
    """`FactSources` over the database, bound by the route to the request's project and user.
    `telemetry` reads the buffer through the plumbing's entity-scoped `get_recent_values` (the
    buffer is private to it); without it, or without `sessions`, those seams have no fact and the
    first tier declines. `library` defaults to the curated one."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        telemetry: TelemetryPlumbing | None = None,
        sessions: SessionManager | None = None,
        library: Library | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self.project_id = project_id
        self._user_id = user_id
        self._telemetry = telemetry
        self._sessions = sessions
        self._library = library

    async def definition(self, entity: EntityRead) -> PartDefinition | None:
        definition_id = entity.attrs.get("definition_id")
        if not isinstance(definition_id, str):
            return None
        found = (self._library or load_library()).get("part", definition_id)
        return found if isinstance(found, PartDefinition) else None

    async def part_limits(self, entity: EntityRead) -> dict[str, float | int]:
        part = await self._part_config(entity.id)
        return dict(part.limits.values) if part is not None and part.limits is not None else {}

    async def scene_joint(self, entity: EntityRead) -> JointRange | None:
        """The joint the project's scene models bind to the part (`part_bindings`): two bound
        joints that disagree on the range are None, since which one is meant is not known."""
        async with self._sessionmaker() as session:
            scenes = await bound_scenes(session, self.project_id, [entity.id])
        return scene_joint_for_part(scenes, entity.id)

    def edges(self, scope: TurnScope) -> GraphContext:
        return scope.graph

    async def latest(self, entity: EntityRead, quantity: str) -> Reading | None:
        part = await self._part_config(entity.id) if self._telemetry is not None else None
        channel = channel_for_quantity(part.telemetry if part is not None else (), quantity)
        if self._telemetry is None or channel is None:
            return None  # no channel for the quantity, or two: which one is not known
        view = await self._telemetry.get_recent_values(
            self.project_id, entity.id, signals=[channel.name], limit=1
        )
        samples = [sample for series in view.signals for sample in series.points]
        if not samples:
            return None
        newest = samples[-1]
        unit = newest.unit or channel.unit
        return Reading(signal=channel.name, value=newest.value, unit=unit, at=newest.timestamp)

    async def findings(self, subject: uuid.UUID) -> FactPage[FindingFact]:
        async with self._sessionmaker() as session:
            rows, meta = await list_findings(
                session, self.project_id, status="open", subjects=[subject], limit=_FINDINGS
            )
            found = tuple(
                FindingFact(
                    id=row.id,
                    severity=str(row.attrs.get("severity")),
                    headline=str(row.attrs.get("headline") or row.name),
                )
                for row in rows
            )
        return FactPage(found, more=bool(meta.get("has_next")))

    async def errors(self, entity: uuid.UUID) -> tuple[ErrorFact, ...]:
        """The P0-T6 read (`solus_layer._scoped_errors`) for one entity."""
        async with self._sessionmaker() as session:
            sections = await load_sections(session, self.project_id)
        return tuple(
            ErrorFact(
                id=uuid.UUID(str(entry["id"])),
                text=str(entry.get("text") or ""),
                status=meta.status,
                count=meta.count,
            )
            for entry, meta in _scoped_errors(sections, frozenset({entity}))
        )

    async def budgets(self) -> BudgetsFact | None:
        async with self._sessionmaker() as session:
            entry = await find_budgets_entry(session, self.project_id)
            if entry is None or entry.payload is None:
                return None
            document = Budgets.model_validate(entry.payload)
            return BudgetsFact(entry.id, document.computed_at, tuple(document.budgets))

    async def divergences(self) -> DivergencesFact | None:
        async with self._sessionmaker() as session:
            entry = await find_divergences_entry(session, self.project_id)
            if entry is None or entry.payload is None:
                return None
            document = EnvironmentDivergencesDoc.model_validate(entry.payload)
            listed = [machine.machine_id for machine in document.machines]
            mine = set(
                await session.scalars(
                    select(GraphEntity.id).where(
                        GraphEntity.project_id == self.project_id,
                        GraphEntity.kind == kinds.MACHINE,
                        GraphEntity.deleted_at.is_(None),
                        GraphEntity.id.in_(listed),
                        GraphEntity.attrs["owner_user_id"].astext == str(self._user_id),
                    )
                )
            )
            machines = tuple(row for row in document.machines if row.machine_id in mine)
            return DivergencesFact(entry.id, document.computed_at, machines)

    async def history(self, since: datetime | None, entity: uuid.UUID) -> FactPage[HistoryFact]:
        """The query behind `GET /projects/{id}/history` (routers/history.py has no service to
        call): this project's rows naming the entity, newest first. One row past the page says
        whether more exist."""
        stmt = select(Activity.type, Activity.created_at).where(
            Activity.project_id == self.project_id,
            Activity.entity_ids.contains([str(entity)]),
        )
        if since is not None:
            stmt = stmt.where(Activity.created_at >= since)
        stmt = stmt.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(_HISTORY + 1)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).tuples().all()
        found = tuple(HistoryFact(type=kind, at=at) for kind, at in rows)
        return FactPage(found[:_HISTORY], more=len(found) > _HISTORY)

    async def machine(self, companion_id: str) -> MachineFact | None:
        """The project's machine with this companion id. Its recent commands only when the asker
        owns its row: another member's are never returned (`project_card.owned_commands`)."""
        async with self._sessionmaker() as session:
            row = await find_machine(session, self.project_id, companion_id)
            if row is None:
                return None
            attrs = row.attrs
            return MachineFact(
                id=row.id,
                hostname=str(attrs.get("hostname") or row.name),
                os=str(attrs.get("os") or "?"),
                arch=str(attrs.get("arch") or "?"),
                recent_commands=owned_commands(attrs, self._user_id, limit=_COMMANDS),
            )

    async def sessions(self, robot: EntityRead) -> tuple[BenchSessionOut, ...] | None:
        """The active bench sessions whose devices include the robot's ref — the project card's
        mapping (`external_ref ∈ device_ids`); None without a session manager or a ref."""
        if self._sessions is None or not robot.external_ref:
            return None
        active = self._sessions.list(self.project_id, status="active")
        return tuple(bench for bench in active if robot.external_ref in bench.device_ids)

    async def _part_config(self, part_id: uuid.UUID) -> PartConfig | None:
        """The part's slot in its owning robot's resolved runtime config."""
        async with self._sessionmaker() as session:
            robot = await self._owner(session, part_id)
            if robot is None:
                return None
            config = await resolve_runtime_config(session, self.project_id, robot)
        return config.parts.get(str(part_id))

    async def _owner(self, session: AsyncSession, part_id: uuid.UUID) -> uuid.UUID | None:
        """The one robot that owns the part: a physical robot that `contains` it, or the robot
        of a robot category that does (`hardware/store.py`'s ownership)."""
        edges = await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == self.project_id,
                GraphEdge.dst_id == part_id,
                GraphEdge.relation_type == _CONTAINS,
                GraphEdge.deleted_at.is_(None),
            )
        )
        holders = [edge.src_id for edge in edges if not is_candidate(edge)]
        rows = await session.execute(
            select(GraphEntity.id, GraphEntity.kind, GraphEntity.attrs["robot_id"].astext).where(
                GraphEntity.project_id == self.project_id,
                GraphEntity.id.in_(holders),
                GraphEntity.deleted_at.is_(None),
                GraphEntity.kind.in_((kinds.PHYSICAL_ROBOT, kinds.ROBOT_CATEGORY)),
            )
        )
        robots = {
            holder if kind == kinds.PHYSICAL_ROBOT else _as_uuid(robot_id)
            for holder, kind, robot_id in rows.tuples()
        }
        robots.discard(None)
        return robots.pop() if len(robots) == 1 else None


def robot_of(entity: EntityRead | None, graph: GraphContext) -> EntityRead | None:
    """The entity itself when it is a physical robot, else the one robot in scope that
    `contains` it, directly or through one of its robot categories (the store files parts
    under them). None on a cut graph: the edge that settles it may be the one cut."""
    if entity is None or graph.truncated:
        return None
    if entity.kind == kinds.PHYSICAL_ROBOT:
        return entity
    named = {node.id: node for node in graph.entities}
    holders = _holders(graph, entity.id)
    via = {
        owner
        for category in _of_kind(named, holders, kinds.ROBOT_CATEGORY)
        for owner in _holders(graph, category)
    }
    robots = _of_kind(named, holders | via, kinds.PHYSICAL_ROBOT)
    return named[next(iter(robots))] if len(robots) == 1 else None


def contents_of(holder: EntityRead, graph: GraphContext) -> list[EntityRead]:
    """What the holder `contains` in scope. A robot category it contains is see-through: its
    parts count as the holder's, the category itself does not."""
    named = {node.id: node for node in graph.entities}
    inside = _held(graph, holder.id)
    categories = _of_kind(named, inside, kinds.ROBOT_CATEGORY)
    found = (inside - categories) | {part for kept in categories for part in _held(graph, kept)}
    return [node for node in graph.entities if node.id in found]


def _held(graph: GraphContext, holder: uuid.UUID) -> set[uuid.UUID]:
    return {e.dst_id for e in graph.edges if e.src_id == holder and e.relation_type == _CONTAINS}


def _holders(graph: GraphContext, held: uuid.UUID) -> set[uuid.UUID]:
    return {e.src_id for e in graph.edges if e.dst_id == held and e.relation_type == _CONTAINS}


def _of_kind(
    named: Mapping[uuid.UUID, EntityRead], ids: Iterable[uuid.UUID], kind: str
) -> set[uuid.UUID]:
    return {node for node in ids if node in named and named[node].kind == kind}


def _as_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None
