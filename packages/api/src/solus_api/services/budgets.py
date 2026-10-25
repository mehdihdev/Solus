"""Project budgets (SOLUSDEV-320 P5-T6, docs/api/solus.md §2.1 `constraints/budgets`).

Three budgets read straight from the graph, never guessed: power per rail from the live
`powers` edges (`attrs.nets`; each sink's draw from its part definition `limits.current_a` /
`stall_current_a` or the `current_draw_a` attr, each supply's rating from `limits.current_a`
or `current_max_a`), mass from part definitions' `mass_g` plus the `mass_kg` / `weight_kg` /
`mass` attrs sourcing already reads, cost from the BOM widget's totals. A value the graph
does not state is `null` and the budget `unknown` ("no limit known") — a partial mass sum is
a lower bound, so it is `exceeded` when already over and `unknown` otherwise. Mass and cost
limits come from a quantified `ConstraintMeta` (`quantity` = `mass` / `cost`, an upper-bound
comparator) on any live constraints entry; power limits are the supplies' ratings.

Stored as the ONE `constraints/budgets` CONFIG (bound to the cell's `solus_subsection` node,
so it never counts toward the section cap). Over limit → `raise_finding(budget_exceeded)`,
idempotent on a repeat (count += 1); a later green pass never resolves it — that is a
person's act. Triggered by `LiveHub.on_graph_changed` (resolution 18): debounced 5 s per
project, enqueued as the ARQ job `recompute_budgets` or run inline without Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import ValidationError
from solus_contracts.relations import RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.checkers.interface import Severity
from solus_api.graph import kinds
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    utcnow,
)
from solus_api.services.solus_config import find_config_entry, put_config_entry
from solus_api.services.solus_graph import SolusGraph
from solus_api.services.solus_payloads import BudgetLine, Budgets, BudgetStatus, ConstraintMeta

logger = logging.getLogger("solus.services.budgets")

RULE_ID: Final = "budget_exceeded"
BUDGETS_SUBSECTION: Final = "budgets"
DEBOUNCE_SECONDS: Final = 5.0
JOB_NAME: Final = "recompute_budgets"
MASS_KINDS: Final = (kinds.PART, kinds.COMPONENT)
#: Entity attrs the graph already carries (checkers/attributes.py, sourcing/service.py).
DRAW_ATTRS: Final = ("current_draw_a",)
RATING_ATTRS: Final = ("current_max_a",)
MASS_ATTRS_KG: Final = ("mass_kg", "weight_kg", "mass")
_UPPER_BOUNDS: Final = frozenset({"<", "<="})
_MASS_UNITS_KG: Final = {"kg": 1.0, "g": 0.001}
_DOMAIN_OF: Final = {"mass": Domain.MECHANICAL, "cost": Domain.PROJECT}
#: A net name as a finding headline may carry it; anything else (schematic text is
#: untrusted connector content) is named by its hash instead.
_SAFE_NET_RE: Final = re.compile(r"^[A-Za-z0-9_+\-./]{1,64}$")


def _safe_net_name(net: str) -> str:
    if _SAFE_NET_RE.match(net):
        return net
    return "net-" + hashlib.sha1(net.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def budget_job_id(project_id: str) -> str:
    """ARQ's dedupe key: one queued-or-running recompute per project across every API
    replica and the worker (each runs its own debounce)."""
    return f"{JOB_NAME}:{project_id}"


def _nonneg_number(value: object) -> float | None:
    """A finite, non-negative number from untrusted attrs; bool and NaN are not numbers."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _definition_of(entity: GraphEntity) -> Any | None:
    definition_id = entity.attrs.get("definition_id")
    if not isinstance(definition_id, str):
        return None
    from solus_api.hardware.library import DefinitionError, load_library

    try:
        return load_library().get("part", definition_id)
    except DefinitionError:
        return None


def _limit_of(
    entity: GraphEntity, limit_keys: tuple[str, ...], attr_keys: tuple[str, ...]
) -> float | None:
    """The first stated of the definition's `limits.<key>`s, else of the entity attrs."""
    limits = getattr(_definition_of(entity), "limits", None)
    for key in limit_keys:
        value = _nonneg_number(getattr(limits, key, None))
        if value is not None:
            return value
    for key in attr_keys:
        value = _nonneg_number(entity.attrs.get(key))
        if value is not None:
            return value
    return None


def _mass_kg_of(entity: GraphEntity) -> float | None:
    grams = _nonneg_number(getattr(_definition_of(entity), "mass_g", None))
    if grams is not None:
        return grams / 1000
    for key in MASS_ATTRS_KG:
        value = _nonneg_number(entity.attrs.get(key))
        if value is not None:
            return value
    return None


def _budget_status(
    current: float | None, limit: float | None, *, complete: bool = True
) -> BudgetStatus:
    if current is not None and limit is not None and current > limit:
        return "exceeded"
    if current is None or limit is None or not complete:
        return "unknown"
    return "ok"


