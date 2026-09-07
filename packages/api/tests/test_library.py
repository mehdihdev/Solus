"""R4 library (docs/api/hardware.md §5; ADR-033 spirit): Solus-curated YAML definitions loaded
once in memory, searched lexically, composed into a LIBRARY config layer. No tenant table, no
write path, and no vendor name anywhere outside the definition files."""

import re
import textwrap
import uuid
from pathlib import Path

import pytest
from solus_api.hardware import library as library_module
from solus_api.hardware import library_router as router_module
from solus_api.hardware.config import (
    CalibrationMode,
    ConfigLayer,
    FieldProvenance,
    TransportKind,
    merge_layers,
)
from solus_api.hardware.library import (
    DEFINITIONS_DIR,
    DefinitionError,
    Library,
    PartDefinition,
    PlatformDefinition,
    load_library,
    vendor_definitions_root,
)

SO101_ROLES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
LEADER_RATIOS = {"1": "1/191", "2": "1/345", "3": "1/191", "4": "1/147", "5": "1/147", "6": "1/147"}
PLATFORMS = {
    "so101-follower",
    "so101-leader",
    "px4-quadrotor",
    "odrive-diff-base",
    "unitree-go2",
    "ur5e",
}
DRONE_ADDRESSES = [
    "1:1",
    "servo:1",
    "servo:2",
    "servo:3",
    "servo:4",
    "1:1:imu",
    "1:1:gps",
    "1:1:baro",
]
BANNED = re.compile(
    r"\b(feetech|dynamixel|lerobot|sts3215|so-?101|px4|odrive|mavlink|unitree|pixhawk)\b"
)


@pytest.fixture(scope="module")
def library() -> Library:
    return load_library()


def _entity_ids(platform: PlatformDefinition) -> dict[str, uuid.UUID]:
    return {part.address: uuid.uuid4() for part in platform.parts}


def _write(root: Path, kind: str, name: str, body: str) -> None:
    (root / kind).mkdir(parents=True, exist_ok=True)
    (root / kind / f"{name}.yaml").write_text(textwrap.dedent(body))


def _part_yaml(definition_id: str) -> str:
    return f"""
        id: {definition_id}
        name: Demo part
        category: sensors
        telemetry: [{{quantity: temperature, unit: degC}}]
    """


# --------------------------------------------------------------------- loading


def test_every_seed_definition_loads_under_its_file_stem(library: Library) -> None:
    part_files = {p.stem for p in (DEFINITIONS_DIR / "parts").glob("*.yaml")}
    platform_files = {p.stem for p in (DEFINITIONS_DIR / "platforms").glob("*.yaml")}
    assert part_files == set(library.parts) and len(part_files) >= 14
    assert platform_files == set(library.platforms) == PLATFORMS
    assert not part_files & platform_files
    for definition in (*library.parts.values(), *library.platforms.values()):
        assert re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", definition.id)


def test_every_platform_part_references_a_known_part(library: Library) -> None:
    for platform in library.platforms.values():
        for part in platform.parts:
            assert part.part in library.parts, f"{platform.id} → {part.part}"


def test_load_library_is_cached_and_the_vendor_tier_is_empty_today() -> None:
    assert load_library() is load_library()
    vendor = load_library(vendor_definitions_root())
    assert vendor.parts == {} and vendor.platforms == {}
    assert vendor_definitions_root().parent == DEFINITIONS_DIR


def test_datasheet_urls_are_https_only(library: Library) -> None:
    for part in library.parts.values():
        if part.datasheet_url is not None:
            assert part.datasheet_url.startswith("https://"), part.id


def test_a_duplicate_id_across_kinds_fails_loudly(tmp_path: Path) -> None:
    _write(tmp_path, "parts", "twin", _part_yaml("twin"))
    _write(
        tmp_path,
        "platforms",
        "twin",
        """
        id: twin
        name: Twin platform
        machine_class: other
        transport: usb_serial
        driver_id: null
        parts: [{part: twin, address: "1", role: probe}]
        """,
    )
    with pytest.raises(DefinitionError, match=r"duplicate.*twin"):
        load_library(tmp_path)


