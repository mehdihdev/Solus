"""FP-01 matcher core: grouping, rules table, states, ambiguity, conflicts.

Every precision guard from the spec gets a direct test here: ambiguity is
never resolved best-of, a datasheet alone never merges, a generic symbol is
near-zero, an LLM proposal is capped below MATCHED, and retrieval-seeded
candidates cannot absorb a distinct identity.
"""

import asyncio
import uuid

import pytest
from pydantic import ValidationError
from solus_api.fingerprint.config import (
    FingerprintConfig,
    load_fingerprint_config,
)
from solus_api.fingerprint.contract import (
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    Modality,
    SourceRef,
)
from solus_api.fingerprint.matcher import (
    Observation,
    match,
    match_with_escalation,
    observations_from_hints,
)
from solus_api.fingerprint.normalize import canonical_uuid

_CFG = load_fingerprint_config()
_TEST_NS = uuid.UUID("00000000-0000-0000-0000-00000000f1f1")


def ref(external_ref: str, connector: str = "kicad") -> SourceRef:
    return SourceRef(
        graph_entity_id=uuid.uuid5(_TEST_NS, f"{connector}:{external_ref}"),
        source_connector=connector,
        external_ref=external_ref,
    )


def obs(
    external_ref: str,
    modality: Modality,
    value: str,
    *,
    entity: str | None = None,
    manufacturer: str | None = None,
    footprint: str | None = None,
    connector: str = "kicad",
) -> Observation:
    source_ref = SourceRef(
        graph_entity_id=uuid.uuid5(_TEST_NS, f"{connector}:{external_ref}:{modality}"),
        source_connector=connector,
        external_ref=entity or external_ref,
    )
    return Observation(
        source_ref=source_ref,
        modality=modality,
        value=value,
        manufacturer=manufacturer,
        footprint=footprint,
    )


def only_part(output: FingerprintOutput) -> CanonicalPart:
    assert len(output.canonical_parts) == 1, output
    return output.canonical_parts[0]


# --- Grouping + rules table ---------------------------------------------------------


def test_exact_and_suffix_variants_collapse_to_base() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U2", Modality.PART_NUMBER, "LM358DR"),
        ],
        config=_CFG,
    )
    part = only_part(output)
    assert part.part_number == "LM358"
    assert part.canonical_id == canonical_uuid("LM358")
    states = {m.state for m in part.modalities}
    assert states == {MatchState.MATCHED}
    assert not output.unmatched and not output.ambiguous


def test_specific_symbol_corroborates_and_boosts_overall() -> None:
    with_symbol = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U1s", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358", entity="U1"),
        ],
        config=_CFG,
    )
    without_symbol = match([obs("U1", Modality.PART_NUMBER, "LM358")], config=_CFG)
    part = only_part(with_symbol)
    symbol_match = next(m for m in part.modalities if m.modality is Modality.SCHEMATIC_SYMBOL)
    assert symbol_match.state is MatchState.MATCHED
    assert part.confidence > only_part(without_symbol).confidence


def test_datasheet_corroborates_low_confidence_only() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U1d", Modality.DATASHEET, "https://www.ti.com/lit/ds/lm358.pdf", entity="U1"),
        ],
        config=_CFG,
    )
    part = only_part(output)
    datasheet_match = next(m for m in part.modalities if m.modality is Modality.DATASHEET)
    assert datasheet_match.state is MatchState.LOW_CONFIDENCE
    assert datasheet_match.confidence < _CFG.thresholds.matched
    assert part.datasheet_ref == "https://www.ti.com/lit/ds/lm358.pdf"


def test_datasheet_alone_never_merges() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U9", Modality.DATASHEET, "lm358.pdf"),
        ],
        config=_CFG,
    )
    part = only_part(output)
    assert {m.modality for m in part.modalities} == {Modality.PART_NUMBER}
    assert [r.external_ref for r in output.unmatched] == ["U9"]