def _round6(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _sum_known(values: list[float | None]) -> float | None:
    """The sum, or None when any member is unknown (a rail with one unknown sink has no total)."""
    if not values or any(v is None for v in values):
        return None
    return math.fsum(v for v in values if v is not None)


@dataclass
class _Rail:
    supplies: dict[uuid.UUID, GraphEntity] = field(default_factory=dict)
    sinks: dict[uuid.UUID, GraphEntity] = field(default_factory=dict)


async def _rails(session: AsyncSession, project_id: uuid.UUID) -> dict[str, _Rail]:
    edges = list(
        await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == RelationType.POWERS.value,
                GraphEdge.deleted_at.is_(None),
            )
        )
    )
    ids = {e.src_id for e in edges} | {e.dst_id for e in edges}
    entities: dict[uuid.UUID, GraphEntity] = {}
    if ids:
        entities = {
            row.id: row
            for row in await session.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(ids),
                    GraphEntity.deleted_at.is_(None),
                )
            )
        }
    rails: dict[str, _Rail] = defaultdict(_Rail)
    for edge in edges:
        supply, sink = entities.get(edge.src_id), entities.get(edge.dst_id)
        if supply is None or sink is None:
            continue
        nets = edge.attrs.get("nets")
        for net in nets if isinstance(nets, list) else []:
            if isinstance(net, str) and net:
                rails[net].supplies[supply.id] = supply
                rails[net].sinks[sink.id] = sink
    return dict(rails)


def _power_lines(rails: dict[str, _Rail]) -> list[tuple[BudgetLine, list[uuid.UUID]]]:
    lines = []
    for net in sorted(rails):
        rail = rails[net]
        current = _sum_known(
            [
                _limit_of(sink, ("current_a", "stall_current_a"), DRAW_ATTRS)
                for sink in rail.sinks.values()
            ]
        )
        limit = _sum_known(
            [_limit_of(supply, ("current_a",), RATING_ATTRS) for supply in rail.supplies.values()]
        )
        supplies = "supply" if len(rail.supplies) == 1 else "supplies"
        line = BudgetLine(
            name=f"power:{_safe_net_name(net)}",
            current=_round6(current),
            limit=_round6(limit),
            unit="A",
            source=f"powers edges · {len(rail.sinks)} sinks · {len(rail.supplies)} {supplies}",
            status=_budget_status(current, limit),
        )
        lines.append((line, sorted(rail.supplies, key=str)))
    return lines


async def _constraint_limit(
    session: AsyncSession, project_id: uuid.UUID, quantity: str, units: dict[str, float] | None
) -> tuple[float | None, str | None]:
    """The tightest upper bound a live constraints entry states for `quantity`, converted
    through `units` (None = any unit, reported as given)."""
    rows = await session.scalars(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == SolusSection.CONSTRAINTS,
            SolusEntry.kind.in_((SolusEntryKind.TEXT, SolusEntryKind.SOL)),
            SolusEntry.deleted_at.is_(None),
            SolusEntry.payload.is_not(None),
        )
    )
    best: tuple[float, str] | None = None
    for entry in rows:
        try:
            meta = ConstraintMeta.model_validate(entry.payload or {})
        except ValidationError:
            continue
        if meta.quantity is None or meta.quantity.strip().lower() != quantity:
            continue
        if meta.comparator not in _UPPER_BOUNDS or meta.limit is None:
            continue
        unit = (meta.unit or "").strip()
        factor = 1.0 if units is None else units.get(unit.lower())
        if factor is None:
            continue
        value = meta.limit * factor
        if best is None or value < best[0]:
            best = (value, unit if units is None else "kg")
    return (best[0], best[1]) if best is not None else (None, None)


async def _mass_line(session: AsyncSession, project_id: uuid.UUID) -> BudgetLine:
    parts = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind.in_(MASS_KINDS),
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    known = [m for m in (_mass_kg_of(p) for p in parts) if m is not None]
    current = math.fsum(known) if known else None
    limit, _ = await _constraint_limit(session, project_id, "mass", _MASS_UNITS_KG)
    return BudgetLine(
        name="mass",
        current=_round6(current),
        limit=_round6(limit),
        unit="kg",
        source=f"part definitions · attrs · {len(known)} of {len(parts)} parts massed",
        status=_budget_status(current, limit, complete=len(known) == len(parts)),
    )


async def _cost_line(session: AsyncSession, project_id: uuid.UUID) -> BudgetLine:
    from solus_api.widgets.bom.rows import totals  # the widget imports services; lazy
    from solus_api.widgets.bom.service import load_config, load_inputs

    inputs = await load_inputs(session, project_id)
    config = await load_config(session, project_id, None)
    summary = totals(inputs.rows(), config.cost_target)
    priced, rows = int(summary["priced_rows"]), int(summary["rows"])
    current = float(summary["line_cost_total"]) if priced else None
    limit, unit = await _constraint_limit(session, project_id, "cost", None)
    return BudgetLine(
        name="cost",
        current=_round6(current),
        limit=_round6(limit),
        unit=(unit or config.currency)[:16],
        source=f"BOM totals · {priced} of {rows} rows priced",
        status=_budget_status(current, limit, complete=priced == rows and not inputs.truncated),
    )


