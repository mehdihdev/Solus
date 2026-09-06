"""SOLUSDEV-246 (STORE ST5) — compliance / style rules: typed, layered, deterministic.

Solus code decides an exclusion and the reason shown is the rule's own text —
never a model's judgement. Rules layer: defaults ← the repo `[ext.sourcing]`
table (scalars) ← the project's rules document.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from solus_api.sourcing.candidates import Candidate
from solus_api.sourcing.rules import (
    ExcludedSupplier,
    SourcingRules,
    apply_rules,
    rules_from_repo_table,
)


def cand(**over: object) -> Candidate:
    base: dict[str, object] = {
        "id": "c1",
        "name": "NEMA 17 stepper",
        "manufacturer": "StepperOnline",
        "supplier": "StepperOnline",
        "torque_nm": 0.59,
        "voltage_v": 12.0,
        "protocol": "step/dir",
        "certifications": ["RoHS", "CE"],
        "optimizes_for": "cost",
        "gives_up": "torque density",
        "source_url": "https://www.omc-stepperonline.com/17hs4401",
    }
    base.update(over)
    return Candidate.model_validate(base)


def test_rules_are_typed_and_capped() -> None:
    rules = SourcingRules(
        excluded_suppliers=[ExcludedSupplier(name="Acme Motors", reason="export controlled")],
        required_certifications=["RoHS"],
        max_voltage_v=24,
        allowed_protocols=["CAN", "step/dir"],
        preferred_suppliers=["Mouser"],
    )
    assert rules.excluded_suppliers[0].reason == "export controlled"
    with pytest.raises(ValidationError):
        SourcingRules(max_voltage_v=-1)
    with pytest.raises(ValidationError):
        SourcingRules(excluded_suppliers=[ExcludedSupplier(name="", reason="x")])
    with pytest.raises(ValidationError):
        SourcingRules.model_validate({"unknown": 1})


def test_an_excluded_supplier_is_removed_with_the_rule_text_as_the_reason() -> None:
    rules = SourcingRules(
        excluded_suppliers=[ExcludedSupplier(name="acme motors", reason="Export-controlled vendor")]
    )
    included, excluded = apply_rules(
        [cand(id="a", supplier="Acme Motors Ltd"), cand(id="b", supplier="Mouser")], rules
    )
    assert [c.id for c in included] == ["b"]
    assert [(c.id, reasons) for c, reasons in excluded] == [
        ("a", ["Supplier 'Acme Motors Ltd' is excluded: Export-controlled vendor"])
    ]


def test_voltage_protocol_and_certification_rules() -> None:
    rules = SourcingRules(
        required_certifications=["RoHS", "UL"],
        max_voltage_v=24,
        allowed_protocols=["CAN"],
    )
    included, excluded = apply_rules(
        [
            cand(id="ok", voltage_v=24, protocol="CAN", certifications=["RoHS", "UL"]),
            cand(id="hot", voltage_v=48, protocol="CAN", certifications=["RoHS", "UL"]),
            cand(id="proto", voltage_v=12, protocol="PWM", certifications=["RoHS", "UL"]),
            cand(id="cert", voltage_v=12, protocol="CAN", certifications=["RoHS"]),
            cand(id="unknown", voltage_v=None, protocol=None, certifications=[]),
        ],
        rules,
    )
    assert [c.id for c in included] == ["ok", "unknown"]
    by_id = {c.id: reasons for c, reasons in excluded}
    assert by_id["hot"] == ["Voltage 48.0 V exceeds the project maximum of 24.0 V"]
    assert by_id["proto"] == ["Protocol 'PWM' is not allowed; allowed: CAN"]
    assert by_id["cert"] == ["Missing required certification: UL"]
    # Unknown facts never exclude — they are flagged, not judged.
    unknown = next(c for c in included if c.id == "unknown")
    assert unknown.flags == [
        "Voltage unknown (project maximum 24.0 V)",
        "Protocol unknown (allowed: CAN)",
        "Certifications unknown (required: RoHS, UL)",
    ]


def test_preferred_suppliers_rank_first_without_excluding() -> None:
    rules = SourcingRules(preferred_suppliers=["Mouser"])
    included, excluded = apply_rules(
        [cand(id="a", supplier="StepperOnline"), cand(id="b", supplier="Mouser Electronics")], rules
    )
    assert [c.id for c in included] == ["b", "a"]
    assert excluded == []
    assert next(c for c in included if c.id == "b").flags == ["Preferred supplier"]


def test_repo_table_scalars_parse_into_rules() -> None:
    rules = rules_from_repo_table(
        {
            "excluded_suppliers": "Acme Motors: export controlled; Foo Parts",
            "required_certifications": "RoHS, CE",
            "max_voltage_v": 24,
            "allowed_protocols": "CAN, step/dir",
            "preferred_suppliers": "Mouser",
            "bogus": "ignored",
        }
    )
    assert [(e.name, e.reason) for e in rules.excluded_suppliers] == [
        ("Acme Motors", "export controlled"),
        ("Foo Parts", "Excluded by the project's .solus rules"),
    ]
    assert rules.required_certifications == ["RoHS", "CE"]
    assert rules.max_voltage_v == 24
    assert rules.allowed_protocols == ["CAN", "step/dir"]
    assert rules.preferred_suppliers == ["Mouser"]


def test_repo_table_with_wrong_types_yields_empty_rules() -> None:
    rules = rules_from_repo_table({"max_voltage_v": "high", "excluded_suppliers": 12})
    assert rules == SourcingRules()
