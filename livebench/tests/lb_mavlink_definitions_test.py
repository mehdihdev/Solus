"""MAVLink definitions are vendor facts, not configuration: message layouts, crc_extra bytes and
the MAV_TYPE / MAV_AUTOPILOT name tables the plugin needs to describe what it heard."""

from livebench.plugins.mavlink.mavlink_definitions import (
    ATTITUDE,
    CRC_EXTRA,
    HEARTBEAT,
    MAV_AUTOPILOT_NAMES,
    MAV_TYPE_NAMES,
    MAX_SERVO_OUTPUTS,
    MESSAGES,
    SERVO_OUTPUT_RAW,
)


def test_message_layouts_follow_the_wire_order_and_lengths() -> None:
    assert HEARTBEAT.length == 9 and HEARTBEAT.wire_format == "<IBBBBB"
    assert ATTITUDE.length == 28 and ATTITUDE.wire_format == "<Iffffff"
    assert SERVO_OUTPUT_RAW.length == 37
    assert SERVO_OUTPUT_RAW.wire_format == "<I" + "H" * 8 + "B" + "H" * 8
    assert [name for name, _ in HEARTBEAT.fields][:2] == ["custom_mode", "type"]
    assert [name for name, _ in SERVO_OUTPUT_RAW.fields][-1] == f"servo{MAX_SERVO_OUTPUTS}_raw"


def test_crc_extra_table_is_keyed_by_message_id() -> None:
    assert CRC_EXTRA == {0: 50, 30: 39, 36: 222}
    assert set(MESSAGES) == set(CRC_EXTRA)
    assert all(MESSAGES[msg_id].crc_extra == extra for msg_id, extra in CRC_EXTRA.items())


def test_vehicle_and_autopilot_names_never_guess_unknown_numbers() -> None:
    assert MAV_TYPE_NAMES[2] == "quadrotor" and MAV_TYPE_NAMES[10] == "ground rover"
    assert MAV_AUTOPILOT_NAMES == {3: "ArduPilot", 12: "PX4"}
    assert MAV_TYPE_NAMES.get(99) is None and MAV_AUTOPILOT_NAMES.get(8) is None
