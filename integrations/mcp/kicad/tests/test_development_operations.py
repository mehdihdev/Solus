"""Gated schematic operations plan exact byte changes before committing."""

from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus.development.models import DevelopmentError, fingerprint
from solus.development.schematic import (
    add_symbol,
    create_schematic,
    get_schematic_geometry,
    get_symbol_definition,
)
from test_development_foundation import LIBRARY


def test_create_dry_run_and_commit_are_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    args: dict[str, Any] = dict(
        schematic_path="fresh.kicad_sch", title="Fresh diagram", expected_absent=True
    )
    preview = create_schematic(**args, dry_run=True)
    assert not list(tmp_path.iterdir())
    result = create_schematic(**args)
    assert result["after_fingerprint"] == preview["after_fingerprint"]
    assert result["preview"] == preview["preview"]
    assert fingerprint((tmp_path / "fresh.kicad_sch").read_bytes()) == result["after_fingerprint"]
    with pytest.raises(DevelopmentError, match="already_exists"):
        create_schematic(**args)


def test_add_real_symbol_then_read_pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from solus.development import schematic

    root = tmp_path / "workspace"
    root.mkdir()
    libraries = tmp_path / "libraries"
    libraries.mkdir()
    (libraries / "Device.kicad_sym").write_bytes(LIBRARY)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    monkeypatch.setattr(schematic, "installed_library_root", lambda: libraries)
    created = create_schematic("new.kicad_sch", "New", True)
    definition = get_symbol_definition("Device:R")
    original = (root / "new.kicad_sch").read_bytes()
    args: dict[str, Any] = dict(
        schematic_path="new.kicad_sch",
        expected_fingerprint=created["after_fingerprint"],
        library_id="Device:R",
        library_fingerprint=definition["library_fingerprint"],
        reference="R1",
        value="10k",
        at={"x_mm": 20, "y_mm": 20},
        rotation_deg=0,
    )
    preview = add_symbol(**args, dry_run=True)
    assert (root / "new.kicad_sch").read_bytes() == original
    result = add_symbol(**args)
    assert result["after_fingerprint"] == preview["after_fingerprint"]
    geometry = get_schematic_geometry("new.kicad_sch", reference="R1")
    assert [(p["number"], p["x_mm"], p["y_mm"]) for p in geometry["symbols"][0]["pins"]] == [
        ("1", 20, 16.19),
        ("2", 20, 23.81),
    ]
    assert geometry["symbols"][0]["reference"] == "R1"
    with pytest.raises(DevelopmentError, match="stale_plan"):
        add_symbol(**args)


