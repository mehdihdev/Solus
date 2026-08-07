"""CTR-08 hardware-recognition modalities: contract proof for the W0-06 forward amendment.

Robot-runtime recognition reuses THIS contract instead of a second identity mechanism.
Three additive `Modality` members carry the hardware evidence; the fixture proves the
important property — ambiguity stays visible (the telemetry case links NOTHING).
"""

from pathlib import Path

from solus_api.fingerprint.contract import FingerprintOutput, MatchState, Modality

_FIXTURE = Path(__file__).with_name("fixtures") / "hardware_modalities.json"


def _load_hardware_fixture() -> FingerprintOutput:
    return FingerprintOutput.model_validate_json(_FIXTURE.read_text())


def test_modality_extension_is_additive() -> None:
    # Original five first, order preserved — existing consumers see nothing moved.
    assert [m.value for m in Modality] == [
        "part_number",
        "datasheet",
        "schematic_symbol",
        "cad_model",
        "photo",
        "bus_enumeration",
        "firmware_symbol",
        "telemetry_channel",
    ]


def test_hardware_fixture_round_trips() -> None:
    output = _load_hardware_fixture()
    assert FingerprintOutput.model_validate_json(output.model_dump_json()) == output


def test_bus_enumerated_servo_is_matched() -> None:
    output = _load_hardware_fixture()
    (xm430,) = [cp for cp in output.canonical_parts if cp.part_number == "XM430-W350"]
    (match,) = xm430.modalities
    assert match.modality is Modality.BUS_ENUMERATION
    assert match.state is MatchState.MATCHED
    assert match.confidence >= 0.9


def test_firmware_inferred_servo_is_low_confidence() -> None:
    output = _load_hardware_fixture()
    (xl330,) = [cp for cp in output.canonical_parts if cp.part_number == "XL330-M288"]
    (match,) = xl330.modalities
    assert match.modality is Modality.FIRMWARE_SYMBOL
    assert match.state is MatchState.LOW_CONFIDENCE
    assert match.confidence < 0.80


def test_ambiguous_telemetry_stays_unlinked() -> None:
    """The load-bearing case: ambiguity stays VISIBLE — never guessed into a link."""
    output = _load_hardware_fixture()
    (amb,) = output.ambiguous

    linked_refs = {m.source_ref for cp in output.canonical_parts for m in cp.modalities}
    assert amb.source_ref not in linked_refs  # links nothing
    assert amb.source_ref not in set(output.unmatched)  # visible as AMBIGUOUS, not demoted

    assert not any(
        m.modality is Modality.TELEMETRY_CHANNEL
        for cp in output.canonical_parts
        for m in cp.modalities
    )  # telemetry evidence never attaches in this fixture

    known = {cp.canonical_id for cp in output.canonical_parts}
    assert len(amb.candidate_canonical_ids) >= 2
    assert set(amb.candidate_canonical_ids) <= known  # candidates are real parts