def test_an_id_that_is_not_the_file_stem_fails_loudly(tmp_path: Path) -> None:
    _write(tmp_path, "parts", "stem", _part_yaml("other"))
    with pytest.raises(DefinitionError, match=r"stem\.yaml.*other"):
        load_library(tmp_path)


def test_a_dangling_part_reference_fails_loudly(tmp_path: Path) -> None:
    _write(tmp_path, "parts", "real", _part_yaml("real"))
    _write(
        tmp_path,
        "platforms",
        "rig",
        """
        id: rig
        name: Rig
        machine_class: other
        transport: ethernet
        driver_id: null
        parts:
          - {part: real, address: "a", role: one}
          - {part: ghost, address: "b", role: two}
        """,
    )
    with pytest.raises(DefinitionError, match=r"rig.*ghost"):
        load_library(tmp_path)


def test_an_unknown_field_or_a_repeated_address_fails_loudly(tmp_path: Path) -> None:
    _write(tmp_path, "parts", "real", _part_yaml("real") + "        colour: red\n")
    with pytest.raises(DefinitionError, match=r"real\.yaml"):
        load_library(tmp_path)
    (tmp_path / "parts" / "real.yaml").write_text(textwrap.dedent(_part_yaml("real")))
    _write(
        tmp_path,
        "platforms",
        "rig",
        """
        id: rig
        name: Rig
        machine_class: other
        transport: ethernet
        driver_id: null
        parts:
          - {part: real, address: "a", role: one}
          - {part: real, address: "a", role: two}
        """,
    )
    with pytest.raises(DefinitionError, match=r"rig\.yaml.*address"):
        load_library(tmp_path)


# ------------------------------------------------------------------ definitions


def test_serial_servo_part_mirrors_the_driver_register_map(library: Library) -> None:
    part = library.get("part", "sts3215")
    assert isinstance(part, PartDefinition)
    assert part.category == "actuators" and part.driver_id == "feetech-sts"
    assert part.protocol_version == 0 and part.resolution == 4096
    assert part.calibration_mode is CalibrationMode.DEGREES
    assert [(t.quantity, t.unit) for t in part.telemetry] == [("position", "deg")]
    registers = {name: (r.address, r.size) for name, r in part.register_map.items()}
    assert registers == {
        "model_number": (3, 2),
        "id": (5, 1),
        "baud_rate": (6, 1),
        "homing_offset": (31, 2),
        "torque_enable": (40, 1),
        "goal_position": (42, 2),
        "present_position": (56, 2),
        "present_load": (60, 2),
        "present_temperature": (63, 1),
    }
    scs = library.parts["scs0009"]
    assert scs.protocol_version == 1 and scs.resolution == 1024
    xl330 = library.parts["xl330-m288"]
    assert xl330.driver_id == "dynamixel-2"
    assert (
        xl330.register_map["present_position"].address,
        xl330.register_map["present_position"].size,
    ) == (132, 4)


def test_get_is_kind_scoped(library: Library) -> None:
    assert isinstance(library.get("platform", "so101-follower"), PlatformDefinition)
    assert library.get("platform", "sts3215") is None
    assert library.get("part", "so101-follower") is None
    assert library.get("part", "nope") is None


def test_so101_follower_is_six_serial_servos_in_joint_order(library: Library) -> None:
    platform = library.platforms["so101-follower"]
    assert platform.machine_class == "arm" and platform.transport is TransportKind.USB_SERIAL
    assert platform.driver_id == "feetech-sts"
    assert platform.params == {"baud": 1_000_000, "protocol_version": 0}
    assert [p.part for p in platform.parts] == ["sts3215"] * 6
    assert [p.address for p in platform.parts] == [str(i) for i in range(1, 7)]
    assert [p.role for p in platform.parts] == SO101_ROLES
    assert {p.gear_ratio for p in platform.parts} == {"1/345"}
    modes = [p.calibration_mode for p in platform.parts]
    assert modes == [CalibrationMode.DEGREES] * 5 + [CalibrationMode.RANGE_0_100]


