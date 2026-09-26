"""Internal extraction evidence preserves facts and uncertainty without acquiring anything."""

import json
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.hardware.topology_evidence import (
    MAX_BATCH_BYTES,
    MAX_NOTES,
    MAX_PROVENANCE,
    MAX_ROWS,
    TopologyEvidence,
    TopologyExtraction,
    TopologyProvenance,
)


def _row(**changes: object) -> TopologyEvidence:
    return TopologyEvidence.model_validate(
        {
            "source_namespace": "schematic:a",
            "source_ref": "net:1",
            "bus": "I2C_A",
            "address": "0x2A",
            "provenance": [{"source_ref": "net:1", "entity_ref": "chip:1", "pin_ref": "SDA/3"}],
            **changes,
        }
    )


def test_unknowns_and_original_pin_and_address_text_remain_intact() -> None:
    row = _row()
    assert row.device is None and row.protocol is None and row.part_candidate is None
    assert row.confidence is None
    assert row.address == "0x2A" and row.provenance[0].pin_ref == "SDA/3"
    assert row.source_namespace == "schematic:a" and row.source_ref == "net:1"


def test_canonical_order_and_exact_duplicates_include_nested_provenance() -> None:
    first = _row()
    other = TopologyProvenance(source_ref="net:2", pin_ref="04")
    rich = first.model_dump()
    rich["provenance"] = [other.model_dump(), first.provenance[0].model_dump(), other.model_dump()]
    reordered = {**rich, "provenance": list(reversed(rich["provenance"]))}
    a = TopologyExtraction(source_kind="schematic", status="success", rows=(first, _row(**rich)))
    b = TopologyExtraction.model_validate(
        {
            "source_kind": "schematic",
            "status": "success",
            "rows": [reordered, first.model_dump(), rich],
        }
    )
    assert a == b
    assert len(a.rows) == 2
    assert len(next(row for row in a.rows if len(row.provenance) > 1).provenance) == 2
    assert a.model_dump_json() == b.model_dump_json()


def test_same_address_different_bus_source_or_candidate_remains_separate() -> None:
    rows = (
        _row(),
        _row(bus="I2C_B"),
        _row(source_namespace="schematic:b"),
        _row(source_ref="net:2"),
        _row(part_candidate="part:A"),
        _row(part_candidate="part:B"),
    )
    batch = TopologyExtraction(source_kind="schematic", status="success", rows=rows)
    assert len(batch.rows) == 6
    assert {row.address for row in batch.rows} == {"0x2A"}


@pytest.mark.parametrize("kind", ["firmware", "host_config", "onboard", "schematic"])
def test_empty_success_is_distinct_from_unavailable_and_invalid(kind: str) -> None:
    batches = [
        TopologyExtraction.model_validate({"source_kind": kind, "status": status})
        for status in ("success", "unavailable", "invalid")
    ]
    assert len({batch.status for batch in batches}) == 3
    assert all(batch.rows == () for batch in batches)


@pytest.mark.parametrize("status", ["unavailable", "invalid"])
def test_failed_extraction_cannot_hide_partial_candidates(status: str) -> None:
    with pytest.raises(ValidationError):
        TopologyExtraction.model_validate(
            {"source_kind": "firmware", "status": status, "rows": [_row()]}
        )


def test_confidence_requires_evidence_and_remains_optional() -> None:
    assert _row(confidence=0.0).confidence == 0.0
    assert _row(confidence=1).confidence == 1.0
    assert _row(provenance=()).confidence is None
    with pytest.raises(ValidationError):
        _row(provenance=(), confidence=0.5)


@pytest.mark.parametrize(
    "confidence", [float("nan"), float("inf"), -float("inf"), -0.1, 1.1, True, "0.5"]
)
def test_invalid_confidence_is_rejected(confidence: object) -> None:
    with pytest.raises(ValidationError):
        _row(confidence=confidence)


def test_all_containers_and_models_are_immutable() -> None:
    row = _row()
    batch = TopologyExtraction(
        source_kind="firmware", status="success", rows=[row], notes=["observed"]
    )
    assert isinstance(batch.rows, tuple) and isinstance(batch.notes, tuple)
    assert isinstance(row.provenance, tuple)
    with pytest.raises(ValidationError):
        row.address = "0x01"
    with pytest.raises(ValidationError):
        row.provenance[0].pin_ref = "4"
    with pytest.raises(ValidationError):
        batch.rows = ()


