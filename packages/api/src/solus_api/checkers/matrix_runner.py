"""SOLUSDEV-321 P3-T3 — the matrix run: every registered rule (`checkers/cells`) over ONE bounded
read of a project, and its results kept where people see them (docs/api/findings.md §5,
docs/api/relations.md §2).

- **The read** (`_project_graph`, the run's only graph read): the project's live entities — no
  finding, nothing of the workspace layer — at most `MAX_MATRIX_ENTITIES`, and the live edges of
  the relations a rule declares (`RUN_RELATIONS`), at most `MAX_EDGE_SCAN`, both under the bound
  read scope and through `to_graph_context`, so no candidate edge reaches a rule. A second read of
  its own holds the schematic's `connected_to` edges, at most `MAX_EDGE_SCAN` (R74). They are the
  netlist membership the motifs and an input's RC come from, and they are never annotated. A cap
  that binds is logged and the report says `truncated`.
- **The facts**: ONE `FactStore` built from that graph, unless the caller passes its own.
- **The judgement** (`judge_matrix`, pure): each requested cell's rules, through `results()`.
- **The ladder** (P4-T5, R97): the run's `inconclusive` results that state a band's quantity
  (R94), at most `MAX_LADDER_RESULTS`, go to `should_simulate` as `rule`, over `ladder_context`.
  Its proposals are data on the report and a count in the log line, a dry run's too. Nothing runs
  from a run: SOL's `simulate` acts on a proposal inside a turn.
- **What is kept**, unless `dry_run` or the caller's own facts (P4's backward loop):
  - each edge's results, through `annotate_edge`, one write per edge whose list changes;
  - each `fail` as a checker finding, unless its rule's `raises_findings` is False;
  - each fact the project lacks as ONE standing `info` per (rule, entity), whose `count` grows with
    each run that still lacks it. The entity is the result's first subject, or each of the
    project's robots for a fact the whole project lacks (with no robot, a line of the report);
  - the resolution of such an info (`resolve_system_finding`) once a run has judged its entity
    under that rule with every fact stated. A run that did not judge it — a cap bound, the edge is
    gone — resolves nothing;
  - each netlist motif on its members' `attrs.motifs` (R57, through `write_motifs`). A model's
    labels (`attrs.motif_labels`) are another key, which the run never rewrites.

The run never publishes `graph.changed` (it would wake the trigger that runs it), never calls a
model and names no vendor or connector. Flushes, never commits.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Any, Final, NamedTuple
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import case, or_, select
from sqlalchemy.orm import defer

from solus_api.billing.development import SESSION_SETTINGS_KEY
from solus_api.checkers.attributes import CONNECTED_TO
from solus_api.checkers.cells import MATRIX_RULES, RELATION_SOURCES, RULES_BY_ID
from solus_api.checkers.checker_results import CheckerResult
from solus_api.checkers.environment import REQUIREMENT_KIND
from solus_api.checkers.fact_store import build_fact_store
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.checkers.netlist_motifs import (
    MOTIFS_KEY,
    NetMotif,
    motif_entries,
    write_motifs,
)
from solus_api.checkers.traversal import GraphView
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import annotate_edge
from solus_api.graph.findings import (
    FindingSpec,
    finding_from_warning,
    raise_finding,
    resolve_system_finding,
)
from solus_api.graph.neighborhood import MAX_EDGE_SCAN, Neighborhood, to_graph_context
from solus_api.graph.read_scope import GraphReadScope, bind_scope, current_scope
from solus_api.models import Domain, GraphEdge, GraphEntity, Source, utcnow
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.sim_ladder import jobs_queued, ladder_context, should_simulate

if TYPE_CHECKING:
    from solus_contracts.relations import MatrixCell
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.agent.interfaces import EntityRead, GraphContext
    from solus_api.checkers.fact_store import FactStore
    from solus_api.checkers.interface import Warning
    from solus_api.simulation.sim_ladder import SimProposal

logger = logging.getLogger("solus.checkers.matrix_runner")

#: The most entities one run reads (R65). The plan's large project (3,000) fits whole and the
#: edge cap binds first. ponytail: past it a run keeps the fact kinds, then the judged relations'
#: endpoints, then the nets (m6), then the oldest (logged, `truncated`). A project whose fact
#: kinds alone pass the cap needs a read per cell, the upgrade.
MAX_MATRIX_ENTITIES: Final = 5_000
#: What a rule or the fact store reads off entities of these kinds: robots (runtime configs),
#: scene models (joints), components (board positions), requirements (pins). They load first (m8).
#: Nets load after the entities a judged relation touches: only the motifs read them (m6).
FACT_KINDS: Final = (
    kinds.PHYSICAL_ROBOT,
    kinds.BENCH_SCENE_MODEL,
    kinds.COMPONENT,
    REQUIREMENT_KIND,
)
#: The attrs key of a file the software reader found a policy or controller in (P6): such files
#: load with the fact kinds, so a large repository's other files never crowd them out.
MODULE_INTERFACES: Final = "module_interfaces"
#: The entities that hold their motifs (`attrs.motifs`): the schematic's components and nets.
MOTIF_HOLDERS: Final = frozenset({kinds.COMPONENT, kinds.NET})
#: The relations some rule reads (`needs.relations`): the only edges a run loads, so structure
#: (`contains`) and the findings' own `observed` edges never crowd `MAX_EDGE_SCAN`.
RUN_RELATIONS: Final = tuple(
    sorted(
        {rel for rules in MATRIX_RULES.values() for rule in rules for rel in rule.needs.relations}
    )
)
#: The sources a standing info's change signal names, at most.
MAX_SIGNAL_SOURCES: Final = 32
#: The items a list in a fail's evidence keeps, its full length beside it as `<key>_count`:
#: `FindingSpec` refuses evidence past 16 KiB, and a drift list can hold thousands (I3).
MAX_EVIDENCE_LIST: Final = 50
#: The `inconclusive` results stating a band's quantity that one run asks the ladder about (P4-T5):
#: each costs at most one provider's `can_answer`, a mesh read at worst. ponytail: the first in
#: registry order; past it, a run that wants the rest asks them when the first have settled.
MAX_LADDER_RESULTS: Final = 64
_RESOLVED: Final = "a matrix run judged it with every fact it needs stated"

type _Key = tuple[MatrixRule, UUID]


@dataclass(frozen=True, kw_only=True)
class MatrixReport:
    """What one run concluded, and what it wrote (all zero for a dry run)."""

    #: rule_id → its results; the requested cells' rules, in registry order.
    results: Mapping[str, tuple[RuleResult, ...]]
    #: Every `fail`, as the checker contract words it (`MatrixRule.warning`).
    warnings: tuple[Warning, ...]
    truncated: bool
    edges_annotated: int = 0
    #: Edges another writer held, left for the next run: a run never waits for an edge row (R68).
    edges_skipped: int = 0
    findings_raised: int = 0
    infos_raised: int = 0
    infos_resolved: int = 0
    #: Members whose `attrs.motifs` the run rewrote, and those another writer held (R57, R78).
    motifs_written: int = 0
    motifs_skipped: int = 0
    #: The unknowns no finding carries: a fact the whole project lacks, and no robot to anchor it.
    notes: tuple[str, ...] = ()
    #: What the ladder proposes for the run's `inconclusive` results (R97): data, never run. SOL's
    #: `simulate`, inside a turn, is the only executor.
    proposals: tuple[SimProposal, ...] = ()


def judge_matrix(
    graph: GraphContext, facts: FactStore, *, cells: set[MatrixCell] | None = None
) -> MatrixReport:
    """The requested cells' rules (every cell by default) over `graph` and `facts`, nothing
    written: what a run concludes, and all a dry run is (SOL's `run_checkers`, R64)."""
    view = GraphView(graph)
    rules = [
        rule
        for cell, of_cell in MATRIX_RULES.items()
        if cells is None or cell in cells
        for rule in of_cell
    ]
    results = {rule.rule_id: tuple(rule.results(graph, facts)) for rule in rules}
    warnings = tuple(
        rule.warning(view, result)
        for rule in rules
        for result in results[rule.rule_id]
        if result.status == "fail"
    )
    return MatrixReport(results=results, warnings=warnings, truncated=graph.truncated)


async def run_matrix(
    session: AsyncSession,
    project_id: UUID,
    *,
    cells: set[MatrixCell] | None = None,
    facts: FactStore | None = None,
    dry_run: bool = False,
) -> MatrixReport:
    """One run over the project: the module docstring says what it reads and what it keeps. A run
    that writes judges the project's shared view, whatever read scope its caller bound, since what
    it keeps is everyone's (m2). A dry run, or one given the caller's facts, reads the caller's."""
    writes = not dry_run and facts is None
    with bind_scope(GraphReadScope(project_id)) if writes else nullcontext():
        hood = await _project_graph(session, project_id)
        graph = to_graph_context(hood)
        store = facts if facts is not None else await build_fact_store(session, project_id, graph)
        judged_now = judge_matrix(graph, store, cells=cells)
        # Minor 7: a run given its caller's facts (a change's dry run) is judged and no more.
        proposals = (
            ()
            if facts is not None
            else _proposals(
                project_id,
                judged_now,
                graph,
                store,
                queued=jobs_queued(session.info.get(SESSION_SETTINGS_KEY)),
            )
        )
        report = replace(judged_now, proposals=proposals)
        if not writes:
            return report
        judged = [row for row in hood.edges if row.relation_type != CONNECTED_TO]
        return await _keep(session, project_id, judged, graph, report, store.motifs)


def _proposals(
    project_id: UUID, report: MatrixReport, graph: GraphContext, facts: FactStore, *, queued: bool
) -> tuple[SimProposal, ...]:
    """What the ladder proposes for the run's `inconclusive` results that state the band's
    quantity (R94, the only ones it reads), asked as `rule` (R97): it only proposes, so nothing
    runs from a run. At most `MAX_LADDER_RESULTS` are asked, each at most one provider's
    `can_answer`, so the job's time stays bounded; the cap is logged. `queued` is whether the
    deployment's job queue takes a rung-3 job, read as `simulate` reads it."""
    found = [
        result
        for results in report.results.values()
        for result in results
        if result.status == "inconclusive" and "quantity" in result.evidence
    ]
    if len(found) > MAX_LADDER_RESULTS:
        logger.warning(
            "matrix ladder capped project=%s inconclusive=%d (cap %d)",
            project_id,
            len(found),
            MAX_LADDER_RESULTS,
        )
    if not found:
        return ()
    context = ladder_context(graph, facts, queued=queued)
    return tuple(should_simulate(found[:MAX_LADDER_RESULTS], trigger="rule", context=context))


async def _project_graph(session: AsyncSession, project_id: UUID) -> Neighborhood:
    """The run's one read (the module docstring): rows, so each edge keeps its id for
    `annotate_edge`; `to_graph_context` makes them what a rule reads. Under the entity cap the
    fact kinds come first, then what a judged relation touches, then the nets, which only the
    motifs read (m6), then the rest, oldest first (m8)."""
    scope = current_scope(project_id)
    judged = (
        GraphEdge.project_id == project_id,
        GraphEdge.deleted_at.is_(None),
        GraphEdge.relation_type.in_(RUN_RELATIONS),
    )
    touched = or_(
        GraphEntity.id.in_(select(GraphEdge.src_id).where(*judged)),
        GraphEntity.id.in_(select(GraphEdge.dst_id).where(*judged)),
    )
    first = case(
        (GraphEntity.kind.in_(FACT_KINDS), 0),
        (GraphEntity.attrs.has_key(MODULE_INTERFACES), 0),  # P6: a file a module contract reads
        (touched, 1),
        (GraphEntity.kind == kinds.NET, 2),  # m6: only the motifs read nets, so they wait
        else_=3,
    )
    entities = list(
        await session.scalars(
            select(GraphEntity)
            .options(defer(GraphEntity.embedding, raiseload=True))
            .where(
                scope.entity_predicate(),
                GraphEntity.deleted_at.is_(None),
                GraphEntity.kind != kinds.FINDING,
                GraphEntity.domain != Domain.WORKSPACE,
            )
            .order_by(first, GraphEntity.created_at, GraphEntity.id)
            .limit(MAX_MATRIX_ENTITIES + 1)
        )
    )
    rows = list(
        await session.scalars(
            select(GraphEdge)
            .where(
                scope.edge_predicate(),
                GraphEdge.deleted_at.is_(None),
                GraphEdge.relation_type.in_(RUN_RELATIONS),
            )
            .order_by(GraphEdge.confidence.desc(), GraphEdge.created_at, GraphEdge.id)
            .limit(MAX_EDGE_SCAN + 1)
        )
    )
    netlist = await _netlist_rows(session, scope)
    kept = entities[:MAX_MATRIX_ENTITIES]
    ids = {entity.id for entity in kept}

    def within(read: Sequence[GraphEdge]) -> list[GraphEdge]:
        projected = (scope.project_edge(row) for row in read[:MAX_EDGE_SCAN])
        return [edge for edge in projected if edge.src_id in ids and edge.dst_id in ids]

    edges, pins = within(rows), within(netlist)
    truncated = len(entities) > len(kept) or max(len(rows), len(netlist)) > MAX_EDGE_SCAN
    if truncated:
        logger.warning(
            "matrix run capped project=%s entities=%d (cap %d) edges=%d (cap %d) "
            "netlist=%d (cap %d)",
            project_id,
            len(kept),
            MAX_MATRIX_ENTITIES,
            len(edges),
            MAX_EDGE_SCAN,
            len(pins),
            MAX_EDGE_SCAN,
        )
    return Neighborhood(entities=kept, edges=[*edges, *pins], truncated=truncated)


async def _keep(
    session: AsyncSession,
    project_id: UUID,
    rows: Sequence[GraphEdge],
    graph: GraphContext,
    report: MatrixReport,
    motifs: Sequence[NetMotif] = (),
) -> MatrixReport:
    """Write what the run concluded: the edges' results, then the findings, then the motifs on
    their members (R57).

    - The project lock comes first. The run never waits for an edge or entity row another writer
      holds: `annotate_edge` and `write_motifs` skip it (R68, R78).
    - A review action (project lock, then edge rows) therefore waits behind the run, and a sync
      (edge rows, then the project lock) waits at most one run. Neither deadlocks with it
      (I2, NB1).
    - The run's reads took no row lock. Both locks are held to the commit."""
    await lock_project(session, project_id)
    annotated, skipped = await _annotate_edges(session, project_id, rows, report)
    raised = await _raise_fails(session, project_id, report.warnings)
    unknown, judged, notes = _standing_infos(report, graph)
    rule_ids = {rule.rule_id for rule, _ in (*unknown, *judged)}
    standing = await _standing_rows(session, project_id, rule_ids)
    infos = await _raise_infos(session, project_id, unknown, graph, standing)
    resolved = await _resolve_infos(session, project_id, judged, standing)
    motifs_written, motifs_skipped = await _keep_motifs(session, project_id, graph, motifs)
    logger.info(
        "matrix run project=%s rules=%d annotated=%d skipped=%d raised=%d infos=%d resolved=%d "
        "motifs=%d notes=%d truncated=%s proposals=%d",
        project_id,
        len(report.results),
        annotated,
        skipped,
        raised,
        infos,
        resolved,
        motifs_written,
        len(notes),
        report.truncated,
        len(report.proposals),
    )
    return replace(
        report,
        edges_annotated=annotated,
        edges_skipped=skipped,
        findings_raised=raised,
        infos_raised=infos,
        infos_resolved=resolved,
        motifs_written=motifs_written,
        motifs_skipped=motifs_skipped,
        notes=notes,
    )


async def _keep_motifs(
    session: AsyncSession, project_id: UUID, graph: GraphContext, motifs: Sequence[NetMotif]
) -> tuple[int, int]:
    """Each motif on its members' `attrs.motifs` (R57), one write per net or component whose list
    moved; one that left every motif loses the key.

    - A model's labels (`attrs.motif_labels`) are never touched.
    - Nothing is published: a GraphEntity flush derives no live frame except a finding's, and the
      run holds no hub, so it never wakes its own trigger.
    - Returns the entities written and those skipped because another writer holds them.
    - A truncated run keeps none and clears none (m5): its read may hold half a net, so its
      motifs are not the netlist's. The members keep what the last whole run wrote."""
    if graph.truncated:
        logger.warning(
            "matrix motifs not kept: the run's read was truncated project=%s", project_id
        )
        return 0, 0
    wanted = motif_entries(motifs)
    written = skipped = 0
    for entity in graph.entities:
        entries = wanted.get(entity.id, [])
        if entity.kind not in MOTIF_HOLDERS or entity.attrs.get(MOTIFS_KEY, []) == entries:
            continue
        try:
            kept = await write_motifs(session, project_id, entity.id, entries)
        except APIError:  # deleted since the read: nothing to keep them on
            logger.warning("matrix motifs not kept project=%s entity=%s", project_id, entity.id)
            continue
        written, skipped = (written + 1, skipped) if kept is not None else (written, skipped + 1)
    if skipped:
        logger.warning(
            "matrix motifs not kept for %d entit(ies) another writer holds project=%s; "
            "kept at the next change",
            skipped,
            project_id,
        )
    return written, skipped


async def _netlist_rows(session: AsyncSession, scope: GraphReadScope) -> list[GraphEdge]:
    """The schematic's live `connected_to` edges under the bound scope, at most `MAX_EDGE_SCAN`
    + 1 (R74). They are the netlist membership the motifs and an input's RC are read from. The
    read is its own, so the netlist never crowds the judged edges out of theirs."""
    return list(
        await session.scalars(
            select(GraphEdge)
            .where(
                scope.edge_predicate(),
                GraphEdge.deleted_at.is_(None),
                GraphEdge.relation_type == CONNECTED_TO,
            )
            .order_by(GraphEdge.created_at, GraphEdge.id)
            .limit(MAX_EDGE_SCAN + 1)
        )
    )


async def _annotate_edges(
    session: AsyncSession, project_id: UUID, rows: Sequence[GraphEdge], report: MatrixReport
) -> tuple[int, int]:
    """Each loaded edge's results (docs/api/relations.md §2): one write per edge whose verdicts
    moved. Another rule's items stay; the rules this run ran rewrite their own. Returns the edges
    written, and those skipped because another writer holds them (judged at the next run)."""
    found = _checker_items(report)
    ran = set(report.results)
    written = skipped = 0
    for row in rows:
        old = row.attrs.get("checker_results")
        before = old if isinstance(old, list) else []
        ref = EdgeRef(row.src_id, row.dst_id, row.relation_type)
        items = [*_kept_items(before, ran), *_settled(before, found.get(ref, []))]
        if items == before:
            continue
        try:
            kept = await annotate_edge(session, project_id, row.id, checker_results=items)
        except APIError:  # retired since the read: nothing to keep the results on
            logger.warning("matrix results not kept project=%s edge=%s", project_id, row.id)
            continue
        written, skipped = (written + 1, skipped) if kept is not None else (written, skipped + 1)
    if skipped:
        logger.warning(
            "matrix results not kept for %d edge(s) another writer holds project=%s; "
            "judged at the next change",
            skipped,
            project_id,
        )
    return written, skipped


def _settled(before: Sequence[object], fresh: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """`fresh`, with each item that says what one of `before`'s said kept as that old item, its
    `at` included, so an edge whose verdicts did not move is not rewritten (m1)."""
    said = {_verdict(item): item for item in before if isinstance(item, dict)}
    return [said.get(_verdict(item), item) for item in fresh]


def _verdict(item: Mapping[str, Any]) -> str:
    """Everything an item says except when it said it, comparable across a JSON round trip."""
    return json.dumps({k: v for k, v in item.items() if k != "at"}, sort_keys=True, default=str)


def _checker_items(report: MatrixReport) -> dict[EdgeRef, list[dict[str, Any]]]:
    """Each judged edge's items, one per distinct (rule, status, message) — two rows of one
    relation are judged twice — all stamped with the run's one time."""
    at = utcnow()
    found: dict[EdgeRef, list[dict[str, Any]]] = {}
    seen: set[tuple[EdgeRef, str, str, str]] = set()
    for rule_id, results in report.results.items():
        for result in results:
            ref = result.edge_ref
            if ref is None or (ref, rule_id, result.status, result.message) in seen:
                continue
            seen.add((ref, rule_id, result.status, result.message))
            found.setdefault(ref, []).append(
                {
                    "rule_id": rule_id,
                    "status": result.status,
                    "severity": result.severity.value,
                    "message": result.message,
                    "evidence": dict(result.evidence),
                    "at": at,
                }
            )
    return found


def _kept_items(items: Sequence[object], ran: set[str]) -> list[dict[str, Any]]:
    """The items of the rules this run did not run that still read as items: one written before
    the item shape is dropped rather than refused by `annotate_edge` forever."""
    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("rule_id") in ran:
            continue
        try:
            CheckerResult.model_validate(item)
        except ValidationError:
            continue
        kept.append(item)
    return kept


async def _raise_fails(session: AsyncSession, project_id: UUID, warnings: Sequence[Warning]) -> int:
    """Each `fail` as a checker finding in its rule's cell, once a run. A rule whose
    `raises_findings` is False keeps it on the edge only, and a fail with no subject raises
    nothing (a finding needs one)."""
    raised = 0
    seen: set[tuple[str, tuple[UUID, ...]]] = set()
    for warning in warnings:
        rule = RULES_BY_ID[warning.checker_id]
        key = (warning.checker_id, tuple(sorted(warning.entity_ids)))  # one node, once a run (m5)
        if not rule.raises_findings or not warning.entity_ids or key in seen:
            continue
        seen.add(key)
        spec_of = partial(_fail_spec, rule, warning)
        raised += await _raised(session, project_id, spec_of, rule.rule_id, warning.entity_ids)
    return raised


def _fail_spec(rule: MatrixRule, warning: Warning) -> FindingSpec:
    """A fail as a checker finding in its rule's cell, with its evidence's lists trimmed."""
    bounded = warning.model_copy(update={"evidence": _trimmed(warning.evidence)})
    spec = finding_from_warning(bounded, source="checker")
    return spec.model_copy(update={"matrix_cell": rule.matrix_cell})


def _trimmed(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """`evidence` with each list in it, nested ones too, cut to its first `MAX_EVIDENCE_LIST`
    items, and its full length beside it as `<key>_count`."""
    trimmed: dict[str, Any] = {}
    for key, value in evidence.items():
        if isinstance(value, Mapping):
            trimmed[key] = _trimmed(value)
        elif isinstance(value, list) and len(value) > MAX_EVIDENCE_LIST:
            trimmed[key], trimmed[f"{key}_count"] = value[:MAX_EVIDENCE_LIST], len(value)
        else:
            trimmed[key] = value
    return trimmed


async def _raised(
    session: AsyncSession,
    project_id: UUID,
    spec_of: Callable[[], FindingSpec],
    rule_id: str,
    subjects: Sequence[UUID],
) -> int:
    """1 when the finding is raised; 0, logged, when its spec is refused (evidence or headline
    past `FindingSpec`'s bounds) or a subject has gone since the read. The spec is built here,
    inside the guard, and each raise has its own SAVEPOINT: one finding never fails the run, and
    a half-written one never outlives its error (I3)."""
    try:
        spec = spec_of()
        async with session.begin_nested():
            await raise_finding(session, project_id, spec)
    except (ValidationError, APIError):
        logger.warning(
            "matrix finding not raised project=%s rule=%s subjects=%s",
            project_id,
            rule_id,
            [str(subject) for subject in subjects],
            exc_info=True,
        )
        return 0
    return 1


def _standing_infos(
    report: MatrixReport, graph: GraphContext
) -> tuple[dict[_Key, list[RuleResult]], set[_Key], tuple[str, ...]]:
    """The (rule, entity) pairs the run could not judge for want of a fact, each with the results
    that say so: an edge's result is about its first subject, and a fact the whole project lacks
    is about each robot (R61), or a line of the report without one. On a truncated run a missing
    relation is a line of the report too, never an info: its edges may lie past the cap (m3).
    Then the pairs it judged with every fact stated, which an info may be resolved for (R63)."""
    robots = [entity.id for entity in graph.entities if entity.kind == kinds.PHYSICAL_ROBOT]
    unknown: dict[_Key, list[RuleResult]] = {}
    judged: set[_Key] = set()
    notes: list[str] = []
    for rule_id, results in report.results.items():
        rule = RULES_BY_ID[rule_id]
        whole, hidden = _project_wide(results, truncated=report.truncated)
        notes.extend(f"{r.message} (the run was capped: its edges may lie past it)" for r in hidden)
        anchored = [(r.subjects[0], r) for r in results if r.subjects]
        anchored += [(robot, r) for robot in robots for r in whole]
        for entity_id, result in anchored:
            if result.status == "unknown_input":
                unknown.setdefault((rule, entity_id), []).append(result)
            else:
                judged.add((rule, entity_id))
        if not whole and not hidden:
            judged.update((rule, robot) for robot in robots)
        elif not robots:
            notes.extend(r.message for r in whole)
    return unknown, judged.difference(unknown), tuple(notes)


def _project_wide(
    results: Sequence[RuleResult], *, truncated: bool
) -> tuple[list[RuleResult], list[RuleResult]]:
    """A rule's subject-less unknowns, split: those to anchor on each robot, and, on a truncated
    run, those naming a relation (`relation_gap`), whose edges the cap may have left out."""
    whole = [r for r in results if r.status == "unknown_input" and not r.subjects]
    hidden = [
        r
        for r in whole
        if truncated and r.missing is not None and r.missing.name in RELATION_SOURCES
    ]
    return [r for r in whole if r not in hidden], hidden


async def _raise_infos(
    session: AsyncSession,
    project_id: UUID,
    unknown: Mapping[_Key, Sequence[RuleResult]],
    graph: GraphContext,
    standing: Mapping[tuple[str, UUID], _Standing],
) -> int:
    """ONE standing info per (rule, entity) the run could not judge (R47), carrying the run's
    change signal. It is raised again only when that signal moved since its last raise (M110):
    its `count` counts the syncs that still lack the fact, and a run no sync caused publishes
    nothing."""
    if not unknown:
        return 0
    signal = await _source_times(session, project_id)
    entities = {entity.id: entity for entity in graph.entities}
    raised = 0
    for (rule, entity_id), found in unknown.items():
        entity, held = entities.get(entity_id), standing.get((rule.rule_id, entity_id))
        if entity is None or (held is not None and held.signal == signal):
            continue  # a subject outside the read, or nothing synced since its last raise
        spec_of = partial(_info_spec, rule, entity, found, signal)
        raised += await _raised(session, project_id, spec_of, rule.rule_id, (entity_id,))
    return raised


def _info_spec(
    rule: MatrixRule,
    entity: EntityRead,
    found: Sequence[RuleResult],
    signal: Mapping[str, str | None],
) -> FindingSpec:
    """The standing info: its headline names the first missing fact, and its evidence lists each
    one with where a person states it, how many edge results lacked them, and the signal."""
    needs = list(dict.fromkeys(result.missing for result in found if result.missing is not None))
    first = needs[0]
    return FindingSpec(
        rule_id=rule.rule_id,
        severity=Severity.INFO,
        source="checker",
        headline=(
            f"could not check {rule.rule_id}: {first.name} unknown for {entity.name}; "
            f"set it in {first.set_in}"
        ),
        subjects=[entity.id],
        evidence={
            "missing": [need.model_dump() for need in needs],
            "edges": sum(result.edge_ref is not None for result in found),
            "signal": dict(signal),
        },
        matrix_cell=rule.matrix_cell,
        domain=Domain(entity.domain),
    )


async def _source_times(session: AsyncSession, project_id: UUID) -> dict[str, str | None]:
    """The change signal (R47): when each of the project's sources last synced — the revision
    snapshot a `graph.changed`, which carries only the project id, stands for. Branch snapshots
    are left out, and at most `MAX_SIGNAL_SOURCES` are named."""
    rows = await session.execute(
        select(Source.id, Source.last_synced_at)
        .where(Source.project_id == project_id, Source.revision_base_source_id.is_(None))
        .order_by(Source.id)
        .limit(MAX_SIGNAL_SOURCES)
    )
    return {str(source_id): at.isoformat() if at else None for source_id, at in rows}


async def _resolve_infos(
    session: AsyncSession,
    project_id: UUID,
    judged: set[_Key],
    standing: Mapping[tuple[str, UUID], _Standing],
) -> int:
    """Resolve each standing info the run judged with every fact stated (R63), and no other."""
    wanted = {(rule.rule_id, entity_id) for rule, entity_id in judged}
    resolved = 0
    for pair, held in standing.items():
        if pair not in wanted:
            continue
        try:
            await resolve_system_finding(session, project_id, held.finding_id, reason=_RESOLVED)
        except APIError:  # deleted since the read
            logger.warning(
                "matrix info not resolved project=%s finding=%s", project_id, held.finding_id
            )
            continue
        resolved += 1
    return resolved


class _Standing(NamedTuple):
    """An unresolved standing info, and the change signal it was last raised under."""

    finding_id: UUID
    signal: object


async def _standing_rows(
    session: AsyncSession, project_id: UUID, rule_ids: set[str]
) -> dict[tuple[str, UUID], _Standing]:
    """The project's unresolved standing infos of these rules, by (rule, entity). A standing info
    is an `info` whose evidence carries `missing` (m4). Both are needed: a fail of the rule on that
    subject shares the node, and the evidence merge keeps the mark it raised over (NB2)."""
    if not rule_ids:
        return {}
    evidence = GraphEntity.attrs["evidence"]
    rows = await session.execute(
        select(
            GraphEntity.id,
            GraphEntity.attrs["rule_id"].astext,
            GraphEntity.attrs["subjects"],
            evidence["signal"],
        ).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.FINDING,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["source"].astext == "checker",
            GraphEntity.attrs["severity"].astext == Severity.INFO.value,
            evidence.has_key("missing"),
            GraphEntity.attrs["status"].astext != "resolved",
            GraphEntity.attrs["rule_id"].astext.in_(sorted(rule_ids)),
        )
    )
    return {
        (rule_id, UUID(subjects[0])): _Standing(finding_id, signal)
        for finding_id, rule_id, subjects, signal in rows
        if isinstance(subjects, list) and len(subjects) == 1
    }
