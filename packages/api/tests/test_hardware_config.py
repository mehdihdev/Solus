"""R5 hardware config schema (docs/api/hardware.md §2, ADR-034 amendment 2026-09-06).

One schema round-trips a serial servo arm, a CAN mobile base and a MAVLink drone with no
per-machine special case; every valued leaf carries provenance; units derive from calibration
mode; later source layers win and the winner is recorded; lifecycle promotion keeps the part key.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.hardware.config import (
    MAX_BUS_ENTRIES,
    MAX_DOCUMENT_BYTES,
    TRANSPORT_PREFIX,
    CalibrationMode,
    ConfigLayer,
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    TransportKind,
    merge_layers,
    part_ref,
    promote_part,
    unit_for_mode,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hardware"
MACHINES = ("serial_arm", "can_base", "mavlink_drone")
EXPECTED_DEVICE_REF = {
    "serial_arm": "usb:5B42134331",
    "can_base": "can:ODRV-3F2A-CAN0",
    "mavlink_drone": "ip:aa:bb:cc:dd:ee:ff",
}


def _machine_fixture(name: str) -> dict[str, Any]:
    return dict(json.loads((FIXTURES / f"{name}.json").read_text()))


@pytest.mark.parametrize("machine", MACHINES)
def test_three_machines_round_trip_through_one_schema(machine: str) -> None:
    raw = _machine_fixture(machine)
    config = HardwareConfig.model_validate(raw)
    dumped = config.model_dump(mode="json")
    assert HardwareConfig.model_validate(dumped) == config
    assert config.identity is not None
    assert config.identity.device_ref == EXPECTED_DEVICE_REF[machine]
    assert config.protocol is not None and config.protocol.driver_id
    assert config.bus_map and config.parts


@pytest.mark.parametrize("machine", MACHINES)
def test_every_part_in_the_bus_map_is_a_configured_part(machine: str) -> None:
    config = HardwareConfig.model_validate(_machine_fixture(machine))
    for entry in config.bus_map:
        if entry.part_entity_id is not None:
            assert str(entry.part_entity_id) in config.parts


def test_schema_module_names_no_vendor() -> None:
    """Early guard for the Phase 6 ratchet: the shared schema knows no product."""
    import solus_api.hardware.config as module

    source = Path(module.__file__).read_text().lower()
    banned = re.compile(r"\b(feetech|dynamixel|lerobot|sts3215|so-?101|px4|odrive|mavlink)\b")
    assert banned.search(source) is None


def test_every_valued_leaf_needs_provenance() -> None:
    raw = _machine_fixture("serial_arm")
    raw["provenance"] = {"identity": {"by": "detected"}}
    with pytest.raises(ValidationError) as excinfo:
        HardwareConfig.model_validate(raw)
    assert "protocol.driver_id" in str(excinfo.value)


def test_empty_config_needs_no_provenance() -> None:
    config = HardwareConfig(robot_entity_id=uuid.uuid4())
    assert config.leaf_paths() == []
    assert config.provenance == {}


def test_provenance_resolves_by_longest_prefix() -> None:
    config = HardwareConfig.model_validate(_machine_fixture("serial_arm"))
    gripper = next(
        pid
        for pid, part in config.parts.items()
        if part.calibration is not None and part.calibration.mode is CalibrationMode.RANGE_0_100
    )
    assert config.provenance_of(f"parts.{gripper}.calibration.values.homing_offset").by is (
        FieldProvenance.REPO
    )
    assert config.provenance_of(f"parts.{gripper}.lifecycle").by is FieldProvenance.USER
    assert config.provenance_of("identity.binding").by is FieldProvenance.DETECTED
    with pytest.raises(KeyError):
        config.provenance_of("nowhere.at.all")


@pytest.mark.parametrize(
    ("mode", "unit"),
    [
        (CalibrationMode.DEGREES, "deg"),
        (CalibrationMode.RANGE_0_100, "%"),
        (CalibrationMode.RANGE_M100_100, "%"),
        (CalibrationMode.LINEAR, "mm"),
        (CalibrationMode.RAW, None),
        (None, None),
    ],
)
def test_unit_for_mode(mode: CalibrationMode | None, unit: str | None) -> None:
    assert unit_for_mode(mode) == unit


def test_the_same_servo_model_reports_different_units_by_mode() -> None:
    config = HardwareConfig.model_validate(_machine_fixture("serial_arm"))
    units = {channel.unit for part in config.parts.values() for channel in part.telemetry}
    assert units == {"deg", "%"}


def test_merge_layers_later_wins_and_records_the_winner() -> None:
    robot = uuid.uuid4()
    library = ConfigLayer(
        by=FieldProvenance.LIBRARY,
        source="platform:demo",
        document={
            "identity": {"kind": "usb_serial", "binding": "AAAA"},
            "protocol": {"driver_id": "serial-bus", "params": {"baud": 115200, "timeout_s": 0.1}},
        },
    )
    repo = ConfigLayer(
        by=FieldProvenance.REPO,
        source="repo:config.py",
        document={"protocol": {"params": {"baud": 1_000_000}}},
    )
    detected = ConfigLayer(
        by=FieldProvenance.DETECTED,
        document={"identity": {"last_seen_path": "/dev/ttyACM1"}},
    )
    config = merge_layers(robot, [library, repo, detected])
    assert config.robot_entity_id == robot
    assert config.protocol is not None
    assert config.protocol.params["baud"] == 1_000_000
    assert config.protocol.params["timeout_s"] == 0.1
    assert config.provenance_of("protocol.params.baud").by is FieldProvenance.REPO
    assert config.provenance_of("protocol.params.baud").source == "repo:config.py"
    assert config.provenance_of("protocol.params.timeout_s").by is FieldProvenance.LIBRARY
    assert config.provenance_of("identity.last_seen_path").by is FieldProvenance.DETECTED
    assert config.provenance_of("identity.binding").by is FieldProvenance.LIBRARY


def test_merge_layers_replaces_lists_whole_and_forgets_stale_indices() -> None:
    robot = uuid.uuid4()
    first = ConfigLayer(
        by=FieldProvenance.LIBRARY,
        document={
            "bus_map": [{"protocol": "p", "address": "1"}, {"protocol": "p", "address": "2"}]
        },
    )
    second = ConfigLayer(
        by=FieldProvenance.DETECTED,
        document={"bus_map": [{"protocol": "p", "address": "9"}]},
    )
    config = merge_layers(robot, [first, second])
    assert [e.address for e in config.bus_map] == ["9"]
    assert config.provenance_of("bus_map.0.address").by is FieldProvenance.DETECTED
    assert "bus_map.1.address" not in config.provenance


def test_port_path_is_informational_never_identity() -> None:
    config = HardwareConfig.model_validate(_machine_fixture("serial_arm"))
    assert config.identity is not None
    moved = config.identity.model_copy(update={"last_seen_path": "/dev/ttyACM7"})
    assert moved.device_ref == config.identity.device_ref
    assert moved.identity_key() == config.identity.identity_key()


def test_binding_cannot_contain_the_part_separator() -> None:
    raw = _machine_fixture("serial_arm")
    raw["identity"]["binding"] = "5B42/1"
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate(raw)


def test_transport_prefixes_are_transports_not_drivers() -> None:
    assert set(TRANSPORT_PREFIX) == set(TransportKind)
    assert set(TRANSPORT_PREFIX.values()) == {"usb", "can", "ble", "bt", "ip", "ros2"}
    assert part_ref("usb:5B42134331", "1") == "usb:5B42134331/1"
    assert part_ref("can:ODRV-3F2A-CAN0", "0x10") == "can:ODRV-3F2A-CAN0/0x10"


def test_lifecycle_promotion_keeps_the_part_key_and_is_immutable() -> None:
    config = HardwareConfig.model_validate(_machine_fixture("can_base"))
    part_id = next(iter(config.parts))
    original_state = config.parts[part_id].lifecycle
    promoted = promote_part(config, part_id, LifecycleState.LIVE)
    assert set(promoted.parts) == set(config.parts)
    assert promoted.parts[part_id].lifecycle is LifecycleState.LIVE
    assert promoted.provenance_of(f"parts.{part_id}.lifecycle").by is FieldProvenance.USER
    assert config.parts[part_id].lifecycle is original_state  # the input is untouched


def test_lifecycle_promotion_of_an_unknown_part_is_refused() -> None:
    config = HardwareConfig.model_validate(_machine_fixture("can_base"))
    with pytest.raises(KeyError):
        promote_part(config, str(uuid.uuid4()), LifecycleState.LIVE)


def test_lifecycle_states_are_the_five_in_order() -> None:
    assert [s.value for s in LifecycleState] == [
        "planned",
        "ordered",
        "received",
        "installed",
        "live",
    ]


def test_bounds_and_unknown_fields_are_rejected() -> None:
    raw = _machine_fixture("serial_arm")
    raw["bus_map"] = [{"protocol": "x", "address": str(i)} for i in range(MAX_BUS_ENTRIES + 1)]
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate(raw)
    raw = _machine_fixture("serial_arm")
    raw["unexpected"] = 1
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate(raw)
    raw = _machine_fixture("serial_arm")
    raw["firmware"] = {"blob": "x" * (MAX_DOCUMENT_BYTES + 1)}
    raw["provenance"]["firmware"] = {"by": "user"}
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate(raw)


def test_part_keys_must_be_entity_ids() -> None:
    raw = _machine_fixture("can_base")
    raw["parts"]["not-a-uuid"] = raw["parts"].popitem()[1]
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate(raw)


def test_schema_version_is_pinned() -> None:
    raw = _machine_fixture("serial_arm")
    raw["schema_version"] = 2
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate(raw)
