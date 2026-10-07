"""Cross-domain linking — SAME_AS edges from the W0-06 fingerprint contract (SOLUS-LNK-01/02).

Materializes cross-tool identity in the graph: for each `CanonicalPart`, the
observations that matched it become pairwise `same_as` graph_edges carrying
`domain_pair` + honest confidence. `link()` and everything below it consume
ONLY `fingerprint.contract` shapes — the mock-and-swap seam. The data SOURCES
sit above that boundary: `link_from_mock` (LNK-01, the committed W0-06 mock)
and `link_from_fingerprint` (LNK-02, the real gather → pure matcher pipeline).
The swap changed only that boundary — matcher imports appear only in the
source function, never in the linker core.

Conflicts (LNK-02): when different canonical parts claim the same entity pair,
confidence decides; an exact tie is flagged in `LinkResult.ties` and the pair
is left un-edged (an existing linker edge for it is retracted) — ties are
flagged, never guessed.

Precision posture (mirrors FP-02, ADR-012): an edge's confidence is the weakest
link of its pair, capped by the part's own belief — a LOW_CONFIDENCE observation
yields a low-confidence edge (`attrs["matched"] = False`), never a promoted
certainty. Ambiguous observations are counted and left un-edged. Resolution is
WRITE-SAFE by default: a stale `graph_entity_id` refuses rather than falling
back to the (connector, external_ref) pair, because the pair could land on a
re-synced, physically different component (the same rule FP-02's write path
enforces). Only the mock path opts into the fallback — its ids are fixtures.

Ownership: linker edges are `origin="linking"`, `source_id` NULL. Retraction
soft-deletes only linker-owned rows — connector-owned and manual edges are never
modified (the connector runtime's reconciliation likewise ignores source-less
edges, so each writer owns exactly its own rows).

Concurrency & idempotency: every write path — including the real-pipeline
GATHER, which must see the same snapshot it writes from — runs under the same
per-project advisory lock as fingerprint ingestion, so linker and scanner
serialize on one project's graph. `uq_graph_edge_source_edge` includes the NULL
`source_id`, and Postgres treats NULLs as distinct, so there is NO DB unique
backstop for linker edges — the advisory lock is the idempotency guarantee.
Resolution is batched (two queries per run, not per observation), and pairing
is bounded per part so connector-influenced hints cannot mint O(n²) edges.
# ponytail: lock-only idempotency; a LANE 0 partial unique index on
# (project_id, src_id, dst_id, relation_type) WHERE source_id IS NULL is the
# flagged follow-up backstop.
"""

import dataclasses
import itertools
import logging
import uuid
from pathlib import Path

from sqlalchemy import Text, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.fingerprint.config import FingerprintConfig, default_fingerprint_config
from solus_api.fingerprint.contract import (
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    SourceRef,
    load_mock_output,
)
from solus_api.fingerprint.matcher import match, observations_from_hints
from solus_api.graph.read_scope import GraphReadScope
from solus_api.models import GraphEdge, GraphEntity, utcnow

logger = logging.getLogger(__name__)

#: `graph_edge.relation_type` for cross-domain identity (the model docstring's
#: blessed value); `origin` marking linker ownership.
RELATION_SAME_AS = "same_as"
LINK_ORIGIN = "linking"

#: Pairing bound per part: modality hints are connector-ingested, attacker-
#: influenceable data, and pairwise linking is O(n²) — a crafted part claiming
#: hundreds of entities must not mint hundreds of thousands of edges. 64
#: observations → at most 2,016 edges per part; the excess is dropped
#: deterministically (contract order) and surfaced via `LinkResult.capped_parts`.
# ponytail: flat cap; per-part confidence-ranked selection if a legitimate
# >64-instance part ever shows up.
MAX_LINKED_OBSERVATIONS_PER_PART = 64


@dataclasses.dataclass(frozen=True)
class LinkResult:
    """Per-run outcome. `created`/`updated`/`retracted` are write counts — an
    idempotent re-link of unchanged output reports all three as zero, while
    `unresolved`/`ambiguous`/`ties`/`capped_parts` restate properties of the
    input and recur on every run over the same output."""

    created: int = 0
    updated: int = 0
    retracted: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    low_confidence_edges: int = 0
    ties: int = 0
    capped_parts: int = 0


