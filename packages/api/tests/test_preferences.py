"""SOLUSDEV-244 / HOME H3 — the engineering-preferences request schema.

The desktop attaches the user's `~/.solus/preferences.json` to each SOL turn.
The server keeps no copy (ADR-034 amendment 2026-09-06): this schema is the
request-boundary twin of the shared-types parser — same fields, same caps,
strict shape — and `prompt_payload()` is the ONLY thing that reaches the prompt
builder: labelled, non-empty sections, never the raw document.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from solus_api.agent.preferences import (
    PREFERENCE_FIELD_CAP,
    PREFERENCE_FREE_TEXT_CAP,
    PREFERENCE_LABELS,
    EngineeringPreferences,
)

FULL = {
    "schema_version": 1,
    "updatedAt": "2026-09-06T12:00:00Z",
    "freeText": "Prefer 0.1 mm clearance minimum on all boards.",
    "codeStyle": "C++17, no dynamic allocation in ISRs.",
    "mechanical": "Metric fasteners only.",
    "electrical": "JST-GH for signal, XT30 for power.",
    "documentation": "One-page bring-up note per board.",
    "unitsStandards": "SI units; ISO 2768-m.",
}
EMPTY = {
    "schema_version": 1,
    "freeText": "",
    "codeStyle": "",
    "mechanical": "",
    "electrical": "",
    "documentation": "",
    "unitsStandards": "",
}


def test_caps_match_the_shared_contract() -> None:
    assert PREFERENCE_FIELD_CAP == 800
    assert PREFERENCE_FREE_TEXT_CAP == 2_400
    # The whole document at cap fits under the prompt's 8 000-char block cap.
    assert PREFERENCE_FREE_TEXT_CAP + 5 * PREFERENCE_FIELD_CAP < 8_000


def test_the_desktop_document_validates_verbatim() -> None:
    prefs = EngineeringPreferences.model_validate(FULL)
    assert prefs.free_text == FULL["freeText"]
    assert prefs.electrical == FULL["electrical"]
    assert prefs.model_dump(by_alias=True, exclude_none=True) == FULL


def test_every_section_defaults_to_empty_so_a_partial_body_is_fine() -> None:
    prefs = EngineeringPreferences.model_validate({"electrical": "XT30 for power."})
    assert prefs.is_empty() is False
    assert prefs.prompt_payload() == {"Electrical": "XT30 for power."}


def test_an_empty_document_is_empty_and_produces_no_payload() -> None:
    prefs = EngineeringPreferences.model_validate(EMPTY)
    assert prefs.is_empty() is True
    assert prefs.prompt_payload() == {}
    assert EngineeringPreferences.model_validate({"freeText": "   \n"}).is_empty() is True


def test_prompt_payload_is_labelled_and_ordered_sections_then_notes() -> None:
    payload = EngineeringPreferences.model_validate(FULL).prompt_payload()
    assert list(payload) == [
        "Code style",
        "Mechanical",
        "Electrical",
        "Documentation",
        "Units and standards",
        "Notes",
    ]
    assert payload["Notes"] == FULL["freeText"]
    assert set(PREFERENCE_LABELS.values()) >= set(payload) - {"Notes"}


def test_prompt_payload_strips_and_skips_blank_sections() -> None:
    payload = EngineeringPreferences.model_validate(
        {**EMPTY, "mechanical": "  6061-T6  ", "documentation": "   "}
    ).prompt_payload()
    assert payload == {"Mechanical": "6061-T6"}


@pytest.mark.parametrize(
    "body",
    [
        {**EMPTY, "toggles": {"dark": True}},
        {**EMPTY, "electrical": 3},
        {**EMPTY, "schema_version": 0},
        {**EMPTY, "schema_version": "1"},
        {**EMPTY, "updatedAt": 5},
        {**EMPTY, "electrical": "e" * (PREFERENCE_FIELD_CAP + 1)},
        {**EMPTY, "freeText": "f" * (PREFERENCE_FREE_TEXT_CAP + 1)},
        "not a document",
    ],
    ids=[
        "unknown-field",
        "non-string-section",
        "zero-version",
        "string-version",
        "non-string-updatedAt",
        "field-over-cap",
        "free-text-over-cap",
        "not-an-object",
    ],
)
def test_strict_rejection(body: object) -> None:
    with pytest.raises(ValidationError):
        EngineeringPreferences.model_validate(body)


def test_at_cap_is_accepted() -> None:
    prefs = EngineeringPreferences.model_validate(
        {
            **EMPTY,
            "electrical": "e" * PREFERENCE_FIELD_CAP,
            "freeText": "f" * PREFERENCE_FREE_TEXT_CAP,
        }
    )
    assert len(prefs.electrical) == PREFERENCE_FIELD_CAP
