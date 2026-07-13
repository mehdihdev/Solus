"""Multimodal fingerprint: the W0-06 OUTPUT contract, the FP-01 matcher, and
FP-02 graph ingestion.

Contract (human-owned, ADR-028): the shapes + committed mock linking (LNK-01)
builds against. Matcher (FP-01): `match()` — pure, deterministic,
precision-first — and the optional gateway-backed LLM escalation. Ingestion
(FP-02): `ingest()`/`scan_project()` write matcher output into the graph
(only MATCHED asserts) and `resolve()` is the entity-collapse API linking
consumes. See docs/contracts/fingerprint-output.md.
"""

from solus_api.fingerprint.config import (
    FingerprintConfig,
    default_fingerprint_config,
    load_fingerprint_config,
)
from solus_api.fingerprint.contract import (
    AmbiguousObservation,
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    Modality,
    ModalityMatch,
    SourceRef,
    load_mock_output,
)
from solus_api.fingerprint.escalation import build_escalator
from solus_api.fingerprint.ingest import (
    EmbedFn,
    IngestResult,
    ScanSummary,
    ingest,
    ingest_output,
    resolve,
    scan_project,
)
from solus_api.fingerprint.matcher import (
    LlmEscalateFn,
    Observation,
    match,
    match_with_escalation,
    observations_from_hints,
)
from solus_api.fingerprint.normalize import (
    SOLUS_FINGERPRINT_NAMESPACE,
    NormalizedMPN,
    canonical_uuid,
    extract_candidate_bases,
    normalize_mpn,
)
from solus_api.fingerprint.visual import (
    MarkingCandidate,
    identify_from_image,
    photo_observations,
)

__all__ = [
    "SOLUS_FINGERPRINT_NAMESPACE",
    "AmbiguousObservation",
    "CanonicalPart",
    "EmbedFn",
    "FingerprintConfig",
    "FingerprintOutput",
    "IngestResult",
    "LlmEscalateFn",
    "MatchState",
    "Modality",
    "ModalityMatch",
    "NormalizedMPN",
    "Observation",
    "ScanSummary",
    "SourceRef",
    "build_escalator",
    "canonical_uuid",
    "default_fingerprint_config",
    "extract_candidate_bases",
    "ingest",
    "ingest_output",
    "load_fingerprint_config",
    "load_mock_output",
    "MarkingCandidate",
    "identify_from_image",
    "match",
    "match_with_escalation",
    "normalize_mpn",
    "observations_from_hints",
    "photo_observations",
    "resolve",
    "scan_project",
]