@dataclasses.dataclass(frozen=True)
class _Support:
    """The best evidence behind one entity pair: weakest-link confidence and
    whether both observations were MATCHED (vs. carried a fingerprint doubt)."""

    confidence: float
    matched: bool
    canonical_id: uuid.UUID
    part_number: str | None
    modalities: tuple[str, str]


async def _acquire_project_lock(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The per-project advisory lock fingerprint ingestion uses — one key, so
    linker and scanner serialize. Transaction-scoped and reentrant, so a source
    function may take it before its gather and `link()` retakes it harmlessly."""
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(project_id), 0)))
    )


_Pair = tuple[str | None, str | None]


async def _lookup_pairs(
    session: AsyncSession, project_id: uuid.UUID, pairs: set[_Pair]
) -> dict[_Pair, GraphEntity | None]:
    """One query for every wanted (connector, external_ref); ambiguous
    provenance (two live rows sharing a pair) is refused, never guessed."""
    by_pair: dict[_Pair, GraphEntity | None] = {}
    if not pairs:
        return by_pair
    rows = (
        await session.scalars(
            select(GraphEntity).where(
                GraphReadScope(project_id).entity_predicate(),
                GraphEntity.deleted_at.is_(None),
                tuple_(GraphEntity.source_connector, GraphEntity.external_ref).in_(pairs),
            )
        )
    ).all()
    grouped: dict[_Pair, list[GraphEntity]] = {}
    for row in rows:
        grouped.setdefault((row.source_connector, row.external_ref), []).append(row)
    for pair, matches in grouped.items():
        if len(matches) == 1:
            by_pair[pair] = matches[0]
        else:
            logger.warning(
                "linking: ambiguous provenance for (%s, %s) — refused, never guessed",
                pair[0],
                pair[1],
            )
            by_pair[pair] = None
    return by_pair


async def _resolve_all(
    session: AsyncSession,
    output: FingerprintOutput,
    project_id: uuid.UUID,
    *,
    pair_fallback_after_id_miss: bool,
) -> dict[SourceRef, GraphEntity | None]:
    """Batch-resolve every observation ref: one id query + one pair query.

    Semantics mirror fingerprint ingest's resolver (duplicated on purpose — the
    seam forbids importing it): project-scoped, live rows only, ambiguous
    (connector, external_ref) provenance refused. A ref whose id misses falls
    back to the pair ONLY when `pair_fallback_after_id_miss` — the write-safe
    default refuses, since the pair could be a re-synced different component.
    """
    refs: list[SourceRef] = []
    seen: set[SourceRef] = set()
    for part in output.canonical_parts:
        for mod_match in part.modalities:
            if mod_match.source_ref not in seen:
                seen.add(mod_match.source_ref)
                refs.append(mod_match.source_ref)

    ids = {ref.graph_entity_id for ref in refs if ref.graph_entity_id is not None}
    by_id: dict[uuid.UUID, GraphEntity] = {}
    if ids:
        rows = (
            await session.scalars(
                select(GraphEntity).where(
                    GraphReadScope(project_id).entity_predicate(),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.id.in_(ids),
                )
            )
        ).all()
        by_id = {row.id: row for row in rows}

    def _pair_allowed(ref: SourceRef) -> bool:
        if not (ref.source_connector and ref.external_ref):
            return False
        if ref.graph_entity_id is None:
            return True
        return ref.graph_entity_id not in by_id and pair_fallback_after_id_miss

    pairs = {(ref.source_connector, ref.external_ref) for ref in refs if _pair_allowed(ref)}
    by_pair = await _lookup_pairs(session, project_id, pairs)

    resolved: dict[SourceRef, GraphEntity | None] = {}
    for ref in refs:
        row = by_id.get(ref.graph_entity_id) if ref.graph_entity_id is not None else None
        if row is None and _pair_allowed(ref):
            row = by_pair.get((ref.source_connector, ref.external_ref))
        resolved[ref] = row
    return resolved


_PairMap = dict[tuple[uuid.UUID, uuid.UUID], _Support]


_Observation = tuple[float, MatchState, str, GraphEntity]


def _part_observations(
    part: CanonicalPart, resolved: dict[SourceRef, GraphEntity | None]
) -> tuple[list[_Observation], int, bool]:
    """One part's resolvable observations, fan-out-capped: (kept, unresolved, capped)."""
    observations: list[_Observation] = []
    unresolved = 0
    for mod_match in part.modalities:
        row = resolved.get(mod_match.source_ref)
        if row is None:
            unresolved += 1
            continue
        observations.append((mod_match.confidence, mod_match.state, mod_match.modality.value, row))
    capped = len(observations) > MAX_LINKED_OBSERVATIONS_PER_PART
    if capped:
        logger.warning(
            "linking: part %s claims %d observations — pairing capped at %d",
            part.canonical_id,
            len(observations),
            MAX_LINKED_OBSERVATIONS_PER_PART,
        )
        observations = observations[:MAX_LINKED_OBSERVATIONS_PER_PART]
    return observations, unresolved, capped


