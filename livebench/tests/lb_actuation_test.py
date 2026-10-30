"""The actuation seam (SOLUSDEV-319): what a driver's actuator promises teleop.

Structural conformance is checked by mypy through the annotated assignments below; the runtime
assertions pin the value types the loop relies on.
"""

import dataclasses

import pytest
from lb_teleop_test import FakeActuator
from livebench.hardware.actuation import ActuatedJoint, Actuator
from livebench.plugins.feetech.feetech_actuator import FeetechActuator


def test_feetech_and_the_test_fake_both_satisfy_the_actuator_protocol() -> None:
    real: Actuator = FeetechActuator()
    fake: Actuator = FakeActuator([], {})
    assert real is not fake


def test_actuated_joint_is_an_immutable_value() -> None:
    joint = ActuatedJoint(address=1, signal="a.position", unit="deg", span=(0, 10))
    with pytest.raises(dataclasses.FrozenInstanceError):
        joint.address = 2  # type: ignore[misc]
    assert joint == ActuatedJoint(1, "a.position", "deg", (0, 10))
