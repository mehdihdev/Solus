"""FP-01 structured-modality part matcher (SOLUSDEV-59).

`match()` is a pure, deterministic function: observations in, W0-06
`FingerprintOutput` out. No DB, no network, no hidden state — the full eval
runs against it with no LLM available. `match_with_escalation()` is the only
async wrapper: it collects unknown-format part numbers, asks the (gateway-
backed, memoized) escalator for base-family proposals, and re-runs the pure
matcher with them.

Precision invariants (spec; enforced structurally, tested directly):
- Identity groups are seeded ONLY by part_number observations; symbols and
  datasheets corroborate, never seed.
- An observation scoring against >1 candidate is AMBIGUOUS, never best-of.
- A datasheet with no same-entity part number never attaches ("a datasheet
  alone is a family"); a generic symbol is near-zero evidence.
- An LLM proposal is recorded as EVIDENCE (`llm_proposed_base`) on the
  observation's own match. It never moves an observation between identity
  groups, never creates a group, and never sets a state — a hallucinated
  "these are the same part" cannot change the partition at all.
- `extra_candidate_bases` is the pgvector retrieval seam: retrieval hits carry
  zero evidence and cannot anchor attachment — they can only surface AMBIGUITY
  against member-backed candidates — so vector similarity can never decide a
  merge (writes/queries of embeddings are FP-02's job).
"""

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict

from solus_api.fingerprint.config import FingerprintConfig, default_fingerprint_config
from solus_api.fingerprint.contract import (
    AmbiguousObservation,
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    Modality,
    ModalityMatch,
    SourceRef,
)
from solus_api.fingerprint.normalize import (
    canonical_uuid,
    extract_candidate_bases,
    normalize_mpn,
)

logger = logging.getLogger(__name__)

LlmEscalateFn = Callable[[str], Awaitable[str | None]]

_HINT_KEYS: dict[str, Modality] = {
    "part_number": Modality.PART_NUMBER,
    "schematic_symbol": Modality.SCHEMATIC_SYMBOL,
    "datasheet": Modality.DATASHEET,
    "cad_model": Modality.CAD_MODEL,  # v1-unscored → lands in unmatched, never dropped
}


