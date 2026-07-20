"""FP-02 fingerprint ingestion: matcher output → the graph (SOLUSDEV-59).

The graph is a SYSTEM OF RECORD: it records what we BELIEVE, not what we
SUSPECT. Persistence-layer precision rules (spec decisions, human-adjudicated
2026-07-12):

- Only a MATCHED observation gets `canonical_part_id` — the hard FK assertion.
  LOW_CONFIDENCE and AMBIGUOUS are auditable candidate evidence in the
  canonical entity's attrs; `unmatched` rows are left alone.
- Canonical entities are PROJECT-scoped, derived rows: `kind="canonical_part"`,
  `origin="fingerprint"`, `source_id`/`external_ref` NULL, idempotency keyed by
  the partial-unique `(project_id, canonical_key)` — the matcher's uuid5 is
  project-agnostic and lives in attrs for traceability only (uuid7 PK,
  ADR-027 untouched).
- Upsert is constraint-based, never check-then-write (cost.py pattern):
  INSERT .. ON CONFLICT DO NOTHING on the partial index, then
  SELECT .. FOR UPDATE and merge in Python (union-with-update evidence).
- CLEAR + STAMP, both directions: every FK this module sets is stamped on the
  observation (`attrs["fingerprint_link"]`); `scan_project` retracts stamped
  assertions the current run no longer supports; and an UNSTAMPED FK
  (LNK-01/manual) is never overwritten OR cleared — human assertions survive
  every scan.
- Keyless-safe: no API key anywhere in this path. `embed` is an optional
  best-effort seam (None → `embedding` stays NULL, nothing raises, match
  outcomes unaffected); the provider-backed implementation is proposed as an
  MO-01 gateway extension (docs/api/gateway-embeddings.md), never a
  second provider stack.

Concurrency: `scan_project` takes a per-project Postgres advisory lock
(transaction-scoped), so concurrent scans of one project serialize — two scans
matching different snapshots must not interleave FK writes/retractions. Row
iteration is id-ordered for deterministic lock acquisition. Bare `ingest()`
remains safe for the canonical row (unique index + row lock) but concurrent
bare use against one project's observations is last-writer-wins — hold the
same advisory lock if that matters to the caller.

The future trigger (Job + activity/data events + LLM escalation, all of which
need an authenticated user) attaches at a router mirroring
`routers/sources.py:trigger_sync` and dispatches `scan_project`; this module is
deliberately user-less and never commits — it flushes so its writes are visible
in-transaction, and the caller owns commit/rollback.
"""

import dataclasses
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Text, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.fingerprint.config import FingerprintConfig, default_fingerprint_config
from solus_api.fingerprint.contract import (
    AmbiguousObservation,
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    SourceRef,
)
from solus_api.fingerprint.matcher import match, observations_from_hints
from solus_api.models import EMBEDDING_DIM, Domain, GraphEntity, utcnow

logger = logging.getLogger(__name__)

EmbedFn = Callable[[str], Awaitable[list[float] | None]]

CANONICAL_KIND = "canonical_part"
CANONICAL_ORIGIN = "fingerprint"
_MAX_KEY_LEN = 64  # String(64) column; matches matching.yaml max_mpn_len
_STAMP_KEY = "fingerprint_link"
_INDEX_ELEMENTS = ["project_id", "canonical_key"]
_INDEX_PREDICATE = text("canonical_key IS NOT NULL AND deleted_at IS NULL")
# Bound the per-canonical evidence maps: modality_hints are untrusted connector
# data and must not grow a row without limit (CLAUDE.md §7 resource bounds).
_MAX_EVIDENCE_ENTRIES = 256


@dataclasses.dataclass(frozen=True)
class IngestResult:
    """Outcome of ingesting one CanonicalPart."""

    row: GraphEntity | None
    created: bool = False
    updated: bool = False
    linked: int = 0
    unresolved: int = 0
    skipped_unstamped: int = 0  # human/LNK-01 FKs we refused to overwrite
    embedded: bool = False


