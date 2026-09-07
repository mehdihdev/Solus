"""ODrive CANSimple definitions: command ids, wire-field → Solus signal mapping with units, and a
display-only model table (the heartbeat carries no model number)."""

from livebench.plugins.odrive.odrive_definitions import (
    ODRIVE_CMD_BUS_VOLTAGE_CURRENT,
    ODRIVE_CMD_GET_ENCODER_ESTIMATES,
    ODRIVE_CMD_GET_IQ,
    ODRIVE_CMD_HEARTBEAT,
    ODRIVE_DEFAULT_BITRATE,
    ODRIVE_FRAME_FIELDS,
    ODRIVE_MODELS,
    ODRIVE_SIGNALS,
    ODRIVE_UNITS,
)


def test_command_ids() -> None:
    assert (ODRIVE_CMD_HEARTBEAT, ODRIVE_CMD_GET_ENCODER_ESTIMATES) == (0x01, 0x09)
    assert (ODRIVE_CMD_GET_IQ, ODRIVE_CMD_BUS_VOLTAGE_CURRENT) == (0x14, 0x17)
    assert ODRIVE_DEFAULT_BITRATE == 250_000


def test_frame_fields_and_signal_units() -> None:
    assert ODRIVE_FRAME_FIELDS == {
        0x09: ("pos_estimate", "vel_estimate"),
        0x14: ("iq_setpoint", "iq_measured"),
        0x17: ("bus_voltage", "bus_current"),
    }
    assert ODRIVE_UNITS == {"position": "rev", "velocity": "rev/s", "current": "A", "voltage": "V"}
    assert ODRIVE_SIGNALS == {
        "pos_estimate": "position",
        "vel_estimate": "velocity",
        "iq_measured": "current",
        "bus_voltage": "voltage",
    }
    assert set(ODRIVE_SIGNALS.values()) == set(ODRIVE_UNITS)


def test_model_table_is_display_data_only() -> None:
    assert ODRIVE_MODELS == ("ODrive S1", "ODrive Pro", "ODrive v3.6")
