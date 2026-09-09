"""KiCad `.kicad_pcb` board parser tests (SOLUSDEV-252, W0-08 §5.2a).

Footprints carrying a Reference become components (no `schematic_symbol_name`
— a board has no libsource, so the hint is absent by design); pad `(net …)`
memberships become the same first-class nets as the netlist path, pad numbers
as pins. Copper/graphics noise is pruned unread. Pure unit — no DB.
"""

from __future__ import annotations

import pytest
from fixtures.kicad_sample import KICAD_PCB, KICAD_SCHEMATIC_HEAD, KICAD_SEXPR, KICAD_XML
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.eda import Component, Netlist
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.connectors.kicad_pcb import parse_kicad_pcb


def _components(text: str = KICAD_PCB) -> dict[str, Component]:
    return {c.designator: c for c in parse_kicad_pcb(text).components}


def _net_map(netlist: Netlist) -> dict[str, set[tuple[str, str]]]:
    return {net.name: {(n.designator, n.pin) for n in net.nodes} for net in netlist.nets}


# ------------------------------------------------------------- components


def test_footprints_with_a_reference_become_components() -> None:
    assert set(_components()) == {"U1", "R1", "C1", "H1", "FID1"}


def test_referenceless_footprint_is_skipped_with_warning() -> None:
    warnings = parse_kicad_pcb(KICAD_PCB).warnings
    assert len(warnings) == 1
    assert "1 footprint(s) without a reference" in warnings[0]


def test_identity_fields_from_kicad8_properties() -> None:
    u1 = _components()["U1"]
    assert u1.value == "LM358"
    assert u1.footprint == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    assert u1.datasheet_ref == "https://www.ti.com/lit/ds/symlink/lm358.pdf"
    assert u1.part_number == "LM358DR"
    assert u1.properties["layer"] == "F.Cu"
    assert u1.properties["description"] == "Dual op-amp"
    assert u1.properties["Tolerance"] == "n/a"
    assert u1.properties["Grade"] == "industrial"


def test_no_schematic_symbol_name_on_a_board_by_design() -> None:
    assert all(c.schematic_symbol_name is None for c in _components().values())


def test_mpn_is_popped_and_ki_properties_are_dropped() -> None:
    u1 = _components()["U1"]
    assert "MPN" not in u1.properties
    assert not any(name.startswith("ki_") for name in u1.properties)
    # The alias spelling lands too, exactly as on the netlist path.
    assert _components()["R1"].part_number == "RC0603FR-0710KL"
    assert "Manufacturer_Part_Number" not in _components()["R1"].properties


def test_well_known_properties_do_not_leak_into_custom_fields() -> None:
    r1 = _components()["R1"]
    for name in ("Reference", "Value", "Footprint", "Datasheet", "Description"):
        assert name not in r1.properties
    assert r1.datasheet_ref is None  # "~" is unset
    assert r1.properties["description"] == "Resistor"
    assert _components()["C1"].properties["layer"] == "B.Cu"


def test_board_only_parts_are_components_without_connectivity() -> None:
    by_ref = _components()
    assert by_ref["H1"].value == "MountingHole_3.2mm_M3"
    assert by_ref["H1"].footprint == "MountingHole:MountingHole_3.2mm_M3"
    assert by_ref["H1"].part_number is None
    referenced = {n.designator for net in parse_kicad_pcb(KICAD_PCB).nets for n in net.nodes}
    assert "H1" not in referenced
    assert "FID1" not in referenced


def test_kicad7_fp_text_reference_and_value() -> None:
    fid1 = _components()["FID1"]
    assert fid1.value == "Fiducial"
    assert fid1.footprint == "Fiducial:Fiducial_1mm_Mask2mm"  # lib id: no Footprint property
    assert fid1.properties == {"layer": "F.Cu"}


def test_property_wins_over_fp_text_when_both_exist() -> None:
    text = """(kicad_pcb (version 20241229) (generator "pcbnew")
      (footprint "Lib:FP" (layer "F.Cu")
        (property "Reference" "R5") (property "Value" "new")
        (fp_text reference "R9" (at 0 0)) (fp_text value "old" (at 0 0))))"""
    by_ref = _components(text)
    assert set(by_ref) == {"R5"}
    assert by_ref["R5"].value == "new"


@pytest.mark.parametrize(
    "reference",
    ['(property "Reference" "REF**")', '(property "Reference" "")', '(property "Reference")', ""],
)
def test_missing_empty_or_placeholder_reference_is_skipped(reference: str) -> None:
    text = f'(kicad_pcb (version 20241229) (footprint "Lib:FP" (layer "F.Cu") {reference}))'
    netlist = parse_kicad_pcb(text)
    assert netlist.components == ()
    assert any("without a reference" in w for w in netlist.warnings)


