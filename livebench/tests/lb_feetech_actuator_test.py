"""Feetech actuation (SOLUSDEV-319 teleop, ADR-014 amendment 2026-10-30).

The driver's actuator shares the polling source's bus — one master, one request outstanding —
and converts between calibrated values and goal ticks exactly as the source converts readings.
Goals never leave a joint's calibrated range; torque on always holds the present pose first.
"""

import uuid

import pytest
from lb_feetech_codec_test import FeetechFakeChannel
from livebench.hardware.actuation import ActuatorUnavailableError, ActuatorWriteError
from livebench.plugins.feetech.feetech_actuator import FeetechActuator
from livebench.plugins.feetech.feetech_definitions import STS_CONTROL_TABLE
from livebench.plugins.feetech.feetech_driver import (
    FeetechPacketSource,
    FeetechParams,
    FeetechStsDriver,
)
from solus_api.hardware.config import (
    BusMapEntry,
    CalibrationMode,
    FieldProvenance,
    HardwareConfig,
    PartCalibration,
    PartConfig,
    ProtocolBinding,
    ProvenanceRecord,
    TelemetryChannel,
    TransportBinding,
    TransportKind,
)

DRIVER = "feetech-sts"
GOAL = STS_CONTROL_TABLE["Goal_Position"].address
TORQUE = STS_CONTROL_TABLE["Torque_Enable"].address
SHOULDER, GRIPPER = uuid.uuid4(), uuid.uuid4()
_USER = ProvenanceRecord(by=FieldProvenance.USER)


def _arm(*, drive_mode: int = 0) -> HardwareConfig:
    return HardwareConfig(
        robot_entity_id=uuid.uuid4(),
        identity=TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B79050331"),
        protocol=ProtocolBinding(driver_id=DRIVER, params={}),
        bus_map=[
            BusMapEntry(protocol=DRIVER, address="1", part_entity_id=SHOULDER, model="STS3215"),
            BusMapEntry(protocol=DRIVER, address="6", part_entity_id=GRIPPER, model="STS3215"),
            BusMapEntry(protocol=DRIVER, address="3"),
        ],
        parts={
            str(SHOULDER): PartConfig(
                calibration=PartCalibration(
                    mode=CalibrationMode.DEGREES, values={"range_min": 700, "range_max": 3300}
                ),
                telemetry=[TelemetryChannel(name="arm-shoulder_pan.position", unit="deg")],
            ),
            str(GRIPPER): PartConfig(
                calibration=PartCalibration(
                    mode=CalibrationMode.RANGE_0_100,
                    values={"range_min": 2036, "range_max": 3486, "drive_mode": drive_mode},
                ),
                telemetry=[TelemetryChannel(name="arm-gripper.position", unit="%")],
            ),
        },
        provenance={"identity": _USER, "protocol": _USER, "bus_map": _USER, "parts": _USER},
    )


def _opened(
    channel: FeetechFakeChannel, config: HardwareConfig
) -> tuple[FeetechStsDriver, FeetechPacketSource, FeetechActuator]:
    driver = FeetechStsDriver()
    source = driver.open(channel, FeetechParams(), config)
    actuator = driver.actuator(config)
    assert actuator is not None
    return driver, source, actuator


def test_joints_describe_signal_unit_and_calibrated_range() -> None:
    _, _, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100, 3: 1000}), _arm())
    joints = {j.address: j for j in actuator.joints()}
    assert (joints[1].mode, joints[6].mode, joints[3].mode) == ("degrees", "range_0_100", None)
    assert joints[1].signal == "arm-shoulder_pan.position"
    assert (joints[1].unit, joints[1].span) == ("deg", (700, 3300))
    assert (joints[6].unit, joints[6].span) == ("%", (2036, 3486))
    assert (joints[3].unit, joints[3].span) == ("tick", None)  # uncalibrated: never actuated


def test_goal_inverts_the_reading_conversion() -> None:
    _, _, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100}), _arm())
    for address, ticks in ((1, 1234), (1, 3000), (6, 2500), (6, 3486)):
        assert actuator.to_goal(address, actuator.to_value(address, ticks)) == ticks


@pytest.mark.parametrize("drive_mode", [0, 1])
def test_goal_respects_drive_mode(drive_mode: int) -> None:
    _, _, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100}), _arm(drive_mode=drive_mode))
    closed = actuator.to_goal(6, 0.0)
    assert closed == (3486 if drive_mode else 2036)


def test_goals_clamp_into_the_calibrated_range() -> None:
    _, _, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100}), _arm())
    assert actuator.to_goal(1, 720.0) == 3300
    assert actuator.to_goal(1, -720.0) == 700
    assert actuator.to_goal(6, 150.0) == 3486