def test_so101_leader_gear_ratios_differ_per_joint(library: Library) -> None:
    platform = library.platforms["so101-leader"]
    assert [p.role for p in platform.parts] == SO101_ROLES
    assert {p.address: p.gear_ratio for p in platform.parts} == LEADER_RATIOS


def test_px4_quadrotor_is_an_autopilot_four_escs_and_sensors_with_no_servo_bus(
    library: Library,
) -> None:
    platform = library.platforms["px4-quadrotor"]
    assert platform.machine_class == "quadrotor" and platform.transport is TransportKind.WIFI
    assert platform.driver_id == "mavlink"
    assert platform.params == {"system_id": 1, "component_id": 1, "protocol_version": 2}
    assert [p.address for p in platform.parts] == DRONE_ADDRESSES
    escs = [p for p in platform.parts if p.part == "blheli32-esc"]
    assert [e.role for e in escs] == ["motor_1", "motor_2", "motor_3", "motor_4"]
    assert all(library.parts[p.part].register_map == {} for p in platform.parts)
    assert {library.parts[p.part].driver_id for p in platform.parts} == {"mavlink", None}


def test_odrive_diff_base_is_a_can_bus_of_two_axes_and_two_encoders(library: Library) -> None:
    platform = library.platforms["odrive-diff-base"]
    assert platform.machine_class == "mobile_base"
    assert platform.transport is TransportKind.USB_CAN and platform.driver_id == "odrive-can"
    assert platform.params == {"bitrate": 250_000}
    assert {p.address: p.role for p in platform.parts} == {
        "0x10": "left_wheel",
        "0x11": "right_wheel",
        "0x10:encoder": "left_encoder",
        "0x11:encoder": "right_encoder",
    }


def test_sdk_only_platforms_have_no_driver_and_say_so(library: Library) -> None:
    go2 = library.platforms["unitree-go2"]
    assert go2.driver_id is None and go2.transport is TransportKind.ETHERNET
    assert len(go2.parts) == 12 and go2.notes and "not yet a Solus driver" in go2.notes
    assert [p.address for p in go2.parts] == [f"leg:{i}" for i in range(12)]
    ur5e = library.platforms["ur5e"]
    assert ur5e.driver_id is None and len(ur5e.parts) == 6
    assert [p.role for p in ur5e.parts][-3:] == ["wrist_1", "wrist_2", "wrist_3"]


# ---------------------------------------------------------------------- search


def test_search_finds_the_part_and_both_platforms_that_use_it(library: Library) -> None:
    ids = {hit.id for hit in library.search("sts3215")}
    assert {"sts3215", "so101-follower", "so101-leader"} <= ids
    assert ids == {hit.id for hit in library.search("STS3215")}


def test_search_by_kind_lists_all_platforms_and_only_platforms(library: Library) -> None:
    hits = library.search("", kind="platform")
    assert {hit.id for hit in hits} == PLATFORMS
    assert all(hit.kind == "platform" and hit.machine_class for hit in hits)
    parts = library.search("", kind="part")
    assert all(hit.kind == "part" and hit.category for hit in parts)
    assert len(library.search("")) == len(library.parts) + len(library.platforms)
    assert library.search("", limit=3)[:3] == library.search("")[:3]
    assert len(library.search("", limit=3)) == 3
    assert library.search("zzz-no-such-thing") == []


def test_search_ranks_by_matched_token_count_then_id(library: Library) -> None:
    hits = library.search("servo sts3215")
    assert hits[0].id == "sts3215"
    ids = [hit.id for hit in hits]
    assert ids.index("so101-follower") < ids.index("so101-leader")


# --------------------------------------------------------------- config layer


