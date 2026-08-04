"""SOLUSDEV-100 T2b — `solus/write/locator.py`: finds the exact byte span of
one symbol property's value, and refuses (never guesses) on every ambiguous
or missing target."""

from pathlib import Path

import pytest
from paths import SOLUS_SAMPLE_SCH

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.write.errors import (  # isort: skip
    REASON_AMBIGUOUS_TARGET,
    REASON_FILE_TOO_LARGE,
    REASON_PROPERTY_NOT_FOUND,
    REASON_REFERENCE_NOT_FOUND,
    RefusalError,
)
from solus.write.locator import locate_property_value  # isort: skip

_MINIMAL_SCHEMATIC = b"""(kicad_sch
    (version 20250114)
    (lib_symbols
        (symbol "Device:R"
            (property "Reference" "R" (at 0 0 0))
            (property "Value" "R" (at 0 0 0))
        )
    )
    (symbol (lib_id "Device:R") (at 10 20 0) (unit 1)
        (uuid "aaaa")
        (property "Reference" "R1" (at 0 0 0))
        (property "Value" "10k" (at 0 0 0))
        (property "MPN" "RC0603FR-0710KL" (at 0 0 0))
    )
    (symbol (lib_id "Device:R") (at 30 40 0) (unit 1)
        (uuid "bbbb")
        (property "Reference" "R2" (at 0 0 0))
        (property "Value" "4.7k" (at 0 0 0))
    )
)
"""

_DUPLICATE_REFERENCE_SCHEMATIC = b"""(kicad_sch
    (symbol (lib_id "Device:R") (at 10 20 0) (unit 1)
        (property "Reference" "R1" (at 0 0 0))
        (property "Value" "10k" (at 0 0 0))
    )
    (symbol (lib_id "Device:R") (at 30 40 0) (unit 1)
        (property "Reference" "R1" (at 0 0 0))
        (property "Value" "4.7k" (at 0 0 0))
    )
)
"""

_DUPLICATE_PROPERTY_SCHEMATIC = b"""(kicad_sch
    (symbol (lib_id "Device:R") (at 10 20 0) (unit 1)
        (property "Reference" "R1" (at 0 0 0))
        (property "Value" "10k" (at 0 0 0))
        (property "Value" "20k" (at 0 0 0))
    )
)
"""


# --- happy path -------------------------------------------------------------------


def test_locates_the_value_token_byte_span() -> None:
    located = locate_property_value(_MINIMAL_SCHEMATIC, "R1", "Value")
    assert located.old_value == "10k"
    assert _MINIMAL_SCHEMATIC[located.start : located.end] == b'"10k"'


def test_locates_a_different_reference_and_property() -> None:
    located = locate_property_value(_MINIMAL_SCHEMATIC, "R1", "MPN")
    assert located.old_value == "RC0603FR-0710KL"


def test_never_matches_the_lib_symbols_definition_template() -> None:
    """The definition template's Reference is the generic "R", never a
    placed refdes — but even if a caller asked for reference "R" it must
    not resolve into lib_symbols (that section is a template, not an
    instance)."""
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(_MINIMAL_SCHEMATIC, "R", "Value")
    assert excinfo.value.reason == REASON_REFERENCE_NOT_FOUND


def test_locates_across_multiple_distinct_instances() -> None:
    located = locate_property_value(_MINIMAL_SCHEMATIC, "R2", "Value")
    assert located.old_value == "4.7k"


# --- refusals -----------------------------------------------------------------------


def test_refuses_an_unknown_reference() -> None:
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(_MINIMAL_SCHEMATIC, "R99", "Value")
    assert excinfo.value.reason == REASON_REFERENCE_NOT_FOUND


def test_refuses_an_unknown_property_on_a_known_reference() -> None:
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(_MINIMAL_SCHEMATIC, "R1", "Footprint")
    assert excinfo.value.reason == REASON_PROPERTY_NOT_FOUND


def test_refuses_a_duplicate_reference_as_ambiguous() -> None:
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(_DUPLICATE_REFERENCE_SCHEMATIC, "R1", "Value")
    assert excinfo.value.reason == REASON_AMBIGUOUS_TARGET


def test_refuses_a_duplicate_property_as_ambiguous() -> None:
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(_DUPLICATE_PROPERTY_SCHEMATIC, "R1", "Value")
    assert excinfo.value.reason == REASON_AMBIGUOUS_TARGET


def test_refuses_malformed_input_with_a_stable_reason() -> None:
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(b"(kicad_sch (unterminated", "R1", "Value")
    assert excinfo.value.reason == REASON_REFERENCE_NOT_FOUND


def test_refuses_pathological_nesting_depth_as_file_too_large() -> None:
    """M5: `GuardExceededError` (the sexpr resource guard) is mapped to the
    dedicated `file_too_large` reason — NOT folded into the generic
    `reference_not_found` bucket ordinary malformed syntax gets."""
    hostile = b"(" * 50_000 + b")" * 50_000
    with pytest.raises(RefusalError) as excinfo:
        locate_property_value(hostile, "R1", "Value")
    assert excinfo.value.reason == REASON_FILE_TOO_LARGE


# --- the real committed fixture ------------------------------------------------------


def test_locates_the_mpn_on_the_committed_solus_fixture() -> None:
    data = Path(SOLUS_SAMPLE_SCH).read_bytes()
    located = locate_property_value(data, "U1", "MPN")
    assert located.old_value == "STM32F030F4P6"
    assert data[located.start : located.end] == b'"STM32F030F4P6"'


def test_locates_a_second_component_on_the_committed_solus_fixture() -> None:
    data = Path(SOLUS_SAMPLE_SCH).read_bytes()
    located = locate_property_value(data, "R1", "Value")
    assert located.old_value == "4.7k"