async def compute_budgets(session: AsyncSession, project_id: uuid.UUID) -> Budgets:
    power = [line for line, _ in _power_lines(await _rails(session, project_id))]
    mass, cost = await _mass_line(session, project_id), await _cost_line(session, project_id)
    return Budgets(computed_at=utcnow(), budgets=[*power, mass, cost])


async def _raise_exceeded(
    session: AsyncSession,
    project_id: uuid.UUID,
    line: BudgetLine,
    subjects: list[uuid.UUID],
    domain: Domain,
) -> None:
    await raise_finding(
        session,
        project_id,
        FindingSpec(
            rule_id=RULE_ID,
            severity=Severity.CRITICAL,
            source="checker",
            headline=(
                f"{line.name} budget exceeded: {line.current:g} {line.unit} "
                f"over a limit of {line.limit:g} {line.unit}"
            ),
            subjects=subjects,
            evidence={"budget": line.model_dump(mode="json")},
            domain=domain,
            bucket=line.name,
        ),
    )


async def store_budgets(session: AsyncSession, project_id: uuid.UUID) -> SolusEntry:
    """Compute, store the ONE `constraints/budgets` CONFIG (same id each time; a version
    only when a value changed) and raise a finding per exceeded budget. The caller commits."""
    graph = await SolusGraph.ensure(session, project_id)  # holds the project lock
    power = _power_lines(await _rails(session, project_id))
    mass, cost = await _mass_line(session, project_id), await _cost_line(session, project_id)
    doc = Budgets(computed_at=utcnow(), budgets=[*(line for line, _ in power), mass, cost])
    for line, supplies in power:
        if line.status == "exceeded":
            await _raise_exceeded(session, project_id, line, supplies, Domain.ELECTRICAL)
    for line in (mass, cost):
        if line.status == "exceeded":
            await _raise_exceeded(session, project_id, line, [graph.root.id], _DOMAIN_OF[line.name])
    subject = graph.subsection_node(SolusSection.CONSTRAINTS, BUDGETS_SUBSECTION)
    entry = await put_config_entry(
        session,
        project_id,
        SolusSection.CONSTRAINTS,
        BUDGETS_SUBSECTION,
        doc,
        text="Budgets",
        configured_entity_id=subject.id,
        created_by=None,
        author="system",
        ignore=("computed_at",),
    )
    logger.info(
        "budgets project=%s %s", project_id, " ".join(f"{b.name}={b.status}" for b in doc.budgets)
    )
    return entry


async def find_budgets_entry(session: AsyncSession, project_id: uuid.UUID) -> SolusEntry | None:
    return await find_config_entry(
        session, project_id, SolusSection.CONSTRAINTS, BUDGETS_SUBSECTION, any_subject=True
    )


async def recompute_budgets(ctx: dict[str, Any], project_id: str) -> None:
    """The ARQ job (also the inline path): one project, own session, committed. A project
    that vanished is logged; a malformed id is the caller's bug and raises."""
    key = uuid.UUID(project_id)
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        try:
            await store_budgets(session, key)
            await session.commit()
        except Exception:  # noqa: BLE001 — a derived document must never poison the worker
            await session.rollback()
            logger.exception("budget recompute failed project=%s", key)


class BudgetTrigger:
    """Debounced per-project recompute: one timer per project, the last write wins, a
    failed run is logged. `run` is whatever the host does with the project id."""

    def __init__(self, run: Callable[[uuid.UUID], Awaitable[None]], *, delay: float) -> None:
        self._run = run
        self._delay = delay
        self._timers: dict[uuid.UUID, asyncio.Task[None]] = {}

    async def __call__(self, project_id: uuid.UUID) -> None:
        previous = self._timers.pop(project_id, None)
        if previous is not None:
            previous.cancel()
        self._timers[project_id] = asyncio.create_task(self._later(project_id))

    async def _later(self, project_id: uuid.UUID) -> None:
        try:
            await asyncio.sleep(self._delay)
            await self._run(project_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the hub's publish must never see this
            logger.exception("budget trigger failed project=%s", project_id)
        finally:
            if self._timers.get(project_id) is asyncio.current_task():
                self._timers.pop(project_id, None)

    def close(self) -> None:
        for task in self._timers.values():
            task.cancel()
        self._timers.clear()


def make_budget_trigger(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    enqueue: Callable[[str, str], Awaitable[Any]] | None,
    delay: float | None = None,
) -> BudgetTrigger:
    """The `LiveHub.on_graph_changed` callback: enqueue `recompute_budgets` by name when a
    queue is available (`enqueue(job_name, project_id)`), else run it inline."""

    async def run(project_id: uuid.UUID) -> None:
        if enqueue is not None:
            await enqueue(JOB_NAME, str(project_id))
        else:
            await recompute_budgets({"sessionmaker": sessionmaker}, str(project_id))

    return BudgetTrigger(run, delay=DEBOUNCE_SECONDS if delay is None else delay)