def test_generic_symbol_is_near_zero_and_unmatched() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U2", Modality.PART_NUMBER, "TL072"),
            obs("U12", Modality.SCHEMATIC_SYMBOL, "OPAMP_Dual_Generic"),
        ],
        config=_CFG,
    )
    assert len(output.canonical_parts) == 2
    assert [r.external_ref for r in output.unmatched] == ["U12"]


def test_cad_model_is_unscored_and_photo_without_members_is_unmatched() -> None:
    """CAD_MODEL stays v1-unscored; a photo whose readings hit no existing
    part-number group contributes nothing (it can never mint a part)."""
    output = match(
        [
            obs("B1", Modality.CAD_MODEL, "JHD-0007-a1b2", connector="onshape"),
            obs("P1", Modality.PHOTO, "assets/photos/imu_top.jpg", connector="github"),
        ],
        config=_CFG,
    )
    assert not output.canonical_parts
    assert len(output.unmatched) == 2


def test_photo_corroborates_existing_part_low_confidence_only() -> None:
    """Containment rules 1+2: a photo reading matching an existing group
    attaches at the capped photo weight (always LOW_CONFIDENCE, so FP-02 never
    sets the FK) and evidence carries ALL readings."""
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("PH1", Modality.PHOTO, "LM358"),
        ],
        config=_CFG,
    )
    part = only_part(output)
    photo_match = next(m for m in part.modalities if m.modality is Modality.PHOTO)
    assert photo_match.state is MatchState.LOW_CONFIDENCE
    assert photo_match.confidence < _CFG.thresholds.matched
    assert photo_match.evidence["matched_on"] == "photo_marking"
    assert photo_match.evidence["readings"] == ["LM358"]
    # Structured members untouched (containment rule 3):
    pn_match = next(m for m in part.modalities if m.modality is Modality.PART_NUMBER)
    assert pn_match.state is MatchState.MATCHED


def test_photo_never_mints_a_canonical_part() -> None:
    output = match([obs("PH1", Modality.PHOTO, "LM358")], config=_CFG)
    assert not output.canonical_parts
    assert [r.external_ref for r in output.unmatched] == ["PH1"]


def test_photo_multiple_readings_are_ambiguous_never_a_winner() -> None:
    """One photo, two plausible readings hitting two parts → ONE ambiguous
    entry with both candidates; neither part gains a photo modality."""
    readings = [
        obs("PH1", Modality.PHOTO, "LM358", entity="PH1"),
        obs("PH1b", Modality.PHOTO, "LM386", entity="PH1"),
    ]
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U2", Modality.PART_NUMBER, "LM386"),
            *readings,
        ],
        config=_CFG,
    )
    assert len(output.ambiguous) == 1
    assert set(output.ambiguous[0].candidate_canonical_ids) == {
        canonical_uuid("LM358"),
        canonical_uuid("LM386"),
    }
    for part in output.canonical_parts:
        assert all(m.modality is not Modality.PHOTO for m in part.modalities)


def test_photo_never_anchors_to_seeded_bases() -> None:
    """Retrieval seeds cannot give a photo an attachment target."""
    output = match(
        [obs("PH1", Modality.PHOTO, "LM358")],
        config=_CFG,
        extra_candidate_bases=["LM358"],
    )
    assert not output.canonical_parts
    assert [r.external_ref for r in output.unmatched] == ["PH1"]


# --- Ambiguity: never best-of ---------------------------------------------------------


def test_symbol_naming_two_parts_is_ambiguous_with_candidates() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U2", Modality.PART_NUMBER, "LM2904"),
            obs("U60", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358_LM2904"),
        ],
        config=_CFG,
    )
    assert len(output.ambiguous) == 1
    ambiguous = output.ambiguous[0]
    assert set(ambiguous.candidate_canonical_ids) == {
        canonical_uuid("LM358"),
        canonical_uuid("LM2904"),
    }
    for part in output.canonical_parts:
        assert all(m.modality is Modality.PART_NUMBER for m in part.modalities)


def test_datasheet_disagreeing_with_entity_is_ambiguous() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U1d", Modality.DATASHEET, "tl072.pdf", entity="U1"),
            obs("U2", Modality.PART_NUMBER, "TL072"),
        ],
        config=_CFG,
    )
    assert len(output.ambiguous) == 1
    assert set(output.ambiguous[0].candidate_canonical_ids) == {
        canonical_uuid("LM358"),
        canonical_uuid("TL072"),
    }