def test_unknown_fields_rejected_at_all_levels() -> None:
    with pytest.raises(ValidationError):
        _row(accepted=True)
    with pytest.raises(ValidationError):
        TopologyProvenance.model_validate({"source_ref": "a", "execute": "command"})
    with pytest.raises(ValidationError):
        TopologyExtraction.model_validate(
            {"source_kind": "onboard", "status": "success", "execute": "command"}
        )


def test_collection_limits_apply_before_deduplication() -> None:
    with pytest.raises(ValidationError):
        TopologyExtraction(source_kind="onboard", status="success", rows=[_row()] * (MAX_ROWS + 1))
    with pytest.raises(ValidationError):
        _row(provenance=[{"source_ref": "same"}] * (MAX_PROVENANCE + 1))
    with pytest.raises(ValidationError):
        TopologyExtraction(
            source_kind="firmware", status="success", notes=["same"] * (MAX_NOTES + 1)
        )


@pytest.mark.parametrize(
    "field",
    ["bus", "device", "protocol", "address", "part_candidate", "source_namespace", "source_ref"],
)
def test_every_row_string_is_bounded(field: str) -> None:
    with pytest.raises(ValidationError):
        _row(**{field: "x" * 2049})


@pytest.mark.parametrize("field", ["source_ref", "entity_ref", "pin_ref", "detail"])
def test_every_provenance_string_is_bounded(field: str) -> None:
    with pytest.raises(ValidationError):
        TopologyProvenance.model_validate({"source_ref": "source", field: "x" * 2049})


def test_batch_total_byte_limit_applies_to_input_before_deduplication() -> None:
    raw = {
        "source_kind": "firmware",
        "status": "success",
        "rows": [_row(device="x" * 512, bus="b" * 512).model_dump()] * MAX_ROWS,
        "notes": ["z" * 2048] * MAX_NOTES,
    }
    assert len(json.dumps(raw, separators=(",", ":")).encode()) > MAX_BATCH_BYTES
    with pytest.raises(ValidationError):
        TopologyExtraction.model_validate(raw)


def test_notes_deduplicate_and_sort_without_rewriting_text() -> None:
    batch = TopologyExtraction(source_kind="firmware", status="success", notes=(" z ", "a", " z "))
    assert batch.notes == (" z ", "a")
    with pytest.raises(ValidationError):
        TopologyExtraction(source_kind="firmware", status="success", notes=("x" * 2049,))


@pytest.mark.parametrize("rows", ["bad", {"row": 1}, iter(())])
def test_only_bounded_concrete_input_collections_are_accepted(rows: object) -> None:
    with pytest.raises(ValidationError):
        TopologyExtraction.model_validate(
            {"source_kind": "onboard", "status": "success", "rows": rows}
        )


def test_non_json_and_nonfinite_nested_values_are_refused() -> None:
    for bad in (object(), float("nan")):
        with pytest.raises(ValidationError):
            TopologyExtraction.model_validate(
                {"source_kind": "onboard", "status": "success", "rows": [{"source_ref": bad}]}
            )


@pytest.mark.parametrize("bad", ["provenance", "row_string", "notes", "header", "extra"])
def test_nested_limits_are_checked_before_serializing(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    raw: dict[str, Any] = {
        "source_kind": "firmware",
        "status": "success",
        "rows": [_row().model_dump()],
    }
    if bad == "provenance":
        raw["rows"][0]["provenance"] *= MAX_PROVENANCE + 1
    elif bad == "row_string":
        raw["rows"][0]["device"] = "x" * 513
    elif bad == "notes":
        raw["notes"] = ["x" * 2049]
    elif bad == "header":
        raw["source_kind"] = "x" * 2049
    else:
        raw["unexpected"] = {"deep": ["x"] * 1000}

    def forbidden_encoding(*args: object, **kwargs: object) -> object:
        raise RuntimeError("oversized evidence reached JSON serialization")

    monkeypatch.setattr(json.JSONEncoder, "iterencode", forbidden_encoding)
    with pytest.raises(ValidationError):
        TopologyExtraction.model_validate(raw)