def test_uncalibrated_joint_has_no_goal() -> None:
    _, _, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100, 3: 1000}), _arm())
    with pytest.raises(ValueError):
        actuator.to_goal(3, 0.0)


def test_write_goals_writes_every_goal_and_fails_loudly_on_a_dropped_ack() -> None:
    channel = FeetechFakeChannel({1: 2000, 6: 2100})
    _, _, actuator = _opened(channel, _arm())
    actuator.write_goals({1: 2010, 6: 2200})
    assert [(i, v) for i, reg, v in channel.writes if reg == GOAL] == [(1, 2010), (6, 2200)]
    channel.silent_writes.add(6)
    with pytest.raises(ActuatorWriteError):
        actuator.write_goals({1: 2020, 6: 2210})


def test_write_goals_refuses_a_goal_outside_the_range() -> None:
    channel = FeetechFakeChannel({1: 2000, 6: 2100})
    _, _, actuator = _opened(channel, _arm())
    with pytest.raises(ValueError):
        actuator.write_goals({1: 3400})
    assert channel.writes == []


def test_hold_writes_present_pose_before_torque_on() -> None:
    channel = FeetechFakeChannel({1: 2000, 6: 2100, 3: 1000})
    _, _, actuator = _opened(channel, _arm())
    held = actuator.hold()
    assert held == {1: 2000, 6: 2100}  # calibrated joints only
    goals = [(i, v) for i, reg, v in channel.writes if reg == GOAL]
    torque = [(i, v) for i, reg, v in channel.writes if reg == TORQUE]
    assert goals == [(1, 2000), (6, 2100)] and torque == [(1, 1), (6, 1)]
    assert channel.writes.index((1, TORQUE, 1)) > channel.writes.index((6, GOAL, 2100))


def test_hold_refuses_when_a_joint_does_not_answer() -> None:
    channel = FeetechFakeChannel({1: 2000})  # gripper silent
    _, _, actuator = _opened(channel, _arm())
    with pytest.raises(ActuatorWriteError):
        actuator.hold()
    assert all(reg != TORQUE for _, reg, _ in channel.writes)


def test_release_turns_torque_off_on_every_joint_that_answers() -> None:
    # Uncalibrated joints are released too (something else may have torqued them); only a
    # calibrated joint that fails to acknowledge is an error.
    channel = FeetechFakeChannel({1: 2000, 6: 2100, 3: 1000})
    _, _, actuator = _opened(channel, _arm())
    actuator.release()
    assert [(i, v) for i, reg, v in channel.writes if reg == TORQUE] == [(1, 0), (6, 0), (3, 0)]
    silent_uncalibrated = FeetechFakeChannel({1: 2000, 6: 2100})
    _, _, quiet = _opened(silent_uncalibrated, _arm())
    quiet.release()  # address 3 is absent: not an error


def test_release_reports_a_calibrated_joint_that_stays_torqued() -> None:
    channel = FeetechFakeChannel({1: 2000, 6: 2100})
    channel.silent_writes.add(6)
    _, _, actuator = _opened(channel, _arm())
    with pytest.raises(ActuatorWriteError):
        actuator.release()


@pytest.mark.parametrize(
    "values", [{"range_min": 100, "range_max": 5000}, {"range_min": -50, "range_max": 3000}]
)
def test_a_calibrated_range_the_servo_cannot_reach_is_not_actuated(
    values: dict[str, float | int],
) -> None:
    # Calibration can arrive from a committed repo file — untrusted input (CLAUDE.md §7).
    config = _arm()
    part = config.parts[str(SHOULDER)]
    bad = part.model_copy(
        update={"calibration": PartCalibration(mode=CalibrationMode.DEGREES, values=values)}
    )
    config = config.model_copy(update={"parts": {**config.parts, str(SHOULDER): bad}})
    _, _, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100}), config)
    joint = next(j for j in actuator.joints() if j.address == 1)
    assert joint.span is None
    with pytest.raises(ValueError):
        actuator.write_goals({1: 4096})


async def test_actuator_follows_the_source_across_incarnations() -> None:
    driver, source, actuator = _opened(FeetechFakeChannel({1: 2000, 6: 2100}), _arm())
    await source.aclose()
    with pytest.raises(ActuatorUnavailableError):
        actuator.read()
    channel = FeetechFakeChannel({1: 2222, 6: 2100})
    driver.open(channel, FeetechParams(), _arm())
    assert actuator.read()[1] == 2222  # same handle, new link


def test_registry_exposes_the_actuator_and_none_for_drivers_without_one() -> None:
    from livebench.hardware.driver import DriverRegistry

    registry = DriverRegistry()
    registry.register(FeetechStsDriver)
    assert registry.actuator(_arm()) is not None
    assert registry.actuator(_arm().model_copy(update={"protocol": None})) is None