class Observation(BaseModel):
    """One modality hint with its provenance — the matcher's input unit.
    Observations sharing (source_connector, external_ref) are the same entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref: SourceRef
    modality: Modality
    value: str
    manufacturer: str | None = None  # metadata rider, not a modality
    footprint: str | None = None  # metadata rider, conflict evidence only


def observations_from_hints(
    source_ref: SourceRef,
    hints: Mapping[str, Any],
    *,
    manufacturer: str | None = None,
    footprint: str | None = None,
) -> list[Observation]:
    """Adapt one `graph_entity.modality_hints` dict (W0-05 channel) into
    observations. Documented keys only; non-string values are skipped."""
    return [
        Observation(
            source_ref=source_ref,
            modality=modality,
            value=value,
            manufacturer=manufacturer,
            footprint=footprint,
        )
        for key, modality in _HINT_KEYS.items()
        if isinstance(value := hints.get(key), str)
    ]


class _Member(NamedTuple):
    """One observation attached to a candidate group, pre-finalization."""

    observation: Observation
    score: float
    evidence: dict[str, Any]
    package: str | None = None


def _entity_key(observation: Observation) -> str:
    ref = observation.source_ref
    if ref.source_connector and ref.external_ref:
        return f"{ref.source_connector}:{ref.external_ref}"
    return str(ref.graph_entity_id)


def _sort_key(ref: SourceRef) -> tuple[str, str, str]:
    return (ref.source_connector or "", ref.external_ref or "", str(ref.graph_entity_id or ""))


class _Buckets:
    """Mutable accumulation state for one match() run."""

    def __init__(self) -> None:
        self.members: dict[str, list[_Member]] = {}
        self.unmatched: list[Observation] = []
        self.ambiguous: list[AmbiguousObservation] = []
        self.entity_bases: dict[str, set[str]] = {}

    def attach(self, base: str, member: _Member) -> None:
        self.members.setdefault(base, []).append(member)

    def mark_ambiguous(self, observation: Observation, bases: set[str], note: str) -> None:
        ordered = sorted(bases)
        self.ambiguous.append(
            AmbiguousObservation(
                source_ref=observation.source_ref,
                candidate_canonical_ids=[canonical_uuid(base) for base in ordered],
                note=note,
            )
        )


def _score_part_numbers(
    part_numbers: Sequence[Observation],
    buckets: _Buckets,
    config: FingerprintConfig,
    proposals: Mapping[str, str],
) -> None:
    for obs in part_numbers:
        norm = normalize_mpn(obs.value, config)
        if norm is None:
            buckets.unmatched.append(obs)
            continue
        stripped = norm.package is not None or norm.grade is not None
        score = config.weights.base_known_suffix if stripped else config.weights.exact_mpn
        evidence: dict[str, Any] = {
            "matched_on": "part_number",
            "value": obs.value.strip(),
            "base": norm.base,
        }
        for key in ("package", "grade", "vendor_prefix"):
            if (delta := getattr(norm, key)) is not None:
                evidence[key] = delta
        proposal = proposals.get(obs.value.strip().upper()) if norm.family is None else None
        if proposal is not None and proposal != norm.base:
            # An LLM proposal is recorded evidence, NEVER a bucket move:
            # silently re-homing a plausible standalone identity is how a
            # hallucinated "same part" (or a one-sided gateway failure) would
            # merge adjudicated-distinct parts like AMS1117-3.3 vs AMS1117-5.0.
            evidence["llm_proposed_base"] = proposal
            evidence["llm_derived"] = True
        buckets.attach(norm.base, _Member(obs, score, evidence, package=norm.package))
        buckets.entity_bases.setdefault(_entity_key(obs), set()).add(norm.base)


def _is_generic_symbol(value: str, config: FingerprintConfig) -> bool:
    cleaned = value.strip().upper()
    if len(cleaned) > config.extraction.max_text_len:
        # Oversized ingested text: bounded BEFORE any regex touches it (§7).
        # Token extraction applies the same bound, so it lands unmatched.
        return False
    return any(pattern.search(cleaned) for pattern in config.extraction.generic_patterns)


def _naming_note(kind: str, named: set[str], own: set[str]) -> str:
    """Honest ambiguity note: what the string actually NAMED, separately from
    what the entity's own part number(s) claim — evidence must not misattribute
    an entity-side data conflict to the symbol/datasheet string."""
    named_text = ", ".join(sorted(named)) if named else "nothing known"
    claimed_text = ", ".join(sorted(own)) if own else "no part number"
    return f"{kind} names: {named_text}; entity part number claims: {claimed_text}"


def _score_symbol(
    observation: Observation,
    member_bases: set[str],
    seeded: set[str],
    buckets: _Buckets,
    config: FingerprintConfig,
) -> None:
    if _is_generic_symbol(observation.value, config):
        # Near-zero evidence by config guarantee (< low threshold): reused
        # across unrelated parts, a generic symbol is a false-merge engine.
        buckets.unmatched.append(observation)
        return
    extracted = set(extract_candidate_bases(observation.value, config))
    context = extracted & (member_bases | seeded)
    own = buckets.entity_bases.get(_entity_key(observation), set())
    candidates = context | own
    if not context:
        buckets.unmatched.append(observation)
    elif len(candidates) == 1 and candidates <= member_bases:
        base = next(iter(candidates))
        evidence = {"matched_on": "schematic_symbol", "value": observation.value, "base": base}
        buckets.attach(base, _Member(observation, config.weights.specific_symbol, evidence))
    elif member_backed := candidates & member_bases:
        buckets.mark_ambiguous(observation, member_backed, _naming_note("symbol", context, own))
    else:
        # Only retrieval-seeded hits: a seed never anchors attachment — there
        # is no in-run identity to join (similarity proposes, never merges).
        buckets.unmatched.append(observation)


def _score_photos(
    photos: Sequence[Observation],
    member_bases: set[str],
    buckets: _Buckets,
    config: FingerprintConfig,
) -> None:
    """FP-03 containment, structural by construction: photo readings may only
    CORROBORATE an existing part-number group (member_bases only — never
    seeded, never entity-own, never seeding); the capped photo weight
    (< thresholds.matched, load-validated) means a photo match is always
    LOW_CONFIDENCE, so FP-02 never sets canonical_part_id from it. One
    disposition per photo entity: all its candidate readings share one
    source_ref, and multiple hits are ONE ambiguity — never a chosen winner."""
    by_entity: dict[str, list[Observation]] = {}
    for observation in photos:
        by_entity.setdefault(_entity_key(observation), []).append(observation)
    for entity_key in sorted(by_entity):
        readings = sorted(by_entity[entity_key], key=lambda o: o.value)
        named: set[str] = set()
        for reading in readings:
            named |= set(extract_candidate_bases(reading.value, config)) & member_bases
        representative = readings[0]
        if not named:
            buckets.unmatched.append(representative)
        elif len(named) == 1:
            base = next(iter(named))
            evidence: dict[str, Any] = {
                "matched_on": "photo_marking",
                "readings": [reading.value for reading in readings],
                "base": base,
            }
            buckets.attach(base, _Member(representative, config.weights.photo, evidence))
        else:
            buckets.mark_ambiguous(
                representative,
                named,
                f"photo readings name more than one part: {', '.join(sorted(named))}",
            )


def _score_datasheet(
    observation: Observation,
    member_bases: set[str],
    seeded: set[str],
    buckets: _Buckets,
    config: FingerprintConfig,
) -> None:
    own = buckets.entity_bases.get(_entity_key(observation), set())
    if not own:
        # "A datasheet alone is a family" — with no same-entity part number it
        # can never attach, no matter what its tokens name.
        buckets.unmatched.append(observation)
        return
    extracted = set(extract_candidate_bases(observation.value, config))
    context = extracted & (member_bases | seeded)
    candidates = context | own
    if not context:
        buckets.unmatched.append(observation)
    elif candidates == own and len(own) == 1:
        base = next(iter(own))
        evidence = {"matched_on": "datasheet", "value": observation.value.strip(), "base": base}
        buckets.attach(base, _Member(observation, config.weights.datasheet, evidence))
    else:
        # own is non-empty and member-backed, so candidates ∩ members ≥ 1.
        buckets.mark_ambiguous(
            observation,
            candidates & member_bases,
            _naming_note("datasheet", context, own),
        )


def _conflicts(members: Sequence[_Member]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    packages = {m.package for m in members if m.package is not None}
    footprints = {m.observation.footprint for m in members if m.observation.footprint is not None}
    manufacturers = {
        m.observation.manufacturer for m in members if m.observation.manufacturer is not None
    }
    if len(packages) > 1:
        found["package"] = sorted(packages)
    if len(footprints) > 1:
        found["footprint"] = sorted(footprints)
    if len(manufacturers) > 1:
        found["manufacturer"] = sorted(manufacturers)
    return found


def _unanimous(values: list[str]) -> str | None:
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else None


def _build_part(base: str, members: list[_Member], config: FingerprintConfig) -> CanonicalPart:
    conflicts = _conflicts(members)
    # Conflicts COMPOUND: three independent disagreement classes signal more
    # risk than one, and confidence is the field that carries that to linking.
    penalty = min(
        1.0,
        sum(
            getattr(config.penalties, f"{conflict_class}_conflict") for conflict_class in conflicts
        ),
    )
    matches = []
    for member in sorted(
        members,
        key=lambda m: (
            m.observation.modality.value,
            _sort_key(m.observation.source_ref),
            m.observation.value,
            m.score,
        ),
    ):
        evidence = dict(member.evidence)
        if conflicts:
            # Fresh copy per match: frozen models don't freeze nested dicts,
            # and sibling matches must never alias one mutable evidence object.
            evidence["conflict"] = {key: list(values) for key, values in conflicts.items()}
        state = (
            MatchState.MATCHED
            if member.score >= config.thresholds.matched
            else MatchState.LOW_CONFIDENCE
        )
        matches.append(
            ModalityMatch(
                modality=member.observation.modality,
                source_ref=member.observation.source_ref,
                confidence=member.score,
                state=state,
                evidence=evidence,
            )
        )
    best = max(member.score for member in members)
    distinct_modalities = len({member.observation.modality for member in members})
    bonus = config.weights.corroboration_bonus * (distinct_modalities - 1)
    overall = min(1.0, best + bonus) * (1.0 - penalty)
    return CanonicalPart(
        canonical_id=canonical_uuid(base),
        part_number=base,
        manufacturer=_unanimous(
            [m.observation.manufacturer for m in members if m.observation.manufacturer]
        ),
        datasheet_ref=_unanimous(
            [
                m.observation.value.strip()
                for m in members
                if m.observation.modality is Modality.DATASHEET
            ]
        ),
        modalities=matches,
        confidence=overall,
    )


def match(
    observations: Sequence[Observation],
    *,
    config: FingerprintConfig | None = None,
    llm_proposals: Mapping[str, str] | None = None,
    extra_candidate_bases: Sequence[str] = (),
) -> FingerprintOutput:
    """Group observations into canonical parts per the W0-06 contract.

    Pure and deterministic: identical inputs (in any order) yield identical
    output, including `canonical_id`s (uuid5 of the normalized base identity).
    `llm_proposals` only annotate evidence; `extra_candidate_bases` (retrieval
    seam) only surface ambiguity — neither can change which observations merge.
    """
    cfg = config or default_fingerprint_config()
    proposals = {
        key.strip().upper(): value.strip().upper() for key, value in (llm_proposals or {}).items()
    }
    seeded = {base.strip().upper() for base in extra_candidate_bases if base.strip()}
    buckets = _Buckets()

    part_numbers = [o for o in observations if o.modality is Modality.PART_NUMBER]
    symbols = [o for o in observations if o.modality is Modality.SCHEMATIC_SYMBOL]
    datasheets = [o for o in observations if o.modality is Modality.DATASHEET]
    photos = [o for o in observations if o.modality is Modality.PHOTO]
    for observation in observations:
        if observation.modality is Modality.CAD_MODEL:
            buckets.unmatched.append(observation)  # CAD stays v1-unscored

    _score_part_numbers(part_numbers, buckets, cfg, proposals)
    member_bases = set(buckets.members)
    for observation in symbols:
        _score_symbol(observation, member_bases, seeded, buckets, cfg)
    for observation in datasheets:
        _score_datasheet(observation, member_bases, seeded, buckets, cfg)
    _score_photos(photos, member_bases, buckets, cfg)  # last: corroborate-only

    # Threshold floor: nothing below low_confidence may live inside a part.
    for base in list(buckets.members):
        keep = [m for m in buckets.members[base] if m.score >= cfg.thresholds.low_confidence]
        dropped = [m for m in buckets.members[base] if m.score < cfg.thresholds.low_confidence]
        buckets.unmatched.extend(m.observation for m in dropped)
        if keep:
            buckets.members[base] = keep
        else:
            del buckets.members[base]

    return FingerprintOutput(
        canonical_parts=[
            _build_part(base, buckets.members[base], cfg) for base in sorted(buckets.members)
        ],
        unmatched=sorted((o.source_ref for o in buckets.unmatched), key=_sort_key),
        ambiguous=sorted(
            buckets.ambiguous,
            key=lambda a: (_sort_key(a.source_ref), a.note or ""),
        ),
    )


async def match_with_escalation(
    observations: Sequence[Observation],
    *,
    escalate: LlmEscalateFn,
    config: FingerprintConfig | None = None,
) -> FingerprintOutput:
    """Deterministic rules first; the LLM is an escalation only (spec Part E).

    Escalates each distinct unknown-format part number (plausible MPN that no
    family rule recognized) at most once. A failed or refused escalation is
    no-signal: the result is exactly the LLM-free `match()`.
    """
    cfg = config or default_fingerprint_config()
    candidates: dict[str, None] = {}
    for observation in observations:
        if observation.modality is not Modality.PART_NUMBER:
            continue
        normalized = normalize_mpn(observation.value, cfg)
        if normalized is not None and normalized.family is None:
            candidates.setdefault(observation.value.strip().upper())

    proposals: dict[str, str] = {}
    for value in candidates:
        try:
            proposed = await escalate(value)
        except Exception:  # noqa: BLE001 — escalation is best-effort corroboration
            logger.warning("fingerprint escalation failed for %r", value, exc_info=True)
            proposed = None
        if proposed:
            proposals[value] = proposed
    return match(observations, config=cfg, llm_proposals=proposals)