def _two_symbols(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from solus.development import schematic

    libraries = tmp_path / "libraries"
    libraries.mkdir()
    (libraries / "Device.kicad_sym").write_bytes(LIBRARY)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(schematic, "installed_library_root", lambda: libraries)
    result = create_schematic("wire.kicad_sch", "Wire test", True)
    definition = get_symbol_definition("Device:R")
    for ref, y in [("R1", 20), ("R2", 50)]:
        result = add_symbol(
            "wire.kicad_sch",
            result["after_fingerprint"],
            "Device:R",
            definition["library_fingerprint"],
            ref,
            "10k",
            {"x_mm": 20, "y_mm": y},
            0,
        )
    return result


def test_wire_label_and_no_connect_use_actual_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.wiring import add_net_label, add_wire, mark_no_connect

    result = _two_symbols(tmp_path, monkeypatch)
    start, end = (
        {"pin": {"reference": "R1", "pin_number": "2"}},
        {"pin": {"reference": "R2", "pin_number": "1"}},
    )
    original = (tmp_path / "wire.kicad_sch").read_bytes()
    plan = add_wire("wire.kicad_sch", result["after_fingerprint"], start, end, dry_run=True)
    assert (tmp_path / "wire.kicad_sch").read_bytes() == original
    result = add_wire("wire.kicad_sch", result["after_fingerprint"], start, end)
    assert result["after_fingerprint"] == plan["after_fingerprint"]
    result = add_net_label("wire.kicad_sch", result["after_fingerprint"], "SenseA0", start, 0)
    geometry = get_schematic_geometry("wire.kicad_sch")
    assert geometry["wires"][0]["start"] == {"x_mm": 20, "y_mm": 23.81}
    assert geometry["labels"][0]["name"] == "SenseA0"
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        mark_no_connect("wire.kicad_sch", result["after_fingerprint"], start["pin"])
    result = mark_no_connect(
        "wire.kicad_sch", result["after_fingerprint"], {"reference": "R1", "pin_number": "1"}
    )
    assert result["changed"] is True


def test_unsupported_anchor_cannot_be_a_raw_coordinate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.wiring import add_wire

    result = _two_symbols(tmp_path, monkeypatch)
    with pytest.raises(DevelopmentError):
        add_wire(
            "wire.kicad_sch",
            result["after_fingerprint"],
            {"x_mm": 20, "y_mm": 23.81},
            {"pin": {"reference": "R2", "pin_number": "1"}},
        )


def test_symbol_cannot_silently_land_on_existing_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _two_symbols(tmp_path, monkeypatch)
    definition = get_symbol_definition("Device:R")
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        add_symbol(
            "wire.kicad_sch",
            result["after_fingerprint"],
            "Device:R",
            definition["library_fingerprint"],
            "R3",
            "10k",
            {"x_mm": 20, "y_mm": 20},
            0,
        )


def test_existing_no_connect_is_true_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from solus.development.wiring import mark_no_connect

    result = _two_symbols(tmp_path, monkeypatch)
    pin = {"reference": "R1", "pin_number": "1"}
    result = mark_no_connect("wire.kicad_sch", result["after_fingerprint"], pin)
    path = tmp_path / "wire.kicad_sch"
    before = path.stat()
    result = mark_no_connect("wire.kicad_sch", result["after_fingerprint"], pin)
    assert result["changed"] is False
    assert path.stat().st_ino == before.st_ino


def test_label_cannot_silently_short_an_unrelated_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.wiring import add_wire

    result = _two_symbols(tmp_path, monkeypatch)
    # The route turns through the other unrequested R1 pin: no hidden short.
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        add_wire(
            "wire.kicad_sch",
            result["after_fingerprint"],
            {"pin": {"reference": "R1", "pin_number": "2"}},
            {"pin": {"reference": "R2", "pin_number": "1"}},
            via=[{"x_mm": 20, "y_mm": 16.19}],
        )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("reference", "../bad"),
        ("at", {"x_mm": True, "y_mm": 20}),
        ("rotation_deg", 45),
        ("library_fingerprint", "bad"),
        ("value", "line\nbreak"),
    ],
)
def test_symbol_rejects_invalid_inputs_without_editing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, bad: Any
) -> None:
    result = _two_symbols(tmp_path, monkeypatch)
    definition = get_symbol_definition("Device:R")
    args: dict[str, Any] = {
        "schematic_path": "wire.kicad_sch",
        "expected_fingerprint": result["after_fingerprint"],
        "library_id": "Device:R",
        "library_fingerprint": definition["library_fingerprint"],
        "reference": "R3",
        "value": "10k",
        "at": {"x_mm": 50, "y_mm": 50},
        "rotation_deg": 0,
    }
    args[field] = bad
    original = (tmp_path / "wire.kicad_sch").read_bytes()
    with pytest.raises(DevelopmentError):
        add_symbol(**args)
    assert (tmp_path / "wire.kicad_sch").read_bytes() == original


def test_placement_retains_one_embedded_definition_and_unrelated_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_symbols(tmp_path, monkeypatch)
    raw = (tmp_path / "wire.kicad_sch").read_bytes()
    assert raw.count(b'(symbol "Device:R"') == 1
    assert raw.count(b'(lib_id "Device:R")') == 2
    assert b'(title "Wire test")' in raw


def test_netlabel_retains_case_and_escapes_quotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.wiring import add_net_label

    result = _two_symbols(tmp_path, monkeypatch)
    name = 'MixedCase"Label'
    result = add_net_label(
        "wire.kicad_sch",
        result["after_fingerprint"],
        name,
        {"pin": {"reference": "R1", "pin_number": "1"}},
        0,
    )
    assert get_schematic_geometry("wire.kicad_sch")["labels"][0]["name"] == name
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        add_net_label(
            "wire.kicad_sch",
            result["after_fingerprint"],
            "Conflicting",
            {"pin": {"reference": "R1", "pin_number": "1"}},
            0,
        )


def test_nonorthogonal_wire_and_duplicate_wire_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.wiring import add_wire

    result = _two_symbols(tmp_path, monkeypatch)
    a, b = (
        {"pin": {"reference": "R1", "pin_number": "2"}},
        {"pin": {"reference": "R2", "pin_number": "1"}},
    )
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        add_wire(
            "wire.kicad_sch", result["after_fingerprint"], a, b, via=[{"x_mm": 30, "y_mm": 30}]
        )
    result = add_wire("wire.kicad_sch", result["after_fingerprint"], a, b)
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        add_wire("wire.kicad_sch", result["after_fingerprint"], a, b)


