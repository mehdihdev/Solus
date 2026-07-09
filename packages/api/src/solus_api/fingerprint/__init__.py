"""Multimodal fingerprint OUTPUT contract (SOLUS-W0-06): the data shape the matcher
produces and cross-domain linking consumes. Shape + a committed mock only — the matcher
(FP-01/02) and linking (LNK-01) are separate tickets. See docs/contracts/fingerprint-output.md.
"""

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

__all__ = [
    "AmbiguousObservation",
    "CanonicalPart",
    "FingerprintOutput",
    "MatchState",
    "Modality",
    "ModalityMatch",
    "SourceRef",
    "load_mock_output",
]
