"""Dynamixel definition tables: model register → part number, encoder resolution by model,
the X-series registers this plugin reads. Data, never configuration."""

from livebench.plugins.dynamixel.dynamixel_definitions import (
    DXL_DEFAULT_BAUD,
    DXL_MODELS,
    DXL_PROTOCOL_VERSION,
    DXL_REGISTERS,
    DXL_TICKS_PER_REV,
    dxl_resolution,
)


def test_model_register_table_names_the_curated_parts_only() -> None:
    assert DXL_MODELS == {
        1020: "XM430-W350",
        1190: "XL330-M288",
        1200: "XC330-M288",
        1060: "XL430-W250",
        1120: "XM540-W270",
        350: "XL320",
    }
    assert DXL_MODELS.get(9999) is None  # an unknown number is never guessed into a name


def test_resolution_is_per_model_with_the_x_series_default() -> None:
    assert DXL_TICKS_PER_REV == 4096
    assert dxl_resolution("XL320") == 1024
    assert dxl_resolution("XM430-W350") == 4096
    assert dxl_resolution(None) == 4096


def test_register_map_and_protocol_facts() -> None:
    assert DXL_REGISTERS["present_position"] == (132, 4)
    assert DXL_REGISTERS["torque_enable"] == (64, 1)
    assert DXL_REGISTERS["goal_position"] == (116, 4)
    assert DXL_REGISTERS["present_load"] == (126, 2)
    assert DXL_REGISTERS["present_temperature"] == (146, 1)
    assert DXL_DEFAULT_BAUD == 57600
    assert DXL_PROTOCOL_VERSION == 2
