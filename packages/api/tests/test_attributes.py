"""Attribute-extraction contract (SOLUS-CHK-01, SOLUSDEV-115).

The rules' no-false-positive guarantee rests on these extractors being TOTAL and DEFENSIVE:
untrusted, connector-ingested attrs coerce to a clean value or None, never raise, and never
silently misread a bool as a number.
"""

from typing import Any
from uuid import uuid4

from solus_api.agent.interfaces import EntityRead
from solus_api.checkers import attributes as av


def _entity(attrs: dict[str, Any]) -> EntityRead:
    return EntityRead(id=uuid4(), kind="component", domain="electrical", name="X", attrs=attrs)


def test_attr_float_reads_numbers() -> None:
    e = _entity({"gbw_hz": 1_000_000, "current_max_a": 2.5})
    assert av.attr_float(e, av.GBW_HZ) == 1_000_000.0
    assert av.attr_float(e, av.CURRENT_MAX_A) == 2.5


def test_attr_float_coerces_numeric_strings() -> None:
    e = _entity({"voltage_nominal_v": "3.3"})
    assert av.attr_float(e, av.VOLTAGE_NOMINAL_V) == 3.3


def test_attr_float_missing_key_is_none() -> None:
    assert av.attr_float(_entity({}), av.GBW_HZ) is None


def test_attr_float_rejects_non_numeric_string() -> None:
    assert av.attr_float(_entity({"gbw_hz": "wide"}), av.GBW_HZ) is None


def test_attr_float_rejects_bool() -> None:
    # bool is an int subclass; True must NOT read as 1.0 volts.
    assert av.attr_float(_entity({"voltage_nominal_v": True}), av.VOLTAGE_NOMINAL_V) is None


def test_attr_float_rejects_non_finite() -> None:
    # nan/inf from untrusted attrs must NOT survive — every comparison with nan is False, which
    # would invert a rule's skip-logic into a fabricated violation.
    assert av.attr_float(_entity({"gbw_hz": "nan"}), av.GBW_HZ) is None
    assert av.attr_float(_entity({"gbw_hz": "inf"}), av.GBW_HZ) is None
    assert av.attr_float(_entity({"gbw_hz": "-inf"}), av.GBW_HZ) is None
    assert av.attr_float(_entity({"gbw_hz": "1e400"}), av.GBW_HZ) is None  # overflow -> inf
    assert av.attr_float(_entity({"gbw_hz": float("nan")}), av.GBW_HZ) is None


def test_attr_nonneg_float_rejects_negative() -> None:
    assert av.attr_nonneg_float(_entity({"current_draw_a": -1.0}), av.CURRENT_DRAW_A) is None
    assert av.attr_nonneg_float(_entity({"current_draw_a": 0.0}), av.CURRENT_DRAW_A) == 0.0
    assert av.attr_nonneg_float(_entity({"current_draw_a": 2.5}), av.CURRENT_DRAW_A) == 2.5
    assert av.attr_nonneg_float(_entity({}), av.CURRENT_DRAW_A) is None


def test_attr_str_reads_strings_only() -> None:
    assert av.attr_str(_entity({"part_class": "op_amp"}), av.PART_CLASS) == "op_amp"
    assert av.attr_str(_entity({"part_class": 5}), av.PART_CLASS) is None


def test_part_class_helper() -> None:
    assert av.part_class(_entity({"part_class": "supply"})) == av.SUPPLY
    assert av.part_class(_entity({})) is None


def test_default_voltage_tolerance_is_positive() -> None:
    assert av.DEFAULT_VOLTAGE_TOLERANCE_PCT > 0
