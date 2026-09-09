"""KiCad netlist dispatcher + XML parser tests (SOLUSDEV-100/252, W0-08 §5.2).

The v1 KiCad format is the XML netlist (`kicad-cli sch export netlist --format
kicadxml`) — schema-stable v5–v10 and stdlib-parseable. The parser produces the
shared EDA IR; identity fields (MPN → `part_number`, libsource → `schematic_symbol_name`,
datasheet → `datasheet_ref`) feed the fingerprint per W0-08 §5.2. Netlist text is
untrusted DATA (§7): DTD/entity tricks are refused, raw `.kicad_sch`/`.kicad_pro`
files are refused with guidance naming the accepted routes (SOLUSDEV-252), and
lenient handling inside valid XML surfaces what was dropped via `Netlist.warnings`.
`parse_kicad_netlist` is the content-sniffing dispatcher: XML here, the default
S-expression `.net` in `kicad_netlist_sexpr` (parity-tested there). Pure unit —
no DB, no network.
"""

from __future__ import annotations

import pytest
from fixtures.kicad_sample import (
    KICAD_PCB,
    KICAD_PROJECT_HEAD,
    KICAD_SCHEMATIC_HEAD,
    KICAD_SEXPR,
    KICAD_XML,
)
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.eda import Component, Node
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


def test_sexpr_netlist_is_accepted_as_a_first_class_equal() -> None:
    # SOLUSDEV-252: the default `.net` S-expression export parses through the
    # same dispatcher to the same IR as the XML export (parity is asserted in
    # test_kicad_netlist_sexpr.py).
    netlist = parse_kicad_netlist(KICAD_SEXPR)
    assert {c.designator for c in netlist.components} == {"U1", "R1", "C1"}
    assert {n.name for n in netlist.nets} == {"VCC", "GND", "SIGNAL"}
    assert netlist.warnings == ()


def test_custom_field_collision_later_property_wins() -> None:
    assert _components()["U1"].properties["Grade"] == "industrial"


# ------------------------------------------- refused formats (SOLUSDEV-252)


def _refused(text: str) -> str:
    with pytest.raises(ConnectorError) as excinfo:
        parse_kicad_netlist(text)
    assert excinfo.value.code == "export_format_unsupported"
    return str(excinfo.value)


def test_raw_schematic_is_refused_naming_both_accepted_routes() -> None:
    message = _refused(KICAD_SCHEMATIC_HEAD)
    assert ".kicad_sch" in message
    assert "kicad-cli sch export netlist" in message
    assert ".kicad_pcb" in message


def test_project_file_is_refused_naming_both_accepted_routes() -> None:
    message = _refused(KICAD_PROJECT_HEAD)
    assert ".kicad_pro" in message
    assert "Export a netlist" in message
    assert ".kicad_pcb" in message


def test_board_given_as_netlist_is_refused_with_redirect() -> None:
    assert "supply it as the board, not as the netlist export" in _refused(KICAD_PCB)


def test_unrecognized_content_is_refused() -> None:
    message = _refused("this is not a kicad file of any kind")
    assert "unrecognized file" in message
    assert "XML or S-expression" in message
    assert ".kicad_pcb" in message


# ------------------------------------------------ shared record builders (P1)


def test_shared_builders_apply_the_family_rules_once_for_both_formats() -> None:
    # SOLUSDEV-252 Phase 4 (P1): the XML and S-expression mappings feed the SAME
    # component/net builders, so skip counting, warning strings, MPN popping and
    # libsource handling cannot drift between formats.
    from solus_api.connectors.kicad_netlist import (
        ComponentRecord,
        NetRecord,
        build_components,
        build_nets,
    )

    warnings: list[str] = []
    fields = {"MPN": "LM358DR", "Grade": "industrial"}
    components = build_components(
        [
            ComponentRecord(
                ref="U1",
                value="LM358",
                footprint="SOIC-8",
                datasheet=None,
                fields=fields,
                library="Amplifier_Operational",
                symbol="LM358",
            ),
            ComponentRecord(ref=None, value="ghost", footprint=None, datasheet=None, fields={}),
        ],
        warnings,
    )
    assert [c.designator for c in components] == ["U1"]
    assert components[0].part_number == "LM358DR"
    assert components[0].schematic_symbol_name == "LM358"
    assert components[0].properties == {
        "Grade": "industrial",
        "libsource": "Amplifier_Operational:LM358",
    }
    assert fields == {"MPN": "LM358DR", "Grade": "industrial"}  # the record is not mutated

    nets = build_nets(
        [
            NetRecord(
                name="VCC", net_class="Power", nodes=(("U1", "8"), (None, "1"), ("U1", None))
            ),
            NetRecord(name=None, net_class=None, nodes=(("U1", "4"),)),
        ],
        warnings,
    )
    assert [(n.name, n.net_class, n.nodes) for n in nets] == [("VCC", "Power", (Node("U1", "8"),))]
    assert warnings == [
        "skipped 1 component(s) without a ref designator",
        "skipped 1 net(s) without a name",
        "skipped 2 net node(s) missing ref/pin",
    ]
