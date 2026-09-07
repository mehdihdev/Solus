"""Persist the confirmed robot via the fingerprint seam (RBT-05) — define once.

NO parallel identity mechanism: a confirmed robot is `CanonicalPart` +
`ModalityMatch` entries fed through FP-02's `ingest_output`, landing in the same
`kind="canonical_part"` rows, keyed by the same `(project_id, canonical_key)`
index, carrying evidence in the same attrs layout every other fingerprint path
uses. The identity linchpin holds throughout: bus/firmware/telemetry evidence
reconciles into ONE canonical entity per part number.

The user's RBT-03 confirmation itself rides the seam AS EVIDENCE — a
`ModalityMatch` whose evidence records `matched_on: user_confirmation` and the
confirmed function name. No new column, no new type; SOL explaining "why is this
the elbow" finds the user's own decision next to the wire evidence.

Honesty boundaries:
* A confirmation with NO part identity (a tier-3 user-named bare channel) is
  REPORTED, never persisted with an invented part number — fabricated keys would
  merge distinct hardware, the false-merge catastrophe class.
* Unconfirmed/ambiguous observations flow through as FP-02 `unmatched`/
  `ambiguous` — explicitly unlinked, never optimistically merged.
* Reconnection: `recognize_robot` compares freshly observed bus identities
  against the persisted evidence; an exact match is recognized with no
  re-confirmation, ANY difference (changed part, new device, missing device) is
  returned as a diff for RBT-03 to RE-PROPOSE — never silently kept.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.fingerprint import (
    AmbiguousObservation,
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    ModalityMatch,
    SourceRef,
    canonical_uuid,
)
from solus_api.fingerprint.config import default_fingerprint_config
from solus_api.fingerprint.ingest import ingest_output
from solus_api.fingerprint.normalize import normalize_mpn
from solus_api.models import GraphEntity

#: User-confirmed, not device-asserted: high, but never 1.0 — a user can be wrong.
CONFIRMED_CONFIDENCE = 0.98

#: canonical_key is String(64); a base longer than this cannot be stored — skip, never truncate.
_MAX_CANONICAL_KEY = 64
#: Confirmed function name is a label bound before it reaches GraphEntity attrs / SOL context.
_MAX_FUNCTION_NAME = 128

_BUS_PREFIX = "bus_enumeration:"


@dataclass(frozen=True)
class ConfirmedMapping:
    """One accepted/edited row from the RBT-03 surface, with its upstream evidence."""

    part_number: str | None
    manufacturer: str | None
    function_name: str
    evidence: Sequence[ModalityMatch]


@dataclass(frozen=True)
class PersistReport:
    persisted: list[str]
    skipped_no_part_identity: list[str]
    unconfirmed_recorded: int


@dataclass(frozen=True)
class RobotRecognition:
    """The reconnect verdict: recognized as-is, or a diff to re-propose."""

    recognized: bool
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)  # ref → (was, now)
    added: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)


def _confirmation_evidence(mapping: ConfirmedMapping) -> ModalityMatch:
    anchor = mapping.evidence[0]
    return ModalityMatch(
        modality=anchor.modality,
        source_ref=anchor.source_ref,
        confidence=CONFIRMED_CONFIDENCE,
        state=MatchState.MATCHED,
        evidence={
            "matched_on": "user_confirmation",
            "value": mapping.function_name,
            "note": "the user confirmed this mapping via RBT-03 — recorded, not inferred",
        },
    )


async def persist_confirmed_robot(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    confirmed: Sequence[ConfirmedMapping],
    unconfirmed: Sequence[SourceRef] = (),
    ambiguous: Sequence[AmbiguousObservation] = (),
) -> PersistReport:
    """Confirmed mappings → the FP-02 seam. Flushes; the caller owns commit."""
    config = default_fingerprint_config()
    parts: list[CanonicalPart] = []
    skipped: list[str] = []
    for mapping in confirmed:
        # Normalize to the SAME base FP-02 keys on (matcher.py: canonical_uuid(base),
        # part_number=base) — keying on the raw string would fork identity for every
        # hyphenated part (ABC-123 vs ABC123), the false-merge/fork class this
        # module exists to prevent. No derivable MPN, or a base too long to store, →
        # reported, never persisted under an invented/truncated key.
        normalized = normalize_mpn(mapping.part_number, config) if mapping.part_number else None
        if normalized is None or not mapping.evidence or len(normalized.base) > _MAX_CANONICAL_KEY:
            skipped.append(mapping.function_name[:_MAX_FUNCTION_NAME])
            continue
        parts.append(
            CanonicalPart(
                canonical_id=canonical_uuid(normalized.base),
                part_number=normalized.base,
                manufacturer=mapping.manufacturer,
                modalities=[*mapping.evidence, _confirmation_evidence(mapping)],
                confidence=CONFIRMED_CONFIDENCE,
            )
        )
    output = FingerprintOutput(
        canonical_parts=parts, unmatched=list(unconfirmed), ambiguous=list(ambiguous)
    )
    await ingest_output(session, output, project_id=project_id)
    return PersistReport(
        persisted=[part.part_number for part in parts if part.part_number],
        skipped_no_part_identity=skipped,
        unconfirmed_recorded=len(unconfirmed),
    )


async def _persisted_bus_map(session: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """external_ref → canonical_key for every persisted bus-enumerated identity."""
    rows = await session.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == "canonical_part",
            GraphEntity.deleted_at.is_(None),
        )
    )
    persisted: dict[str, str] = {}
    for row in rows:
        if not row.canonical_key:
            continue
        fingerprint = row.attrs.get("fingerprint") or {}
        for key, entry in (fingerprint.get("modalities") or {}).items():
            if not key.startswith(_BUS_PREFIX) or entry.get("stale_at"):
                continue
            external_ref = (entry.get("source_ref") or {}).get("external_ref")
            if external_ref:
                persisted[external_ref] = row.canonical_key
    return persisted


async def recognize_robot(
    session: AsyncSession, *, project_id: uuid.UUID, observed: dict[str, str]
) -> RobotRecognition:
    """Compare freshly observed bus identities (`external_ref → part_number`)
    against the persisted robot. Exact match → recognized, no re-confirmation.
    Anything else → the diff RBT-03 re-proposes from.

    Both sides are normalized to the FP-02 base before comparison — a fresh scan
    reports a raw part number, the graph stores the base, and reconnect must not
    re-propose a robot just because of hyphenation."""
    config = default_fingerprint_config()
    persisted = await _persisted_bus_map(session, project_id)
    observed_base: dict[str, str] = {}
    for ref, part in observed.items():
        normalized = normalize_mpn(part, config)
        observed_base[ref] = normalized.base if normalized is not None else part
    changed = {
        ref: (persisted[ref], part)
        for ref, part in observed_base.items()
        if ref in persisted and persisted[ref] != part
    }
    added = {ref for ref in observed if ref not in persisted}
    missing = {ref for ref in persisted if ref not in observed}
    return RobotRecognition(
        recognized=not changed and not added and not missing,
        changed=changed,
        added=added,
        missing=missing,
    )
