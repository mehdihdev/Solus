"""The migration keeps subjects, values and portable evidence, refusing ambiguous winners."""

import uuid

import pytest
from pydantic import ValidationError
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.migration import split_legacy_document


def test_entity_config_needs_no_connection_and_validates_each_valued_leaf() -> None:
    entity_id = uuid.uuid4()
    config = EntityHardwareConfig(entity_id=entity_id)
    assert config.schema_version == 2
    assert config.identity is None
    with pytest.raises(ValidationError, match="provenance"):
        EntityHardwareConfig.model_validate(
            {"entity_id": entity_id, "component": {"limits": {"values": {"max": 90}}}}
        )


@pytest.mark.parametrize(
    "private",
    [
        "/home/member/calibration.json",
        r"C:\Users\member\calibration.json",
        "file:///home/member/config.json",
    ],
)
async def test_private_paths_are_replaced_by_opaque_refs_on_legacy_split(private: str) -> None:
    robot, part = uuid.uuid4(), uuid.uuid4()
    old = {
        "schema_version": 1,
        "robot_entity_id": str(robot),
        "identity": {
            "kind": "usb_serial",
            "binding": "serial-example",
            "last_seen_path": "/dev/ttyUSB0",
        },
        "parts": {
            str(part): {
                "calibration": {
                    "mode": "degrees",
                    "values": {"offset": 7},
                    "source": private,
                    "owner": "repo",
                },
                "limits": {"values": {"max": 90}},
                "lifecycle": "received",
            }
        },
        "provenance": {"identity": {"by": "detected"}, "parts": {"by": "repo", "source": private}},
    }
    documents = split_legacy_document(old)
    assert set(documents) == {robot, part}
    component = documents[part].component
    assert (
        component is not None and component.calibration is not None and component.limits is not None
    )
    assert component.calibration.values == {"offset": 7}
    assert component.limits.values == {"max": 90}
    assert private not in documents[part].model_dump_json()
    assert "last_seen_path" not in documents[robot].model_dump_json()
    assert component.calibration.source is not None
    assert component.calibration.source.startswith("source:")
    assert documents == split_legacy_document(old)


def test_v2_rejects_private_identity_hint_unknown_fields_and_duplicate_bus_address() -> None:
    entity_id = str(uuid.uuid4())
    base = {
        "entity_id": entity_id,
        "provenance": {"identity": {"by": "user"}, "bus_map": {"by": "user"}},
    }
    with pytest.raises(ValidationError):
        EntityHardwareConfig.model_validate(
            {
                **base,
                "identity": {
                    "kind": "usb_serial",
                    "binding": "serial",
                    "last_seen_path": "/dev/ttyUSB0",
                },
            }
        )
    with pytest.raises(ValidationError):
        EntityHardwareConfig.model_validate({**base, "credentials": "forbidden"})
    with pytest.raises(ValidationError, match="duplicate"):
        EntityHardwareConfig.model_validate(
            {
                **base,
                "bus_map": [
                    {"protocol": "generic", "address": "1"},
                    {"protocol": "generic", "address": "1"},
                ],
            }
        )


@pytest.mark.parametrize("top", [{"version": "1"}, {"board": "fixture"}, {}])
def test_owner_component_collision_merges_without_losing_connection(top: dict[str, str]) -> None:
    owner = uuid.uuid4()
    legacy = {
        "robot_entity_id": str(owner),
        "identity": {"kind": "usb_serial", "binding": "fixture"},
        "protocol": {"driver_id": "fixture", "params": {"baud": 115200}},
        "bus_map": [{"protocol": "fixture", "address": "1"}],
        "disambiguated_by": "user",
        "firmware": top,
        "parts": {
            str(owner): {
                "firmware": {"version": "1"},
                "limits": {"values": {"max": 50}},
                "lifecycle": "installed",
            }
        },
        "provenance": {
            "identity": {"by": "detected"},
            "protocol": {"by": "library"},
            "bus_map": {"by": "detected"},
            "parts": {"by": "repo"},
            "firmware": {"by": "user"},
            "disambiguated_by": {"by": "user"},
            f"parts.{owner}.lifecycle": {"by": "sol"},
        },
    }
    config = split_legacy_document(legacy)[owner]
    assert config.identity is not None and config.identity.binding == "fixture"
    assert config.protocol is not None and config.protocol.params == {"baud": 115200}
    assert len(config.bus_map) == 1 and config.disambiguated_by == "user"
    assert config.component is not None and config.component.limits is not None
    assert config.component.limits.values == {"max": 50}
    assert config.component.firmware == {"version": "1", **top}
    assert config.component.lifecycle.value == "installed"
    assert config.provenance_of("component.lifecycle").by.value == "sol"
    assert config.provenance_of("component.firmware.version").by.value == (
        "user" if "version" in top else "repo"
    )


def test_conflicting_owner_firmware_copies_require_review() -> None:
    owner = str(uuid.uuid4())
    with pytest.raises(ValueError, match="firmware"):
        split_legacy_document(
            {
                "robot_entity_id": owner,
                "firmware": {"version": "new"},
                "parts": {owner: {"firmware": {"version": "old"}}},
                "provenance": {"parts": {"by": "user"}, "firmware": {"by": "user"}},
            }
        )


def test_null_firmware_leaf_needs_no_provenance_and_is_retained() -> None:
    owner = uuid.uuid4()
    split = split_legacy_document({"robot_entity_id": str(owner), "firmware": {"optional": None}})
    component = split[owner].component
    assert component is not None and component.firmware == {"optional": None}