def test_four_decimal_placement_survives_saved_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _two_symbols(tmp_path, monkeypatch)
    definition = get_symbol_definition("Device:R")
    add_symbol(
        "wire.kicad_sch",
        result["after_fingerprint"],
        "Device:R",
        definition["library_fingerprint"],
        "R3",
        "10k",
        {"x_mm": 100.0001, "y_mm": 500.1234},
        0,
    )
    symbol = get_schematic_geometry("wire.kicad_sch", "R3")["symbols"][0]
    assert symbol["x_mm"] == 100.0001 and symbol["y_mm"] == 500.1234


def test_wire_refuses_standalone_label_interception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.structural import insert_nodes
    from solus.development.wiring import add_wire

    _two_symbols(tmp_path, monkeypatch)
    path = tmp_path / "wire.kicad_sch"
    path.write_bytes(
        insert_nodes(
            path.read_bytes(), root_nodes=[b'(label "OtherNet" (at 20 30 0) (uuid "label"))']
        )
    )
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        add_wire(
            "wire.kicad_sch",
            fingerprint(path.read_bytes()),
            {"pin": {"reference": "R1", "pin_number": "2"}},
            {"pin": {"reference": "R2", "pin_number": "1"}},
        )


@pytest.mark.parametrize(
    "construct", ["global_label", "hierarchical_label", "sheet", "bus", "bus_entry", "junction"]
)
def test_unsupported_electrical_construct_refuses_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, construct: str
) -> None:
    from solus.development.wiring import mark_no_connect

    _two_symbols(tmp_path, monkeypatch)
    path = tmp_path / "wire.kicad_sch"
    data = path.read_bytes().rstrip()
    path.write_bytes(data[:-1] + f" ({construct})".encode() + b")")
    with pytest.raises(DevelopmentError, match="unsupported_symbol"):
        mark_no_connect(
            "wire.kicad_sch", fingerprint(path.read_bytes()), {"reference": "R1", "pin_number": "1"}
        )


def test_symbol_read_does_not_repeat_unit_in_each_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_symbols(tmp_path, monkeypatch)
    definition = get_symbol_definition("Device:R")
    assert definition["units"][0]["unit"] == 1
    assert all("unit" not in pin for pin in definition["units"][0]["pins"])


def test_wire_preview_discloses_existing_endpoint_net(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development.wiring import add_net_label, add_wire

    result = _two_symbols(tmp_path, monkeypatch)
    start = {"pin": {"reference": "R1", "pin_number": "2"}}
    result = add_net_label(
        "wire.kicad_sch", result["after_fingerprint"], "ExistingSignal", start, 0
    )
    result = add_wire(
        "wire.kicad_sch",
        result["after_fingerprint"],
        start,
        {"pin": {"reference": "R2", "pin_number": "1"}},
        dry_run=True,
    )
    assert "ExistingSignal" in result["preview"][0]["after"]


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_symbol_fields_are_legible_and_metadata_is_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, angle: int
) -> None:
    from solus.development import schematic
    from solus.development.structural import children, document, value

    libraries = tmp_path / "libraries"
    libraries.mkdir()
    data = LIBRARY.replace(
        b'(property "Value" "R")',
        b'(property "Value" "R") (property "Datasheet" "https://example.com/resistor.pdf")',
    )
    (libraries / "Device.kicad_sym").write_bytes(data)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(schematic, "installed_library_root", lambda: libraries)
    created = create_schematic("fields.kicad_sch", "Field readability", True)
    definition = get_symbol_definition("Device:R")
    add_symbol(
        "fields.kicad_sch",
        created["after_fingerprint"],
        "Device:R",
        definition["library_fingerprint"],
        "R1",
        "10k",
        {"x_mm": 20, "y_mm": 20},
        angle,
    )
    root = document((tmp_path / "fields.kicad_sch").read_bytes())
    symbol = children(root, "symbol")[0]
    props = {value(prop): prop for prop in children(symbol, "property")}
    ref_at = children(props["Reference"], "at")[0]
    value_at = children(props["Value"], "at")[0]
    assert (value(ref_at), value(ref_at, 2)) != (value(value_at), value(value_at, 2))
    pins = get_schematic_geometry("fields.kicad_sch")["symbols"][0]["pins"]
    assert float(value(value_at, 2)) <= min(pin["y_mm"] for pin in pins) - 3.81
    for name in ("Footprint", "Datasheet"):
        assert value(children(props[name], "hide")[0]) == "yes"
    assert value(props["Datasheet"], 2) == "https://example.com/resistor.pdf"