@dataclasses.dataclass(frozen=True)
class ScanSummary:
    """Outcome of one project scan (or one ingest_output call)."""

    observations: int = 0
    canonical_created: int = 0
    canonical_updated: int = 0
    canonical_staled: int = 0  # orphaned canonicals whose evidence was stale-marked
    linked: int = 0
    cleared: int = 0
    skipped_unstamped: int = 0
    low_confidence: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    unresolved_refs: int = 0
    embedded: int = 0


def _source_key(ref: SourceRef) -> str:
    """Stable per-observation key (mirrors the matcher's entity-key format).
    Known limit: two sources of one connector TYPE reusing an external_ref share
    a key (their FK links are already refused by the ambiguous-provenance rule;
    evidence provenance keeps the last writer's source_ref)."""
    if ref.source_connector and ref.external_ref:
        return f"{ref.source_connector}:{ref.external_ref}"
    return str(ref.graph_entity_id)


def _stable_view(attrs: dict[str, Any]) -> dict[str, Any]:
    """attrs with volatile timestamps stripped — the change-detection view, so
    an idempotent re-run leaves the row (and its version) completely untouched."""
    fingerprint = attrs.get("fingerprint")
    if not isinstance(fingerprint, dict):
        return attrs
    stable = {key: value for key, value in fingerprint.items() if key != "last_run_at"}
    for map_name in ("modalities", "ambiguous"):
        entries = fingerprint.get(map_name)
        if isinstance(entries, dict):
            stable[map_name] = {
                key: {k: v for k, v in entry.items() if k != "seen_at"}
                for key, entry in entries.items()
            }
    return {**attrs, "fingerprint": stable}


def _mark_unrefreshed_stale(
    entries: dict[str, dict[str, Any]], refreshed: set[str], now: str
) -> None:
    """RUN-SUPPORT staleness: a scan recomputes belief from the whole live
    project, so any entry the run did not re-derive is unsupported — mark it
    (never drop: provenance survives; the marker clears if re-derived later).
    This also covers a live observation that MOVED to another part."""
    for key, entry in entries.items():
        if key not in refreshed and entry.get("stale_at") is None:
            entry["stale_at"] = now


