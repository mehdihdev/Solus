"""KiCad S-expression netlist parser tests (SOLUSDEV-252, W0-08 §5.2).

The default `kicad-cli sch export netlist` format (`.net`, `(export …)` root) is
a first-class equal of the XML export: the field mapping is IDENTICAL, so the
governing assertion is PARITY — the same design parsed from either format yields
the same IR. Netlist text is untrusted DATA (§7): traversal is scoped to the
documented positions and leniency inside a valid file surfaces what was dropped
via `Netlist.warnings`. Pure unit — no DB, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.kicad_project import SOLUS_SAMPLE_NETLIST
from fixtures.kicad_sample import KICAD_SEXPR, KICAD_XML
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.eda import Netlist
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.connectors.kicad_netlist_sexpr import parse_sexpr_netlist

#: The real `kicad-cli sch export netlist` (10.0.1, default S-expression format)
#: of the committed fixture schematic — twin of the committed XML export.
SOLUS_SAMPLE_SEXPR_NETLIST = Path(__file__).parent / "fixtures" / "solus_sample.net"


def _net_map(netlist: Netlist) -> dict[str, set[tuple[str, str]]]:
    return {net.name: {(n.designator, n.pin) for n in net.nodes} for net in netlist.nets}


def _identity(netlist: Netlist) -> dict[str, tuple[object, ...]]:
    return {
        c.designator: (
            c.value,
            c.footprint,
            c.part_number,
            c.schematic_symbol_name,
            c.datasheet_ref,
        )
        for c in netlist.components
    }


# ------------------------------------------------------------- parity


def test_hand_fixture_parity_with_xml_twin() -> None:
    sexpr = parse_kicad_netlist(KICAD_SEXPR)
    xml = parse_kicad_netlist(KICAD_XML)
    assert sexpr.components == xml.components
    assert sexpr.nets == xml.nets
    assert sexpr.warnings == () == xml.warnings


def test_dispatcher_and_direct_entry_point_agree() -> None:
    assert parse_sexpr_netlist(KICAD_SEXPR) == parse_kicad_netlist(KICAD_SEXPR)


def test_identity_fields_and_collision_rules_match_xml_semantics() -> None:
    by_ref = {c.designator: c for c in parse_sexpr_netlist(KICAD_SEXPR).components}
    u1 = by_ref["U1"]
    assert u1.part_number == "LM358DR"  # v5-style (field (name "MPN") "…")
    assert u1.schematic_symbol_name == "LM358"
    assert u1.datasheet_ref == "https://www.ti.com/lit/ds/symlink/lm358.pdf"
    assert u1.properties["libsource"] == "Amplifier_Operational:LM358"
    assert u1.properties["Grade"] == "industrial"  # later (property) wins over (field)
    assert "MPN" not in u1.properties
    assert "description" not in u1.properties  # (description …) is ignored, as in XML
    assert by_ref["R1"].part_number == "RC0603FR-0710KL"  # alias via (property)
    assert by_ref["C1"].datasheet_ref is None  # "~" is unset


def test_real_kicad_cli_export_parity_with_committed_xml_export() -> None:
    sexpr = parse_kicad_netlist(SOLUS_SAMPLE_SEXPR_NETLIST.read_text(encoding="utf-8"))
    xml = parse_kicad_netlist(SOLUS_SAMPLE_NETLIST.read_text(encoding="utf-8"))
    assert sexpr.warnings == () == xml.warnings
    assert {c.designator for c in sexpr.components} == {c.designator for c in xml.components}
    assert _identity(sexpr) == _identity(xml)
    # Divergence between the two real exports (Eeschema 10.0.1 S-expr vs 9.0.4
    # XML): KiCad 10 prefixes local-label net names with the sheet path ("/SDA"
    # vs "SDA"). Power/global nets and "unconnected-…" names are identical. The
    # membership invariant holds once that producer-side prefix is normalized.
    sexpr_nets = {name.lstrip("/"): nodes for name, nodes in _net_map(sexpr).items()}
    xml_nets = {name.lstrip("/"): nodes for name, nodes in _net_map(xml).items()}
    assert sexpr_nets == xml_nets


def test_real_export_component_count_and_mpns() -> None:
    netlist = parse_sexpr_netlist(SOLUS_SAMPLE_SEXPR_NETLIST.read_text(encoding="utf-8"))
    by_ref = {c.designator: c for c in netlist.components}
    assert set(by_ref) == {"C1", "C2", "C3", "C4", "R1", "R2", "R3", "U1", "U2"}
    assert by_ref["U1"].part_number == "STM32F030F4P6"
    assert by_ref["U1"].schematic_symbol_name == "STM32F030F4Px"
    assert by_ref["C1"].datasheet_ref is None
    # An empty (value "") property is absence, exactly as an empty XML value is.
    assert "Sheetname" not in by_ref["C1"].properties
    assert by_ref["C1"].properties["Sheetfile"] == "solus_sample.kicad_sch"


# ------------------------------------------------------------- shape / leniency


def test_empty_sections_yield_empty_netlist() -> None:
    netlist = parse_sexpr_netlist('(export (version "E") (components) (nets))')
    assert netlist == Netlist()


def test_missing_sections_yield_empty_netlist() -> None:
    assert parse_sexpr_netlist('(export (version "E"))') == Netlist()


def test_field_without_value_is_absence() -> None:
    text = '(export (components (comp (ref "C1") (fields (field (name "Datasheet"))))))'
    c1 = parse_sexpr_netlist(text).components[0]
    assert "Datasheet" not in c1.properties
    assert c1.value is None
    assert c1.footprint is None
    assert c1.schematic_symbol_name is None


def test_component_without_ref_is_skipped_with_warning() -> None:
    text = '(export (components (comp (value "orphan")) (comp (ref "R9") (value "1k"))))'
    netlist = parse_sexpr_netlist(text)
    assert [c.designator for c in netlist.components] == ["R9"]
    assert any("component" in w for w in netlist.warnings)


def test_net_without_name_and_incomplete_nodes_are_skipped_with_warnings() -> None:
    text = """(export
      (components (comp (ref "R1") (value "1k")))
      (nets
        (net (code "1") (node (ref "R1") (pin "1")))
        (net (code "2") (name "OK")
          (node (ref "R1") (pin "2"))
          (node (ref "R1"))
          (node (pin "3")))))"""
    netlist = parse_sexpr_netlist(text)
    assert [n.name for n in netlist.nets] == ["OK"]
    assert [(n.designator, n.pin) for n in netlist.nets[0].nodes] == [("R1", "2")]
    assert any("net" in w for w in netlist.warnings)
    assert any("node" in w for w in netlist.warnings)


def test_extraction_is_scoped_to_the_documented_schema() -> None:
    # A comp smuggled under (design), fields nested under (libsource), a node
    # under a decoy list: none of it may reach properties, hints, or the graph.
    text = """(export
      (design (comp (ref "GHOST")) (nets (net (code "9") (name "GHOSTNET"))))
      (components
        (comp (ref "R1") (value "1k")
          (libsource (lib "Device") (part "R")
            (field (name "MPN") "EVIL-MPN")
            (property (name "Sneaky") (value "nested")))
          (fields (nested (field (name "MPN") "ALSO-EVIL"))))
        (decoy (comp (ref "GHOST2"))))
      (nets
        (net (code "1") (name "OK")
          (node (ref "R1") (pin "1"))
          (decoy (node (ref "R1") (pin "2"))))
        (decoy (net (code "9") (name "GHOSTNET") (node (ref "R1") (pin "3"))))))"""
    netlist = parse_sexpr_netlist(text)
    assert [c.designator for c in netlist.components] == ["R1"]
    r1 = netlist.components[0]
    assert r1.part_number is None
    assert "Sneaky" not in r1.properties
    assert [n.name for n in netlist.nets] == ["OK"]
    assert [(n.designator, n.pin) for n in netlist.nets[0].nodes] == [("R1", "1")]


# ------------------------------------------------------------- untrusted input


def test_wrong_root_is_refused() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_sexpr_netlist("(kicad_pcb (version 20241229))")
    assert excinfo.value.code == "export_invalid"
    assert "(export" in str(excinfo.value)


def test_malformed_sexpr_is_refused() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        parse_sexpr_netlist('(export (components (comp (ref "U1")')
    assert excinfo.value.code == "export_invalid"
    assert "well-formed" in str(excinfo.value)


def test_resource_guard_trip_is_refused_as_invalid() -> None:
    deep = "(export " + "(" * 200 + ")" * 200 + ")"
    with pytest.raises(ConnectorError) as excinfo:
        parse_sexpr_netlist(deep)
    assert excinfo.value.code == "export_invalid"
