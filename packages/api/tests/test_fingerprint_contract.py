"""The fingerprint output contract + its committed mock (SOLUS-W0-06).

Proves the mock-and-swap seam: the models validate the mock, and the mock demonstrably
carries every hard case linking (LNK-01) must handle before the real matcher exists. If a
case is missing here, code built against the mock breaks on real matcher output.
"""

from uuid import UUID

import pytest
from pydantic import ValidationError
from solus_api.fingerprint.contract import (
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    Modality,
    ModalityMatch,
    SourceRef,
    load_mock_output,
)


def test_models_validate_the_committed_mock() -> None:
    output = load_mock_output()  # FingerprintOutput.model_validate_json under the hood
    assert isinstance(output, FingerprintOutput)
    assert len(output.canonical_parts) >= 10


def test_mock_covers_a_clean_high_confidence_match() -> None:
    output = load_mock_output()
    clean = [
        cp
        for cp in output.canonical_parts
        if cp.confidence >= 0.95
        and len(cp.modalities) >= 2
        and all(m.state is MatchState.MATCHED for m in cp.modalities)
    ]
    assert clean, "expected an all-matched high-confidence part (e.g. LM358)"


def test_mock_covers_a_low_confidence_modality_inside_a_matched_part() -> None:
    output = load_mock_output()
    # A part accepted overall, but carrying a flagged modality linking can choose to drop.
    flagged = [
        cp
        for cp in output.canonical_parts
        if any(m.state is MatchState.LOW_CONFIDENCE for m in cp.modalities)
        and any(m.state is MatchState.MATCHED for m in cp.modalities)
    ]
    assert flagged


def test_mock_has_explicit_unmatched_observations() -> None:
    output = load_mock_output()
    assert len(output.unmatched) >= 2  # explicit list, not inferred by absence


def test_mock_has_ambiguous_observation_referencing_real_canonical_ids() -> None:
    output = load_mock_output()
    assert output.ambiguous
    known: set[UUID] = {cp.canonical_id for cp in output.canonical_parts}
    for amb in output.ambiguous:
        assert len(amb.candidate_canonical_ids) >= 2
        assert set(amb.candidate_canonical_ids) <= known  # candidates are real parts


def test_mock_covers_a_partial_disagreement_across_modalities() -> None:
    output = load_mock_output()

    def disagrees(cp: CanonicalPart) -> bool:
        values = {m.evidence.get("value") for m in cp.modalities if m.evidence.get("value")}
        return len(values) > 1

    assert any(disagrees(cp) for cp in output.canonical_parts), (
        "expected a modality disagreement (e.g. AMS1117 -3.3 vs -5.0)"
    )


def test_mock_carries_a_photo_modality_even_though_v1_wont_produce_it() -> None:
    output = load_mock_output()
    photos = [
        m for cp in output.canonical_parts for m in cp.modalities if m.modality is Modality.PHOTO
    ]
    assert photos


def test_sourceref_requires_a_resolvable_reference() -> None:
    SourceRef(graph_entity_id=UUID("22222222-2222-2222-2222-222222220201"))  # id alone: ok
    SourceRef(source_connector="kicad", external_ref="U1")  # connector + ref: ok
    with pytest.raises(ValidationError):
        SourceRef()  # nothing resolvable
    with pytest.raises(ValidationError):
        SourceRef(source_connector="kicad")  # connector without external_ref


def test_confidence_is_bounded_zero_to_one() -> None:
    ref = SourceRef(source_connector="kicad", external_ref="U1")
    ModalityMatch(
        modality=Modality.PART_NUMBER, source_ref=ref, confidence=1.0, state=MatchState.MATCHED
    )
    for bad in (1.5, -0.1):
        with pytest.raises(ValidationError):
            ModalityMatch(
                modality=Modality.PART_NUMBER,
                source_ref=ref,
                confidence=bad,
                state=MatchState.MATCHED,
            )