def _prune_entries(entries: dict[str, dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    """Resource bound: evict stale-oldest (then oldest) entries beyond the cap."""
    if len(entries) <= _MAX_EVIDENCE_ENTRIES:
        return entries
    ranked = sorted(
        entries.items(),
        key=lambda item: (item[1].get("stale_at") is None, str(item[1].get("seen_at") or "")),
    )
    evicted = len(entries) - _MAX_EVIDENCE_ENTRIES
    logger.warning("fingerprint attrs %s map over cap — evicting %d entries", label, evicted)
    return dict(ranked[evicted:])


def _merge_part_attrs(
    existing: dict[str, Any],
    part: CanonicalPart,
    now: str,
    *,
    complete_run: bool,
) -> dict[str, Any]:
    """Union-with-update merge of one part's evidence into canonical attrs.
    Pure: always returns new dicts, never mutates `existing`. Scalars reflect
    the latest run. Per-source evidence maps update seen keys and PRESERVE
    absent ones (a partial bare-ingest must not erase other sources' evidence);
    with `complete_run` (a full project scan) unrefreshed entries are
    stale-marked — the run is complete knowledge."""
    fingerprint = dict(existing.get("fingerprint") or {})
    modalities = {key: dict(entry) for key, entry in (fingerprint.get("modalities") or {}).items()}
    refreshed: set[str] = set()
    for modality_match in part.modalities:
        key = f"{modality_match.modality.value}:{_source_key(modality_match.source_ref)}"
        refreshed.add(key)
        modalities[key] = {
            "source_ref": modality_match.source_ref.model_dump(mode="json"),
            "confidence": modality_match.confidence,
            "state": modality_match.state.value,
            "evidence": dict(modality_match.evidence),
            "seen_at": now,
            "stale_at": None,
        }
    ambiguous = {key: dict(entry) for key, entry in (fingerprint.get("ambiguous") or {}).items()}
    if complete_run:
        _mark_unrefreshed_stale(modalities, refreshed, now)
        _mark_unrefreshed_stale(ambiguous, set(), now)  # refreshed later by ingest_output
    fingerprint.update(
        canonical_id=str(part.canonical_id),
        confidence=part.confidence,
        manufacturer=part.manufacturer,
        datasheet_ref=part.datasheet_ref,
        last_run_at=now,
        modalities=_prune_entries(modalities, "modalities"),
        ambiguous=_prune_entries(ambiguous, "ambiguous"),
    )
    return {**existing, "fingerprint": fingerprint}


def _merge_ambiguous_attrs(
    existing: dict[str, Any], observation: AmbiguousObservation, now: str
) -> dict[str, Any]:
    """Record one ambiguous observation as candidate evidence (no FK, ever)."""
    fingerprint = dict(existing.get("fingerprint") or {})
    ambiguous = {key: dict(entry) for key, entry in (fingerprint.get("ambiguous") or {}).items()}
    ambiguous[_source_key(observation.source_ref)] = {
        "source_ref": observation.source_ref.model_dump(mode="json"),
        "note": observation.note,
        "candidate_canonical_ids": [str(cid) for cid in observation.candidate_canonical_ids],
        "seen_at": now,
        "stale_at": None,
    }
    fingerprint["ambiguous"] = _prune_entries(ambiguous, "ambiguous")
    return {**existing, "fingerprint": fingerprint}


def _mark_all_stale(attrs: dict[str, Any], now: str) -> dict[str, Any]:
    """Stale-mark every evidence entry of a canonical that lost ALL support
    this run (it appeared in no matcher group, so nothing re-derived it)."""
    fingerprint = dict(attrs.get("fingerprint") or {})
    changed = dict(attrs)
    for map_name in ("modalities", "ambiguous"):
        entries = {key: dict(entry) for key, entry in (fingerprint.get(map_name) or {}).items()}
        _mark_unrefreshed_stale(entries, set(), now)
        fingerprint[map_name] = entries
    changed["fingerprint"] = fingerprint
    return changed


def _embedding_text(part: CanonicalPart) -> str:
    """Deterministic canonical text representation for the embedding seam."""
    pieces = [part.part_number or ""]
    if part.manufacturer:
        pieces.append(f"manufacturer={part.manufacturer}")
    if part.datasheet_ref:
        pieces.append(f"datasheet={part.datasheet_ref}")
    return " | ".join(pieces)


async def resolve(
    session: AsyncSession, ref: SourceRef, *, project_id: uuid.UUID
) -> GraphEntity | None:
    """The API linking consumes: SourceRef → the entity it collapses to.

    Returns the CANONICAL entity when the observation carries a live, same-
    project `canonical_part_id` assertion; otherwise the observation's own row.
    Strictly project-scoped (cross-tenant refs never resolve); never raises —
    unresolvable → None.
    """
    observation = await _resolve_observation(
        session, ref, project_id=project_id, pair_fallback_after_id_miss=True
    )
    if observation is None or observation.canonical_part_id is None:
        return observation
    canonical = await session.get(GraphEntity, observation.canonical_part_id)
    if (
        canonical is not None
        and canonical.project_id == project_id
        and canonical.deleted_at is None
    ):
        return canonical
    # Dangling assertion (canonical tombstoned): fall back to the observation.
    return observation


async def _resolve_observation(
    session: AsyncSession,
    ref: SourceRef,
    *,
    project_id: uuid.UUID,
    pair_fallback_after_id_miss: bool,
) -> GraphEntity | None:
    """Resolve a SourceRef to its live OBSERVATION row (no FK following).

    Write paths (FK linking) pass `pair_fallback_after_id_miss=False`: when a
    provided graph_entity_id turns out tombstoned/foreign, the pair lookup could
    land on a RE-SYNCED, potentially different physical component — a stale ref
    must never stamp an assertion computed from old data onto a new row. The
    read path (`resolve`) keeps the fallback for tombstone-resync convenience.
    """
    if ref.graph_entity_id is not None:
        row = await session.get(GraphEntity, ref.graph_entity_id)
        if row is not None:
            if row.project_id != project_id:
                # Cross-tenant guard: a foreign-project id never resolves.
                logger.warning("fingerprint resolve: entity %s belongs to another project", row.id)
                if not pair_fallback_after_id_miss:
                    return None
            elif row.deleted_at is None:
                return row
        if not pair_fallback_after_id_miss:
            return None
    if ref.source_connector and ref.external_ref:
        rows = (
            await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.source_connector == ref.source_connector,
                    GraphEntity.external_ref == ref.external_ref,
                    GraphEntity.deleted_at.is_(None),
                )
                .order_by(GraphEntity.id)
                .limit(2)
            )
        ).all()
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            # Two sources of one connector type can legally collide on
            # (connector, external_ref) — ambiguous provenance, never guess.
            logger.warning("fingerprint resolve: ambiguous provenance for %s", _source_key(ref))
    return None