def _collect_supports(
    output: FingerprintOutput, resolved: dict[SourceRef, GraphEntity | None]
) -> tuple[_PairMap, dict[uuid.UUID, GraphEntity], int, int, int]:
    """Fold resolved observations into best-support pairs (pure, no I/O).

    Conflict handling: confidence decides between competing canonical parts; an
    exact (confidence, matched) tie between DIFFERENT parts marks the pair
    contested — contested pairs are dropped from the result and counted, never
    guessed. A strictly better later support clears the contest.
    """
    desired: _PairMap = {}
    contested: set[tuple[uuid.UUID, uuid.UUID]] = set()
    entities: dict[uuid.UUID, GraphEntity] = {}
    unresolved = 0
    capped_parts = 0
    for part in output.canonical_parts:
        observations, part_unresolved, capped = _part_observations(part, resolved)
        unresolved += part_unresolved
        capped_parts += int(capped)
        for (conf_a, state_a, mod_a, ent_a), (
            conf_b,
            state_b,
            mod_b,
            ent_b,
        ) in itertools.combinations(observations, 2):
            if ent_a.id == ent_b.id:
                continue  # two modalities on one entity need no self-link
            src, dst = (ent_a, ent_b) if ent_a.id < ent_b.id else (ent_b, ent_a)
            support = _Support(
                confidence=min(part.confidence, conf_a, conf_b),
                matched=state_a is MatchState.MATCHED and state_b is MatchState.MATCHED,
                canonical_id=part.canonical_id,
                part_number=part.part_number,
                modalities=(mod_a, mod_b),
            )
            key = (src.id, dst.id)
            entities[src.id], entities[dst.id] = src, dst
            current = desired.get(key)
            if current is None:
                desired[key] = support
                continue
            new_rank = (support.confidence, support.matched)
            cur_rank = (current.confidence, current.matched)
            if new_rank > cur_rank:
                desired[key] = support
                contested.discard(key)  # confidence decided; the contest is over
            elif new_rank == cur_rank and support.canonical_id != current.canonical_id:
                contested.add(key)
    for key in contested:
        desired.pop(key, None)
    return desired, entities, unresolved, len(contested), capped_parts