def test_family_datasheet_naming_own_and_other_is_ambiguous() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U1d", Modality.DATASHEET, "lm358-lm2904.pdf", entity="U1"),
            obs("U2", Modality.PART_NUMBER, "LM2904"),
        ],
        config=_CFG,
    )
    assert len(output.ambiguous) == 1


# --- Visible conflicts within one part ------------------------------------------------


def test_package_conflict_is_visible_and_penalized() -> None:
    conflicted = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358N"),
            obs("U2", Modality.PART_NUMBER, "LM358D"),
        ],
        config=_CFG,
    )
    clean = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358N"),
            obs("U2", Modality.PART_NUMBER, "LM358N"),
        ],
        config=_CFG,
    )
    part = only_part(conflicted)
    assert all(m.evidence.get("conflict", {}).get("package") == ["D", "N"] for m in part.modalities)
    assert part.confidence < only_part(clean).confidence


def test_manufacturer_conflict_yields_none_field_and_evidence() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358", manufacturer="Texas Instruments"),
            obs("U2", Modality.PART_NUMBER, "LM358", manufacturer="STMicroelectronics"),
        ],
        config=_CFG,
    )
    part = only_part(output)
    assert part.manufacturer is None
    assert all("manufacturer" in m.evidence.get("conflict", {}) for m in part.modalities)


def test_unanimous_manufacturer_is_populated() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358", manufacturer="Texas Instruments"),
            obs("U2", Modality.PART_NUMBER, "LM358DR", manufacturer="Texas Instruments"),
        ],
        config=_CFG,
    )
    assert only_part(output).manufacturer == "Texas Instruments"


def test_footprint_conflict_never_splits_the_part() -> None:
    output = match(
        [
            obs(
                "U1s",
                Modality.SCHEMATIC_SYMBOL,
                "Amplifier_Operational:LM358",
                footprint="DIP-8",
            ),
            obs("U2", Modality.PART_NUMBER, "LM358DR", footprint="SOIC-8"),
        ],
        config=_CFG,
    )
    part = only_part(output)
    assert len(part.modalities) == 2
    assert any("footprint" in m.evidence.get("conflict", {}) for m in part.modalities)


def test_conflict_evidence_is_not_aliased_across_sibling_matches() -> None:
    """Frozen models don't freeze nested dicts: each match must carry its own
    copy so a future consumer mutating one can never corrupt its siblings."""
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358N"),
            obs("U2", Modality.PART_NUMBER, "LM358D"),
        ],
        config=_CFG,
    )
    first, second = only_part(output).modalities
    assert first.evidence["conflict"] == second.evidence["conflict"]
    assert first.evidence["conflict"] is not second.evidence["conflict"]
    assert first.evidence["conflict"]["package"] is not second.evidence["conflict"]["package"]


def test_multiple_conflict_classes_compound_the_penalty() -> None:
    """Three independent disagreement signals must not score like one."""
    one_conflict = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358N"),
            obs("U2", Modality.PART_NUMBER, "LM358D"),
        ],
        config=_CFG,
    )
    three_conflicts = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358N", manufacturer="TI", footprint="DIP-8"),
            obs("U2", Modality.PART_NUMBER, "LM358D", manufacturer="ST", footprint="SOIC-8"),
        ],
        config=_CFG,
    )
    assert only_part(three_conflicts).confidence < only_part(one_conflict).confidence