def test_platform_config_layer_merges_into_a_config_with_library_provenance(
    library: Library,
) -> None:
    platform = library.platforms["so101-follower"]
    ids = _entity_ids(platform)
    robot_id = uuid.uuid4()
    config = merge_layers(
        robot_id,
        [
            ConfigLayer(
                by=FieldProvenance.LIBRARY,
                source="platform:so101-follower",
                document=library.platform_config_layer(platform, ids),
            )
        ],
    )
    assert config.identity is None and config.protocol is not None
    assert (
        config.protocol.driver_id == "feetech-sts" and config.protocol.params["baud"] == 1_000_000
    )
    assert [e.address for e in config.bus_map] == [str(i) for i in range(1, 7)]
    assert [e.part_entity_id for e in config.bus_map] == [ids[str(i)] for i in range(1, 7)]
    assert {e.protocol for e in config.bus_map} == {"feetech-sts"}
    assert {e.model for e in config.bus_map} == {"Feetech STS3215"}
    channels = [config.parts[str(ids[str(i)])].telemetry[0] for i in range(1, 7)]
    assert [c.name for c in channels] == [f"{role}.position" for role in SO101_ROLES]
    assert [c.unit for c in channels] == ["deg"] * 5 + ["%"]
    gripper = config.parts[str(ids["6"])]
    assert gripper.calibration is not None
    assert gripper.calibration.mode is CalibrationMode.RANGE_0_100
    assert gripper.calibration.owner == "solus"
    assert gripper.calibration.source == "platform:so101-follower"
    assert gripper.lifecycle.value == "planned"
    for path in config.leaf_paths():
        record = config.provenance_of(path)
        assert record.by is FieldProvenance.LIBRARY and record.source == "platform:so101-follower"


def test_platform_config_layer_for_the_drone_keeps_its_addresses(library: Library) -> None:
    platform = library.platforms["px4-quadrotor"]
    ids = _entity_ids(platform)
    config = merge_layers(
        uuid.uuid4(),
        [
            ConfigLayer(
                by=FieldProvenance.LIBRARY, document=library.platform_config_layer(platform, ids)
            )
        ],
    )
    assert config.protocol is not None and config.protocol.driver_id == "mavlink"
    assert [e.address for e in config.bus_map] == DRONE_ADDRESSES
    by_name = {c.name: c.unit for part in config.parts.values() for c in part.telemetry}
    assert by_name["motor_1.output"] == "us" and by_name["autopilot.attitude"] == "rad"
    assert config.parts[str(ids["servo:1"])].calibration is None


def test_platform_config_layer_without_a_driver_uses_the_transport(library: Library) -> None:
    platform = library.platforms["unitree-go2"]
    document = library.platform_config_layer(platform, _entity_ids(platform))
    assert "protocol" not in document
    assert {entry["protocol"] for entry in document["bus_map"]} == {"ethernet"}
    assert len(document["parts"]) == 12


def test_platform_config_layer_needs_an_entity_id_per_address(library: Library) -> None:
    platform = library.platforms["ur5e"]
    with pytest.raises(DefinitionError, match="joint:1"):
        library.platform_config_layer(platform, {"joint:0": uuid.uuid4()})


def test_part_config_uses_the_definition_units_when_no_mode_applies(library: Library) -> None:
    entry = library.part_config(library.parts["odrive-s1"], "left_wheel", source="part:odrive-s1")
    assert [c["name"] for c in entry["telemetry"]] == [
        "left_wheel.position",
        "left_wheel.velocity",
        "left_wheel.current",
    ]
    assert [c["unit"] for c in entry["telemetry"]] == ["rev", "rev/s", "A"]
    assert "calibration" not in entry and entry["lifecycle"] == "planned"


# ---------------------------------------------------------------- vendor hygiene


def test_shared_library_modules_name_no_vendor() -> None:
    for module in (library_module, router_module):
        assert module.__file__ is not None
        assert BANNED.search(Path(module.__file__).read_text().lower()) is None, module.__name__
