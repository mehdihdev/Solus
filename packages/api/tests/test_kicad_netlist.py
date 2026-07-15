"""KiCad XML netlist parser tests (SOLUSDEV-100, W0-08 §5.2).

The v1 KiCad format is the XML netlist (`kicad-cli sch export netlist --format
kicadxml`) — schema-stable v5–v10 and stdlib-parseable. The parser produces the
shared EDA IR; identity fields (MPN → `part_number`, libsource → `schematic_symbol_name`,
datasheet → `datasheet_ref`) feed the fingerprint per W0-08 §5.2. Netlist text is
untrusted DATA (§7): DTD/entity tricks are refused, the S-expr `.net` format is
rejected with re-export guidance (XML-only v1), and lenient handling inside valid
XML surfaces what was dropped via `Netlist.warnings`. Pure unit — no DB, no network.
"""

from __future__ import annotations

import pytest
from fixtures.kicad_sample import KICAD_XML
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.eda import Component
from solus_api.connectors.kicad_netlist import parse_kicad_netlist


def _components(text: str = KICAD_XML) -> dict[str, Component]:
    return {c.designator: c for c in parse_kicad_netlist(text).components}


# ------------------------------------------------------------- happy path


def test_parses_components_with_identity_fields() -> None:
    by_ref = _components()
    assert set(by_ref) == {"U1", "R1", "C1"}
    u1 = by_ref["U1"]
    assert u1.value == "LM358"
    assert u1.footprint == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    # The three W0-08 §5.2 fingerprint channels:
    assert u1.part_number == "LM358DR"
    assert u1.schematic_symbol_name == "LM358"
    assert u1.datasheet_ref == "https://www.ti.com/lit/ds/symlink/lm358.pdf"


def test_mpn_recognized_from_property_element_and_alias() -> None:
    # v6+ emits symbol fields as <property name value>; the alias list catches
    # the common non-"MPN" spellings (delegated-judgment decision, SOLUSDEV-100).
    assert _components()["R1"].part_number == "RC0603FR-0710KL"


def test_placeholder_datasheet_is_not_a_hint() -> None:
    # KiCad writes "~" for an unset datasheet — that is absence, not a reference.
    c1 = _components()["C1"]
    assert c1.datasheet_ref is None
    assert c1.part_number is None


def test_custom_fields_land_in_properties_but_mpn_stays_out() -> None:
    u1 = _components()["U1"]
    assert u1.properties["Tolerance"] == "n/a"
    assert u1.properties["libsource"] == "Amplifier_Operational:LM358"
    # Supply-chain identity is the fingerprint's channel, not a display property.
    assert "MPN" not in u1.properties


def test_parses_nets_with_class_and_nodes() -> None:
    netlist = parse_kicad_netlist(KICAD_XML)
    by_name = {n.name: n for n in netlist.nets}
    assert set(by_name) == {"VCC", "GND", "SIGNAL"}
    assert by_name["VCC"].net_class == "Power"
    assert by_name["GND"].net_class is None
    vcc_nodes = {(node.designator, node.pin) for node in by_name["VCC"].nodes}
    assert vcc_nodes == {("U1", "8"), ("C1", "1")}


def test_clean_parse_has_no_warnings() -> None:
    assert parse_kicad_netlist(KICAD_XML).warnings == ()


def test_empty_sections_yield_empty_netlist() -> None:
    netlist = parse_kicad_netlist('<export version="E"><components/><nets/></export>')
    assert netlist.components == ()
    assert netlist.nets == ()
    assert netlist.warnings == ()


# ------------------------------------------------------------- leniency


def test_component_without_ref_is_skipped_with_warning() -> None:
    text = """<export version="E">
      <components>
        <comp><value>orphan</value></comp>
        <comp ref="R9"><value>1k</value></comp>
      </components>
      <nets/>
    </export>"""
    netlist = parse_kicad_netlist(text)
    assert [c.designator for c in netlist.components] == ["R9"]
    assert any("component" in w for w in netlist.warnings)


def test_net_without_name_and_incomplete_nodes_are_skipped_with_warnings() -> None:
    text = """<export version="E">
      <components><comp ref="R1"><value>1k</value></comp></components>
      <nets>
        <net code="1"><node ref="R1" pin="1"/></net>
        <net code="2" name="OK">
          <node ref="R1" pin="2"/>
          <node ref="R1"/>
          <node pin="3"/>
        </net>
      </nets>
    </export>"""
    netlist = parse_kicad_netlist(text)
    assert [n.name for n in netlist.nets] == ["OK"]
    assert [(node.designator, node.pin) for node in netlist.nets[0].nodes] == [("R1", "2")]
    assert any("net" in w for w in netlist.warnings)
    assert any("node" in w for w in netlist.warnings)


def test_extraction_is_scoped_to_the_documented_schema() -> None:
    # Review finding (SOLUSDEV-100 Phase 4): traversal must read only the
    # documented positions — <components>/<comp>, <fields>/<field>, comp-direct
    # <property>, <nets>/<net>, net-direct <node>. Adversarial content nested
    # anywhere else must not be smuggled into properties, hints, or the graph.
    text = """<export version="E">
      <components>
        <comp ref="R1">
          <value>1k</value>
          <libsource lib="Device" part="R">
            <field name="MPN">EVIL-MPN</field>
            <property name="Sneaky" value="nested"/>
          </libsource>
        </comp>
        <decoy><comp ref="GHOST"/></decoy>
      </components>
      <nets>
        <net code="1" name="OK">
          <node ref="R1" pin="1"/>
          <decoy><node ref="R1" pin="2"/></decoy>
        </net>
        <decoy><net code="9" name="GHOSTNET"><node ref="R1" pin="3"/></net></decoy>
      </nets>
    </export>"""
    netlist = parse_kicad_netlist(text)
    assert [c.designator for c in netlist.components] == ["R1"]
    r1 = netlist.components[0]
    assert r1.part_number is None
    assert "Sneaky" not in r1.properties
    assert [n.name for n in netlist.nets] == ["OK"]
    assert [(node.designator, node.pin) for node in netlist.nets[0].nodes] == [("R1", "1")]


def test_missing_value_and_footprint_are_none() -> None:
    text = '<export version="E"><components><comp ref="J1"/></components><nets/></export>'
    j1 = parse_kicad_netlist(text).components[0]
    assert j1.value is None
    assert j1.footprint is None
    assert j1.part_number is None
    assert j1.schematic_symbol_name is None


# ------------------------------------------------- untrusted input (§7)


def test_dtd_and_entity_declarations_are_refused() -> None:
    bomb = """<?xml version="1.0"?>
    <!DOCTYPE export [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>
    <export version="E"><components/><nets/></export>"""
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_netlist(bomb)
    assert excinfo.value.code == "export_invalid"


def test_malformed_xml_is_refused() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_netlist('<export version="E"><components><comp ref="U1">')
    assert excinfo.value.code == "export_invalid"


def test_non_netlist_xml_root_is_refused() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_netlist("<html><body>not a netlist</body></html>")
    assert excinfo.value.code == "export_invalid"


def test_sexpr_netlist_is_rejected_with_reexport_guidance() -> None:
    # XML-only v1 (design review Q2): the default S-expr `.net` gets a clear
    # "re-export as XML" error, not a confusing parse failure.
    sexpr = '(export (version "E") (components (comp (ref "U1"))))'
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_netlist(sexpr)
    assert excinfo.value.code == "export_format_unsupported"
    assert "kicad-cli" in str(excinfo.value)