def test_order_invariance_holds_on_sort_key_ties() -> None:
    """Observations sharing one source_ref (same entity, no distinct ids) must
    still serialize identically regardless of input order."""
    shared = SourceRef(source_connector="kicad", external_ref="U1")

    def tied(value: str) -> Observation:
        return Observation(source_ref=shared, modality=Modality.PART_NUMBER, value=value)

    forward = match([tied("LM358"), tied("LM358DR")], config=_CFG)
    reverse = match([tied("LM358DR"), tied("LM358")], config=_CFG)
    assert forward.model_dump_json() == reverse.model_dump_json()

    def tied_symbol(value: str) -> Observation:
        return Observation(source_ref=shared, modality=Modality.SCHEMATIC_SYMBOL, value=value)

    base_parts = [
        obs("U2", Modality.PART_NUMBER, "LM358"),
        obs("U3", Modality.PART_NUMBER, "TL072"),
    ]
    ambiguous_a = tied_symbol("Amplifier_Operational:LM358_TL072")
    ambiguous_b = tied_symbol("Comparator:LM358_TL072")
    forward = match([*base_parts, ambiguous_a, ambiguous_b], config=_CFG)
    reverse = match([*base_parts, ambiguous_b, ambiguous_a], config=_CFG)
    assert forward.model_dump_json() == reverse.model_dump_json()


def test_stripped_suffix_delta_is_preserved_as_evidence() -> None:
    output = match([obs("U1", Modality.PART_NUMBER, "LM358DR")], config=_CFG)
    evidence = only_part(output).modalities[0].evidence
    assert evidence["package"] == "DR"
    assert evidence["value"] == "LM358DR"
    assert evidence["base"] == "LM358"


# --- Retrieval seam: similarity can never merge ---------------------------------------


def test_seeded_candidate_never_absorbs_distinct_identity() -> None:
    """A retriever proposing LM358 as 'similar' to LM3588 must change nothing:
    similarity is structurally unrepresentable — only exact base equality attaches."""
    seeded = match(
        [obs("U2", Modality.PART_NUMBER, "LM3588")],
        config=_CFG,
        extra_candidate_bases=["LM358"],
    )
    unseeded = match([obs("U2", Modality.PART_NUMBER, "LM3588")], config=_CFG)
    assert seeded == unseeded
    assert only_part(seeded).part_number == "LM3588"


def test_seeded_base_with_no_observations_emits_nothing() -> None:
    output = match(
        [obs("U1", Modality.PART_NUMBER, "LM358")],
        config=_CFG,
        extra_candidate_bases=["TL072"],
    )
    assert [p.part_number for p in output.canonical_parts] == ["LM358"]


def test_seeded_base_never_anchors_attachment() -> None:
    """A seed is not an in-run identity: a symbol whose only hit is a seed goes
    to unmatched — otherwise retrieval + symbol text could merge symbol-only
    entities into a part no part_number observation ever established."""
    output = match(
        [
            obs("U5", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358"),
            obs("U6", Modality.SCHEMATIC_SYMBOL, "Comparator:LM358"),
        ],
        config=_CFG,
        extra_candidate_bases=["LM358"],
    )
    assert not output.canonical_parts
    assert len(output.unmatched) == 2


def test_seeded_base_surfaces_ambiguity_without_dangling_candidates() -> None:
    """A seed hit alongside a member-backed hit makes the symbol AMBIGUOUS, and
    every candidate id references a part that actually exists in the output."""
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U60", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358_TL072"),
        ],
        config=_CFG,
        extra_candidate_bases=["TL072"],
    )
    (ambiguous,) = output.ambiguous
    part_ids = {part.canonical_id for part in output.canonical_parts}
    assert ambiguous.candidate_canonical_ids == [canonical_uuid("LM358")]
    assert set(ambiguous.candidate_canonical_ids) <= part_ids


# --- LLM proposals: capped, corroborating, never deciding ------------------------------


