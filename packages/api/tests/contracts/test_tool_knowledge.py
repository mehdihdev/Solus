"""SOLUSDEV-220 (CTR-05) — the tool-knowledge boundary, Python half.

⚠ HIGHEST-RISK CONTRACT ON THE BOARD. This table is read by EVERY tenant, so
the tests that matter are not "does a valid record validate" — they are "can a
customer's part, dimension, file or document get in at all".

The TypeScript compile-time proof lives in
`packages/shared-types/src/tool-knowledge.illegal.ts` and runs under
`pnpm typecheck`. This file is the Python half, and it validates the SAME
fixtures the TypeScript runtime tests do.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.contracts.tool_knowledge import (
    MAX_VENDOR_TEXT,
    ControlEffect,
    Provenance,
    ToolFamily,
    ToolKnowledge,
    UiSurface,
)

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "tool-knowledge"

ALL = ["fusion-extrude", "kicad-net-label"]


def load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return loaded


def base() -> dict[str, Any]:
    return load("fusion-extrude")


def test_the_fixture_directory_is_the_one_typescript_reads() -> None:
    assert FIXTURES.is_dir(), FIXTURES
    assert (FIXTURES.parents[1] / "src" / "tool-knowledge.test.ts").is_file()
    # The compile-time proof must exist, or "structurally incapable" is prose.
    assert (FIXTURES.parents[1] / "src" / "tool-knowledge.illegal.ts").is_file()


@pytest.mark.parametrize("name", ALL)
def test_fixtures_validate(name: str) -> None:
    ToolKnowledge.model_validate(load(name))


# ── 1. The column set is closed ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "7c9e6679-7425-40de-944b-e07fc1f90ae7"),
        ("team_id", "7c9e6679-7425-40de-944b-e07fc1f90ae7"),
        ("entity_id", "1f0a2b3c-4d5e-4f60-8a91-b2c3d4e5f601"),
        ("document_id", "d/9a1c2ef4b7d80a3c5e6f1b29"),
        ("file_path", "/home/mehdi/robot/chassis.f3d"),
        ("properties", {"width_mm": 62}),
        ("attrs", {}),
        ("payload", "{}"),
        ("metadata", {}),
        ("notes", "the customer's gripper is 62mm wide"),
        ("screenshot_b64", "iVBORw0KGgo="),
        ("embedding", [0.1, 0.2]),
    ],
)
def test_no_field_exists_to_hold_customer_content(field: str, value: object) -> None:
    # extra="forbid". There is no `properties`, `attrs`, `metadata`, `payload`
    # or `notes` to put anything in — and no id of anything a customer owns.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), field: value})


# ── 2. Prose fields reject customer-shaped content ───────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "/home/mehdi/robot/chassis.f3d",
        "C:\\Users\\pratham\\Desktop\\arm_v3.sldprt",
        "~/designs/gripper.step",
        "https://cad.onshape.com/documents/9a1c2ef4b7d8",
        "d/9a1c2ef4b7d80a3c5e6f1b29",
        "w/1a2b3c/e/4d5e6f",
        "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "someone@example.com",
        "motor_mount.step",
        "62.5 mm",
        "24 AWG harness at 3.0 A",
    ],
)
@pytest.mark.parametrize("field", ["label", "description"])
def test_prose_fields_reject_customer_shapes(field: str, raw: str) -> None:
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), field: raw})


@pytest.mark.parametrize(
    "raw",
    [
        "Extrude",
        "Push/Pull",
        "Sketch Dimension",
        "Adds depth to a closed sketch profile, producing a solid or surface body.",
    ],
)
def test_prose_fields_accept_vendor_ui_text(raw: str) -> None:
    assert ToolKnowledge.model_validate({**base(), "label": raw}).label == raw


def test_prose_is_length_capped() -> None:
    # An unbounded string IS a blob field. The cap is part of the boundary.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), "description": "x" * (MAX_VENDOR_TEXT + 1)})


def test_prose_may_not_be_empty() -> None:
    for blank in ("", "   "):
        with pytest.raises(ValidationError):
            ToolKnowledge.model_validate({**base(), "label": blank})


# ── 3. The Onshape featurespecs trap ─────────────────────────────────────────


def test_an_imported_custom_feature_cannot_be_stored() -> None:
    # Prior work found Onshape's per-document `featurespecs` includes a
    # customer's IMPORTED CUSTOM FEATURES — vendor-looking data that is actually
    # customer content, arriving in exactly the fields a real control would use.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate(
            {
                **base(),
                "label": "Chassis Rib Pattern",
                "control_id": "d/9a1c2ef4b7d80a3c5e6f1b29",
                "provenance": "observed_ui",
            }
        )


def test_a_recent_file_menu_entry_cannot_be_stored() -> None:
    # "File > Open Recent > ~/designs/arm_v3.f3d" is a real vendor menu holding
    # real customer content; every segment is checked, not just the first.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate(
            {
                **base(),
                "invocation": {
                    "menu_path": ["File", "Open Recent", "~/designs/arm_v3.f3d"],
                    "shortcut": None,
                },
            }
        )


# ── 4. control_id is a slug, not a sentence ──────────────────────────────────


@pytest.mark.parametrize("raw", ["Extrude", "my part", "chassis.f3d", "d/9a1c2e", "", "A_B"])
def test_control_id_rejects_anything_that_is_not_a_slug(raw: str) -> None:
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), "control_id": raw})


def test_control_id_accepts_a_vendor_identifier() -> None:
    record = ToolKnowledge.model_validate({**base(), "control_id": "fusion.sketch.dimension"})
    assert record.control_id == "fusion.sketch.dimension"


# ── 5. Categorical fields are closed ─────────────────────────────────────────


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool", "customers_internal_cad"),
        ("surface", "wherever"),
        ("effect", "does_what_the_customer_asked"),
        ("provenance", "customer_project"),
    ],
)
def test_categorical_fields_are_enums_not_free_text(field: str, value: str) -> None:
    # A free-text category is a blob with extra steps.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), field: value})


def test_the_enums_match_the_typescript_vocabularies() -> None:
    assert [t.value for t in ToolFamily] == [
        "fusion",
        "onshape",
        "solidworks",
        "autocad",
        "kicad",
        "altium",
        "spice",
    ]
    assert [s.value for s in UiSurface] == [
        "toolbar",
        "menu",
        "context_menu",
        "panel",
        "dialog",
        "keyboard",
        "status_bar",
    ]
    assert [p.value for p in Provenance] == ["vendor_docs", "observed_ui", "operator_authored"]
    assert ControlEffect.CREATE_FEATURE.value == "create_feature"


def test_provenance_can_never_be_a_customer_project() -> None:
    # Not a lookup failure — there is no such member to select.
    assert "customer" not in {p.value for p in Provenance}


# ── 6. The locator is geometry, never pixels of someone's screen ─────────────


def test_a_locator_is_normalised() -> None:
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), "locator": {"x": 0.1, "y": 0.2, "w": 2, "h": 0.1}})


def test_a_locator_cannot_carry_an_image() -> None:
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate(
            {**base(), "locator": {"x": 0, "y": 0, "w": 1, "h": 1, "image_b64": "iVBORw0KGgo="}}
        )


def test_a_locator_may_be_absent() -> None:
    assert ToolKnowledge.model_validate({**base(), "locator": None}).locator is None


# ── 7. Versioning ────────────────────────────────────────────────────────────


def test_a_version_range_must_look_like_one() -> None:
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), "version_range": "the one Mehdi has"})


def test_the_model_is_frozen() -> None:
    # A record that could be mutated after validation is a record whose checks
    # describe a moment, not the value.
    record = ToolKnowledge.model_validate(base())
    with pytest.raises(ValidationError):
        record.label = "anything"


# ── SOLUSDEV-216 security review: the findings, asserted so they cannot return ──


@pytest.mark.parametrize(
    "raw",
    [
        "Net MOTOR_PWM_1 connects U3 pin 14 to Q2 gate on the power board",
        "Chassis/DriveArm/Gripper_v3/FingerLeft revision 7",
        "U29sdXNQcm9wcmlldGFyeVNjaGVtYXRpY0R1bXBWMQ" * 6,
        "Motor rated 250W at 3000RPM, 12psi clamp, 40Hz loop",
        "Decoupling 100nF and 10uF near U7, pullups 4k7, xtal 16MHz",
        "／home／mehdi／robot／chassis․f3d",
        "Users\\mehdi\\Documents\\robot\\chassis",
        "Battery pack 2200mAh",
        "Harness uses 24 AWG wire to the driver",
    ],
)
def test_customer_content_the_review_got_through_is_now_rejected(raw: str) -> None:
    # Every one of these passed model_validate before the review. The patterns
    # are still a BACKSTOP, not a filter — see the module warning — but these
    # specific shapes are the ones that leak by accident.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), "description": raw})


@pytest.mark.parametrize("raw", ["Extrude", "Push/Pull", "3D Sketch", "Sketch Dimension"])
def test_broadening_the_patterns_did_not_reject_real_vendor_text(raw: str) -> None:
    assert ToolKnowledge.model_validate({**base(), "label": raw}).label == raw


def test_the_pattern_list_is_shared_with_typescript_not_duplicated() -> None:
    # The two lists were hand-maintained and had already drifted (AWG was here
    # and not in TS). One file, loaded by both, is why that cannot recur.
    from solus_api.contracts.tool_knowledge import _SHAPES_FILE

    assert _SHAPES_FILE.is_file(), _SHAPES_FILE
    assert _SHAPES_FILE == FIXTURES / "customer-shapes.json"
    assert "AWG" in _SHAPES_FILE.read_text()


def test_version_range_cannot_be_used_to_burn_cpu() -> None:
    # 83 chars took 2.4 seconds against the old ambiguous regex; Python survived
    # only because of max_length, and 172 ms/record is still 1000x amplification.
    import time

    evil = "1" + "  1" * 30 + "!"
    started = time.perf_counter()
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate({**base(), "version_range": evil})
    assert (time.perf_counter() - started) < 0.05


def test_a_shortcut_may_not_smuggle_a_trailing_newline() -> None:
    # re.match + `$` matches before a trailing newline; TS rejected it and Python
    # stored 'E\n'. fullmatch closes the parity gap.
    with pytest.raises(ValidationError):
        ToolKnowledge.model_validate(
            {**base(), "invocation": {"menu_path": None, "shortcut": "E\n"}}
        )


def test_a_rejection_names_the_field_that_failed() -> None:
    # "why did this user's sync fail?" must be answerable from the error
    # (CLAUDE.md §6); both prose fields used to report the literal "text".
    with pytest.raises(ValidationError) as excinfo:
        ToolKnowledge.model_validate({**base(), "description": "/home/mehdi/chassis.f3d"})
    assert "description" in str(excinfo.value)


def test_a_part_name_in_prose_is_not_caught_and_the_doc_says_so() -> None:
    """The honest limit, pinned so nobody mistakes the backstop for a filter.

    "Hero Arm Bracket Rev C" is a customer part name and it VALIDATES. Two
    patterns that tried to catch this class were removed because they also
    rejected KiCad's "Net Label" menu item and "Revision History" — bare domain
    nouns cannot tell a vendor UI label from a design description.

    This is why LANE D's ingestion guard (SOLUS-TU-06) must allowlist at the
    source rather than lean on these patterns, and why the doc's "What this
    contract does not do" section is not boilerplate.
    """
    assert ToolKnowledge.model_validate({**base(), "description": "Hero Arm Bracket Rev C"})