async def _locked_canonical_row(
    session: AsyncSession, part: CanonicalPart, key: str, *, project_id: uuid.UUID, now: str
) -> tuple[GraphEntity, bool]:
    """Constraint-based upsert core: insert-if-missing on the partial unique
    index, then lock the live row. Retries once if the conflicting row is
    concurrently soft-deleted between the two statements."""
    for attempt in (0, 1):
        inserted_id = (
            await session.execute(
                pg_insert(GraphEntity)
                .values(
                    project_id=project_id,
                    kind=CANONICAL_KIND,
                    domain=Domain.ELECTRICAL,
                    name=key,
                    canonical_key=key,
                    origin=CANONICAL_ORIGIN,
                    attrs=_merge_part_attrs({}, part, now, complete_run=False),
                )
                .on_conflict_do_nothing(
                    index_elements=_INDEX_ELEMENTS, index_where=_INDEX_PREDICATE
                )
                .returning(GraphEntity.id)  # a row comes back ONLY when inserted
            )
        ).scalar_one_or_none()
        row = (
            await session.execute(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.canonical_key == key,
                    GraphEntity.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None:
            return row, inserted_id is not None
        logger.warning(
            "fingerprint ingest: canonical %r vanished mid-upsert (attempt %d)", key, attempt
        )
    raise RuntimeError(f"fingerprint ingest: could not obtain canonical row for {key!r}")


async def ingest(
    session: AsyncSession,
    part: CanonicalPart,
    *,
    project_id: uuid.UUID,
    complete_run: bool = False,
    embed: EmbedFn | None = None,
    asserted_row_ids: set[uuid.UUID] | None = None,
) -> IngestResult:
    """Idempotent, concurrency-safe upsert of one canonical part.

    Race safety for the canonical row comes from the partial unique index, not
    a read. `complete_run` marks unrefreshed evidence stale (scan semantics);
    bare ingests leave other sources' evidence untouched. `asserted_row_ids`
    (filled for the caller) records every observation this part asserts MATCHED
    this run — `scan_project`'s retraction sweep spares them.
    """
    key = part.part_number
    if not key or len(key) > _MAX_KEY_LEN:
        # Never truncate: a truncated key could merge distinct parts.
        logger.warning("fingerprint ingest: unusable canonical key %r — skipped", key)
        return IngestResult(row=None)
    now = utcnow().isoformat()

    row, created = await _locked_canonical_row(session, part, key, project_id=project_id, now=now)

    updated = False
    merged = _merge_part_attrs(row.attrs, part, now, complete_run=complete_run)
    if _stable_view(merged) != _stable_view(row.attrs):
        row.attrs = merged  # assign a new dict, never mutate (JSONB change detection)
        row.version += 1
        updated = not created

    linked, unresolved, skipped = await _assert_matched_links(
        session, part, row, project_id=project_id, now=now, asserted_row_ids=asserted_row_ids
    )
    embedded = await _write_embedding(part, row, embed)
    # Flush (never commit — the caller owns the transaction): ORM mutations must
    # be visible to same-transaction readers and survive a refresh().
    await session.flush()
    return IngestResult(
        row=row,
        created=created,
        updated=updated,
        linked=linked,
        unresolved=unresolved,
        skipped_unstamped=skipped,
        embedded=embedded,
    )


async def _assert_matched_links(
    session: AsyncSession,
    part: CanonicalPart,
    row: GraphEntity,
    *,
    project_id: uuid.UUID,
    now: str,
    asserted_row_ids: set[uuid.UUID] | None,
) -> tuple[int, int, int]:
    """Set the canonical FK (+ ownership stamp) on MATCHED observations only.

    OWNERSHIP GUARD (the other half of CLEAR+STAMP): an existing FK WITHOUT our
    stamp is a human/LNK-01 assertion — never overwritten, even when the matcher
    disagrees. The disagreement stays visible in the canonical's evidence map.
    """
    linked = 0
    unresolved = 0
    skipped_unstamped = 0
    for modality_match in part.modalities:
        if modality_match.state is not MatchState.MATCHED:
            continue  # LOW_CONFIDENCE is candidate evidence only — never an FK
        observation = await _resolve_observation(
            session,
            modality_match.source_ref,
            project_id=project_id,
            pair_fallback_after_id_miss=False,
        )
        if observation is None or observation.id == row.id:
            unresolved += 1
            continue
        if observation.canonical_part_id == row.id:
            # Already asserted. Spare it from the retraction sweep only when it
            # is OURS; an unstamped agreeing FK stays human-owned territory.
            if asserted_row_ids is not None and _STAMP_KEY in observation.attrs:
                asserted_row_ids.add(observation.id)
            continue
        if observation.canonical_part_id is not None and _STAMP_KEY not in observation.attrs:
            logger.warning(
                "fingerprint ingest: observation %s carries an unstamped (human/LNK-01) "
                "assertion — matcher disagreement recorded as evidence only",
                observation.id,
            )
            skipped_unstamped += 1
            continue
        observation.canonical_part_id = row.id
        observation.attrs = {
            **observation.attrs,
            _STAMP_KEY: {"canonical_key": row.canonical_key, "run_at": now},
        }
        observation.version += 1
        linked += 1
        if asserted_row_ids is not None:
            asserted_row_ids.add(observation.id)
    return linked, unresolved, skipped_unstamped


async def _write_embedding(part: CanonicalPart, row: GraphEntity, embed: EmbedFn | None) -> bool:
    """Best-effort, never load-bearing: failures are logged and swallowed, and
    the vector is retrieval-only — it can never change a match outcome."""
    if embed is None or row.embedding is not None:
        return False
    try:
        vector = await embed(_embedding_text(part))
    except Exception:  # noqa: BLE001 — embedding is best-effort
        logger.warning("fingerprint embedding failed for %r", row.canonical_key, exc_info=True)
        return False
    if vector is None:
        return False
    if len(vector) != EMBEDDING_DIM:
        logger.warning(
            "fingerprint embedding for %r has wrong dimension — skipped", row.canonical_key
        )
        return False
    row.embedding = vector
    return True


async def ingest_output(
    session: AsyncSession,
    output: FingerprintOutput,
    *,
    project_id: uuid.UUID,
    complete_run: bool = False,
    embed: EmbedFn | None = None,
    asserted_row_ids: set[uuid.UUID] | None = None,
    ingested_canonical_ids: set[uuid.UUID] | None = None,
) -> ScanSummary:
    """Persist a full matcher output: parts, then ambiguous candidate evidence.

    AMBIGUOUS is recorded on EVERY candidate canonical present in this output —
    SOL explaining "why isn't this linked" must find the evidence from
    whichever candidate the user inspects. A candidate uuid5 with no ingested
    row is skipped: ambiguity alone never creates a canonical entity.
    `unmatched` observations are counted and otherwise left completely alone.
    """
    now = utcnow().isoformat()
    created = updated = linked = low_confidence = unresolved = embedded = skipped = 0
    by_uuid5: dict[uuid.UUID, GraphEntity] = {}
    for part in output.canonical_parts:
        result = await ingest(
            session,
            part,
            project_id=project_id,
            complete_run=complete_run,
            embed=embed,
            asserted_row_ids=asserted_row_ids,
        )
        if result.row is None:
            continue
        by_uuid5[part.canonical_id] = result.row
        if ingested_canonical_ids is not None:
            ingested_canonical_ids.add(result.row.id)
        created += result.created
        updated += result.updated
        linked += result.linked
        unresolved += result.unresolved
        embedded += result.embedded
        skipped += result.skipped_unstamped
        low_confidence += sum(1 for m in part.modalities if m.state is MatchState.LOW_CONFIDENCE)

    for ambiguous_obs in output.ambiguous:
        for candidate_id in ambiguous_obs.candidate_canonical_ids:
            row = by_uuid5.get(candidate_id)
            if row is None:
                continue
            merged = _merge_ambiguous_attrs(row.attrs, ambiguous_obs, now)
            if _stable_view(merged) != _stable_view(row.attrs):
                row.attrs = merged
                row.version += 1
    await session.flush()

    return ScanSummary(
        canonical_created=created,
        canonical_updated=updated,
        linked=linked,
        skipped_unstamped=skipped,
        low_confidence=low_confidence,
        ambiguous=len(output.ambiguous),
        unmatched=len(output.unmatched),
        unresolved_refs=unresolved,
        embedded=embedded,
    )


async def scan_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    config: FingerprintConfig | None = None,
    embed: EmbedFn | None = None,
) -> ScanSummary:
    """Pipeline entry point: gather → match (pure, LLM-free) → ingest → sweeps.

    Serialized per project via a transaction-scoped advisory lock: two scans
    matching different snapshots must never interleave assertions/retractions.
    User-less by design: the future trigger router (Job + events + optional
    escalation, which all need an authenticated user) wraps this and owns the
    commit.
    """
    cfg = config or default_fingerprint_config()
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(project_id), 0)))
    )
    rows = (
        await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
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

    output = match(observations, config=cfg)
    asserted: set[uuid.UUID] = set()
    ingested_ids: set[uuid.UUID] = set()
    summary = await ingest_output(
        session,
        output,
        project_id=project_id,
        complete_run=True,
        embed=embed,
        asserted_row_ids=asserted,
        ingested_canonical_ids=ingested_ids,
    )
    now = utcnow().isoformat()

    # CLEAR + STAMP retraction sweep: stamped (fingerprint-owned) assertions the
    # run no longer supports are retracted. Scoped to ALL live stamped rows —
    # an observation whose hints emptied is exactly the retraction case.
    stamped = (
        await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
                func.jsonb_exists(GraphEntity.attrs, _STAMP_KEY),
            )
            .order_by(GraphEntity.id)  # deterministic lock order
        )
    ).all()
    cleared = 0
    for row in stamped:
        if row.id in asserted:
            continue
        row.canonical_part_id = None
        row.attrs = {key: value for key, value in row.attrs.items() if key != _STAMP_KEY}
        row.version += 1
        cleared += 1

    # Orphaned-canonical sweep: a canonical that appeared in NO group this run
    # was re-derived by nothing — its cached evidence is no longer supported.
    # Mark it all stale (the row itself stays live; lifecycle is a follow-on).
    staled = 0
    canonicals = (
        await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
                GraphEntity.kind == CANONICAL_KIND,
                GraphEntity.canonical_key.is_not(None),
            )
            .order_by(GraphEntity.id)
        )
    ).all()
    for row in canonicals:
        if row.id in ingested_ids:
            continue
        marked = _mark_all_stale(row.attrs, now)
        if _stable_view(marked) != _stable_view(row.attrs):
            row.attrs = marked
            row.version += 1
            staled += 1
    await session.flush()

    return dataclasses.replace(
        summary, observations=len(observations), cleared=cleared, canonical_staled=staled
    )