def test_llm_proposal_is_evidence_only_and_never_moves_buckets() -> None:
    """A proposal annotates the observation's OWN match with an auditable
    suggestion; the partition is byte-identical to the LLM-free run. This is
    the guard against a hallucinated/echoed 'same part' re-homing an
    adjudicated-distinct identity (e.g. AMS1117-3.3 into AMS1117-5.0)."""
    observations = [
        obs("U1", Modality.PART_NUMBER, "LM358"),
        obs("U2", Modality.PART_NUMBER, "XQZ1234PQ"),
    ]
    with_proposal = match(observations, config=_CFG, llm_proposals={"XQZ1234PQ": "LM358"})
    without_proposal = match(observations, config=_CFG)
    assert [p.part_number for p in with_proposal.canonical_parts] == ["LM358", "XQZ1234PQ"]
    assert [
        {frozenset(str(m.source_ref.graph_entity_id) for m in p.modalities)}
        for p in with_proposal.canonical_parts
    ] == [
        {frozenset(str(m.source_ref.graph_entity_id) for m in p.modalities)}
        for p in without_proposal.canonical_parts
    ]
    xqz_part = with_proposal.canonical_parts[1]
    evidence = xqz_part.modalities[0].evidence
    assert evidence["llm_proposed_base"] == "LM358"
    assert evidence["llm_derived"] is True
    assert xqz_part.modalities[0].state is MatchState.MATCHED  # its OWN deterministic identity


def test_llm_proposal_never_yields_llm_decided_state() -> None:
    """No LLM-derived signal produces any match state: adversarial proposals
    for every value leave states exactly as the deterministic rules set them."""
    observations = [
        obs("U1", Modality.PART_NUMBER, "AMS1117-3.3"),
        obs("U2", Modality.PART_NUMBER, "AMS1117-5.0"),
    ]
    output = match(
        observations,
        config=_CFG,
        llm_proposals={"AMS1117-3.3": "AMS11175.0", "AMS1117-5.0": "AMS11173.3"},
    )
    assert [p.part_number for p in output.canonical_parts] == ["AMS11173.3", "AMS11175.0"]


def test_llm_proposal_never_creates_a_group() -> None:
    """A proposal naming a base no deterministic observation established is
    no-signal: the plausible unknown stays its own group-of-one, and no LM358
    part materializes out of the LLM's imagination."""
    output = match(
        [obs("U2", Modality.PART_NUMBER, "XQZ1234PQ")],
        config=_CFG,
        llm_proposals={"XQZ1234PQ": "LM358"},
    )
    assert [p.part_number for p in output.canonical_parts] == ["XQZ1234PQ"]
    assert not output.unmatched


def test_match_with_escalation_calls_once_per_distinct_value() -> None:
    calls: list[str] = []

    async def escalate(value: str) -> str | None:
        calls.append(value)
        return "LM358"

    output = asyncio.run(
        match_with_escalation(
            [
                obs("U1", Modality.PART_NUMBER, "LM358"),
                obs("U2", Modality.PART_NUMBER, "XQZ1234PQ"),
                obs("U3", Modality.PART_NUMBER, "XQZ1234PQ"),
            ],
            escalate=escalate,
            config=_CFG,
        )
    )
    assert calls == ["XQZ1234PQ"]  # matched values never escalate; duplicates dedup
    assert not output.unmatched


def test_match_with_escalation_swallows_escalator_failure() -> None:
    async def escalate(value: str) -> str | None:
        raise RuntimeError("provider down")

    output = asyncio.run(
        match_with_escalation(
            [obs("U2", Modality.PART_NUMBER, "XQZ1234PQ")],
            escalate=escalate,
            config=_CFG,
        )
    )
    assert output == match([obs("U2", Modality.PART_NUMBER, "XQZ1234PQ")], config=_CFG)


# --- Output contract: interchangeable with the mock -------------------------------------