def test_footprint_property_overrides_lib_id_when_set() -> None:
    text = """(kicad_pcb (version 20241229)
      (footprint "Lib:Placed" (layer "F.Cu")
        (property "Reference" "J1") (property "Footprint" "Lib:Declared"))
      (footprint "Lib:Placed2" (layer "F.Cu")
        (property "Reference" "J2") (property "Footprint" "~")))"""
    by_ref = _components(text)
    assert by_ref["J1"].footprint == "Lib:Declared"
    assert by_ref["J2"].footprint == "Lib:Placed2"


# ------------------------------------------------------------- nets


def test_pad_memberships_reproduce_the_netlist_connectivity() -> None:
    assert _net_map(parse_kicad_pcb(KICAD_PCB)) == _net_map(parse_kicad_netlist(KICAD_XML))


def test_nets_follow_header_order_and_carry_no_class() -> None:
    nets = parse_kicad_pcb(KICAD_PCB).nets
    assert [n.name for n in nets] == ["VCC", "GND", "SIGNAL"]
    assert all(n.net_class is None for n in nets)


def test_unconnected_net_zero_and_netless_pads_produce_nothing() -> None:
    text = """(kicad_pcb (version 20241229)
      (net 0 "")
      (net 1 "A")
      (footprint "Lib:FP" (layer "F.Cu") (property "Reference" "U9")
        (pad "1" smd rect (net 0 ""))
        (pad "2" smd rect)
        (pad "" np_thru_hole circle (net 1 "A"))))"""
    assert parse_kicad_pcb(text).nets == ()


def test_pad_net_code_falls_back_to_the_header_map() -> None:
    text = """(kicad_pcb (version 20241229)
      (net 1 "FROM_HEADER")
      (footprint "Lib:FP" (layer "F.Cu") (property "Reference" "U9")
        (pad "1" smd rect (net 1))
        (pad "2" smd rect (net 7 "PAD_ONLY"))
        (pad "3" smd rect (net 8))))"""
    netlist = parse_kicad_pcb(text)
    assert _net_map(netlist) == {"FROM_HEADER": {("U9", "1")}, "PAD_ONLY": {("U9", "2")}}
    assert any("pad" in w for w in netlist.warnings)


def test_header_nets_without_pads_are_not_emitted() -> None:
    text = '(kicad_pcb (version 20241229) (net 1 "LONELY") (net 2 "ALSO"))'
    assert parse_kicad_pcb(text) == Netlist()


def test_pruned_copper_and_graphics_contribute_no_nodes() -> None:
    # segments/vias/zones carry (net …) sublists — they must never become nodes.
    text = """(kicad_pcb (version 20241229)
      (net 1 "VCC")
      (segment (start 0 0) (end 1 1) (width 0.25) (layer "F.Cu") (net 1))
      (via (at 0 0) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1))
      (zone (net 1) (net_name "VCC") (layer "B.Cu") (polygon (pts (xy 0 0))))
      (gr_line (start 0 0) (end 1 0) (layer "Edge.Cuts")))"""
    assert parse_kicad_pcb(text) == Netlist()


def test_extraction_is_scoped_to_the_documented_positions() -> None:
    text = """(kicad_pcb (version 20241229)
      (net 1 "REAL")
      (setup (net 2 "SMUGGLED") (footprint "Lib:X" (property "Reference" "GHOST")))
      (footprint "Lib:FP" (layer "F.Cu") (property "Reference" "U1")
        (property "Value" "v" (property "Reference" "GHOST2"))
        (fp_text user "text" (pad "9" smd rect (net 1 "REAL")))
        (pad "1" smd rect (net 1 "REAL") (decoy (net 2 "SMUGGLED")))))"""
    netlist = parse_kicad_pcb(text)
    assert [c.designator for c in netlist.components] == ["U1"]
    assert _net_map(netlist) == {"REAL": {("U1", "1")}}


# ------------------------------------------------------------- refusals


@pytest.mark.parametrize("text", [KICAD_XML, KICAD_SEXPR])
def test_netlist_given_as_board_is_refused_with_redirect(text: str) -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_pcb(text)
    assert excinfo.value.code == "export_format_unsupported"
    assert "expected a .kicad_pcb board file but received a netlist" in str(excinfo.value)


def test_schematic_given_as_board_is_refused_with_guidance() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_pcb(KICAD_SCHEMATIC_HEAD)
    assert excinfo.value.code == "export_format_unsupported"
    assert ".kicad_sch" in str(excinfo.value)


def test_unknown_content_given_as_board_is_refused() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_pcb("not a board at all")
    assert excinfo.value.code == "export_format_unsupported"


def test_malformed_board_is_invalid() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_pcb('(kicad_pcb (version 20241229) (footprint "Lib:FP"')
    assert excinfo.value.code == "export_invalid"
    assert "well-formed" in str(excinfo.value)