async def link(
    session: AsyncSession,
    output: FingerprintOutput,
    *,
    project_id: uuid.UUID,
    pair_fallback_after_id_miss: bool = False,
) -> LinkResult:
    """Reconcile the project's linker-owned same_as edges to `output`.

    Flushes but never commits — the caller owns the transaction (house rule,
    same as fingerprint ingest).
    """
    await _acquire_project_lock(session, project_id)
    resolved = await _resolve_all(
        session, output, project_id, pair_fallback_after_id_miss=pair_fallback_after_id_miss
    )
    desired, entities, unresolved, ties, capped_parts = _collect_supports(output, resolved)

    # NOT `edge_predicate()`: that hides edges whose endpoint is soft-deleted, so a
    # linker edge to a part a re-sync just removed would never be retracted and would
    # stay live forever, dangling. Linker-owned edges are project-scoped by id alone.
    live = (
        (
            await session.execute(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.origin == LINK_ORIGIN,
                    GraphEdge.relation_type == RELATION_SAME_AS,
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    existing = {(row.src_id, row.dst_id): row for row in live}

    created = updated = retracted = low_confidence = 0
    for (src_id, dst_id), support in desired.items():
        domain_pair = f"{entities[src_id].domain.value}<->{entities[dst_id].domain.value}"
        attrs = {
            "canonical_id": str(support.canonical_id),
            "part_number": support.part_number,
            "modalities": sorted(support.modalities),
            "matched": support.matched,
        }
        row = existing.pop((src_id, dst_id), None)
        if row is None:
            # A previously retracted pair that reappears gets a fresh row; the
            # tombstone stays as history (mirrors connector reconciliation).
            session.add(
                GraphEdge(
                    project_id=project_id,
                    src_id=src_id,
                    dst_id=dst_id,
                    relation_type=RELATION_SAME_AS,
                    domain_pair=domain_pair,
                    confidence=support.confidence,
                    origin=LINK_ORIGIN,
                    attrs=attrs,
                )
            )
            created += 1
            if not support.matched:
                low_confidence += 1
        elif (
            row.confidence != support.confidence
            or row.domain_pair != domain_pair
            or row.attrs != attrs
        ):
            row.confidence = support.confidence
            row.domain_pair = domain_pair
            row.attrs = attrs  # new dict, never mutated in place (JSONB change detection)
            updated += 1
            if not support.matched:
                low_confidence += 1

    for row in existing.values():
        row.deleted_at = utcnow()
        retracted += 1

    await session.flush()
    return LinkResult(
        created=created,
        updated=updated,
        retracted=retracted,
        unresolved=unresolved,
        ambiguous=len(output.ambiguous),
        low_confidence_edges=low_confidence,
        ties=ties,
        capped_parts=capped_parts,
    )


async def link_from_mock(
    session: AsyncSession, *, project_id: uuid.UUID, path: Path | None = None
) -> LinkResult:
    """LNK-01 data source: the committed W0-06 mock. LNK-02 replaces this loader
    with the real fingerprint output behind the same contract — linker logic
    below this boundary must not change for the swap. The mock's entity ids are
    fixtures, so this path opts into the (connector, external_ref) fallback."""
    return await link(
        session, load_mock_output(path), project_id=project_id, pair_fallback_after_id_miss=True
    )


async def link_from_fingerprint(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    config: FingerprintConfig | None = None,
) -> LinkResult:
    """LNK-02 data source: the real fingerprint pipeline (gather → pure matcher).

    Takes the project lock BEFORE gathering — the gather, match, and write must
    see one snapshot, exactly as `scan_project` locks before its gather; a
    stale-snapshot writer would retract edges a fresher run just asserted. The
    lock is transaction-scoped and reentrant, so `link()` retaking it is free.
    Gathers the same modality-hint observations `scan_project` gathers and feeds
    the SAME `link()` the mock path uses — the swap changes only this boundary.
    # ponytail: the gather loop mirrors scan_project's inline gather verbatim
    # (fingerprint/ is @shared, not lane-editable); extracting one shared public
    # gather is a flagged LANE 0 follow-up so the two cannot drift.
    """
    await _acquire_project_lock(session, project_id)
    rows = (
        await session.scalars(
            select(GraphEntity)
            .where(
                GraphReadScope(project_id).entity_predicate(),
                GraphEntity.deleted_at.is_(None),
                GraphEntity.modality_hints.cast(Text) != "{}",
            )
            .order_by(GraphEntity.id)
        )
    ).all()
    observations = []
    for row in rows:
        ref = SourceRef(
            graph_entity_id=row.id,
            source_connector=row.source_connector,
            external_ref=row.external_ref,
        )
        footprint = row.attrs.get("footprint")
        observations.extend(
            observations_from_hints(
                ref,
                row.modality_hints,
                manufacturer=None,  # no connector sources manufacturer yet — never invented
                footprint=footprint if isinstance(footprint, str) else None,
            )
        )
    output = match(observations, config=config or default_fingerprint_config())
    return await link(session, output, project_id=project_id)