def test_output_round_trips_the_contract_serialization_path() -> None:
    output = match(
        [
            obs("U1", Modality.PART_NUMBER, "LM358"),
            obs("U1s", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358", entity="U1"),
            obs("U9", Modality.PART_NUMBER, "TBD"),
            obs("U60", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358_LM2904"),
            obs("U2", Modality.PART_NUMBER, "LM2904"),
        ],
        config=_CFG,
    )
    assert isinstance(output, FingerprintOutput)
    assert FingerprintOutput.model_validate_json(output.model_dump_json()) == output


def test_every_observation_lands_in_exactly_one_bucket() -> None:
    observations = [
        obs("U1", Modality.PART_NUMBER, "LM358"),
        obs("U1s", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358", entity="U1"),
        obs("U2", Modality.PART_NUMBER, "LM2904"),
        obs("U9", Modality.DATASHEET, "lm2904-n.pdf"),
        obs("U40", Modality.PART_NUMBER, "TBD"),
        obs("U60", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358_LM2904"),
    ]
    output = match(observations, config=_CFG)
    seen = [
        *(m.source_ref.graph_entity_id for p in output.canonical_parts for m in p.modalities),
        *(r.graph_entity_id for r in output.unmatched),
        *(a.source_ref.graph_entity_id for a in output.ambiguous),
    ]
    expected = [o.source_ref.graph_entity_id for o in observations]
    assert sorted(seen, key=str) == sorted(expected, key=str)


def test_empty_input_is_a_valid_empty_output() -> None:
    output = match([], config=_CFG)
    assert output == FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])


def test_output_is_deterministic_and_input_order_invariant() -> None:
    observations = [
        obs("U1", Modality.PART_NUMBER, "LM358"),
        obs("U2", Modality.PART_NUMBER, "NE555P"),
        obs("U3", Modality.PART_NUMBER, "TL072"),
        obs("U1s", Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358", entity="U1"),
        obs("U9", Modality.PART_NUMBER, "0805"),
    ]
    first = match(observations, config=_CFG)
    second = match(list(reversed(observations)), config=_CFG)
    assert first.model_dump_json() == second.model_dump_json()


# --- Boundary adapter --------------------------------------------------------------------


def test_observations_from_hints_maps_documented_keys() -> None:
    source_ref = ref("U1")
    observations = observations_from_hints(
        source_ref,
        {
            "part_number": "LM358DR",
            "schematic_symbol": "Amplifier_Operational:LM358",
            "datasheet": "lm358.pdf",
            "cad_model": "JHD-0007-a1b2",  # accepted; v1-unscored → lands in unmatched
            "unknown_key": "ignored",
            "photo": 42,  # non-str → skipped
        },
        manufacturer="Texas Instruments",
    )
    assert {(o.modality, o.value) for o in observations} == {
        (Modality.PART_NUMBER, "LM358DR"),
        (Modality.SCHEMATIC_SYMBOL, "Amplifier_Operational:LM358"),
        (Modality.DATASHEET, "lm358.pdf"),
        (Modality.CAD_MODEL, "JHD-0007-a1b2"),
    }
    assert all(o.source_ref == source_ref for o in observations)
    assert all(o.manufacturer == "Texas Instruments" for o in observations)


# --- Config safety validators -------------------------------------------------------------


def _config_data() -> dict[str, object]:
    return load_fingerprint_config().model_dump()


def test_llm_cap_must_stay_below_matched_threshold() -> None:
    data = _config_data()
    data["llm"]["confidence_cap"] = 0.85  # type: ignore[index]
    with pytest.raises(ValidationError, match="confidence_cap"):
        FingerprintConfig.model_validate(data)


def test_datasheet_weight_must_stay_below_matched_threshold() -> None:
    data = _config_data()
    data["weights"]["datasheet"] = 0.9  # type: ignore[index]
    with pytest.raises(ValidationError, match="datasheet"):
        FingerprintConfig.model_validate(data)


def test_generic_symbol_weight_must_stay_below_low_threshold() -> None:
    data = _config_data()
    data["weights"]["generic_symbol"] = 0.6  # type: ignore[index]
    with pytest.raises(ValidationError, match="generic_symbol"):
        FingerprintConfig.model_validate(data)


def test_thresholds_must_be_ordered() -> None:
    data = _config_data()
    data["thresholds"] = {"matched": 0.5, "low_confidence": 0.8}
    with pytest.raises(ValidationError, match="matched"):
        FingerprintConfig.model_validate(data)


def test_bad_family_regex_fails_at_load() -> None:
    data = _config_data()
    data["families"][0]["stem_pattern"] = "(unclosed"  # type: ignore[index]
    with pytest.raises(ValidationError, match="invalid regex"):
        FingerprintConfig.model_validate(data)


def test_photo_weight_must_stay_below_matched_threshold() -> None:
    data = _config_data()
    data["weights"]["photo"] = 0.9  # type: ignore[index]
    with pytest.raises(ValidationError, match="photo"):
        FingerprintConfig.model_validate(data)
