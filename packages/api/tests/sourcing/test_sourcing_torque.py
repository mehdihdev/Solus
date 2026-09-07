"""SOLUSDEV-246 (STORE ST5) — torque derivation is Solus arithmetic, never LLM arithmetic.

Static holding torque about a pivot from masses and lever arms, from a plain
spec ("holds 2 kg at 30 cm") or from an assembly's geometry (CAD placements)
and masses. Unknown masses are reported, never guessed.
"""

from __future__ import annotations

import math
import uuid

import pytest
from solus_api.sourcing.torque import (
    DEFAULT_SAFETY_FACTOR,
    AssemblyPart,
    G,
    Load,
    derive_torque,
    loads_from_assembly,
    torque_from_spec,
)


def test_spec_two_kilograms_at_thirty_centimetres() -> None:
    result = torque_from_spec(load_kg=2.0, arm_m=0.30)
    assert math.isclose(result.static_torque_nm, 2.0 * G * 0.30, rel_tol=1e-9)
    assert result.safety_factor == DEFAULT_SAFETY_FACTOR
    assert math.isclose(result.required_torque_nm, result.static_torque_nm * DEFAULT_SAFETY_FACTOR)
    assert result.unknown == ()
    assert any("static" in a.lower() for a in result.assumptions)


def test_loads_sum_and_unknown_masses_are_named_not_guessed() -> None:
    loads = [
        Load(name="arm", mass_kg=1.0, lever_arm_m=0.2),
        Load(name="gripper", mass_kg=0.5, lever_arm_m=0.4),
    ]
    result = derive_torque(loads, unknown=("camera",), safety_factor=2.0)
    assert math.isclose(result.static_torque_nm, G * (1.0 * 0.2 + 0.5 * 0.4))
    assert result.required_torque_nm == pytest.approx(result.static_torque_nm * 2.0)
    assert result.unknown == ("camera",)
    assert any("camera" in a for a in result.assumptions)
    assert [entry.name for entry in result.loads] == ["arm", "gripper"]


def test_loads_from_assembly_use_horizontal_distance_from_the_pivot_in_metres() -> None:
    pivot = (0.0, 0.0, 0.0)
    parts = [
        AssemblyPart(id=uuid.uuid4(), name="Arm link", mass_kg=1.2, position_mm=(300.0, 0.0, 50.0)),
        AssemblyPart(
            id=uuid.uuid4(), name="Gripper", mass_kg=0.4, position_mm=(300.0, 400.0, -20.0)
        ),
        AssemblyPart(id=uuid.uuid4(), name="Camera", mass_kg=None, position_mm=(100.0, 0.0, 0.0)),
        AssemblyPart(id=uuid.uuid4(), name="No placement", mass_kg=0.1, position_mm=None),
    ]
    loads, unknown = loads_from_assembly(parts, pivot_mm=pivot)
    assert [(load.name, round(load.lever_arm_m, 3)) for load in loads] == [
        ("Arm link", 0.3),
        ("Gripper", 0.5),
    ]
    assert unknown == ("Camera", "No placement")


def test_derive_torque_rejects_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        torque_from_spec(load_kg=-1, arm_m=0.1)
    with pytest.raises(ValueError):
        torque_from_spec(load_kg=1, arm_m=0.1, safety_factor=0.5)
    with pytest.raises(ValueError):
        derive_torque([Load(name="x", mass_kg=float("inf"), lever_arm_m=1.0)])


def test_result_is_a_plain_payload() -> None:
    payload = torque_from_spec(load_kg=2.0, arm_m=0.3).payload()
    assert set(payload) >= {
        "static_torque_nm",
        "required_torque_nm",
        "safety_factor",
        "loads",
        "unknown",
        "assumptions",
    }
    assert payload["loads"][0] == {"name": "load", "mass_kg": 2.0, "lever_arm_m": 0.3}
