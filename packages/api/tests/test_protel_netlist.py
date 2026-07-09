"""Protel-netlist parser tests (SOLUSDEV-102, W0-08 §5.4/§6.3).

The parser is pure (text in → shared EDA netlist IR out) and lenient: malformed
blocks/nodes are skipped rather than raising, so one bad line never fails a whole
sync. Ingested netlist text is untrusted data, parsed without eval/exec/subprocess
(CLAUDE.md §7).
"""

from __future__ import annotations

from solus_api.connectors.protel_netlist import parse_protel_netlist

SAMPLE = """[
U1
SOIC-8
LM358

]
[
R1
0603
10k

]
[
C1
0603
100nF

]
(
VCC
U1-8
R1-1
)
(
GND
U1-4
C1-2
)
(
SIGNAL
U1-1
R1-2
C1-1
)
"""


def test_parses_components_with_footprint_and_value() -> None:
    netlist = parse_protel_netlist(SAMPLE)
    by_ref = {c.designator: c for c in netlist.components}
    assert set(by_ref) == {"U1", "R1", "C1"}
    assert by_ref["U1"].footprint == "SOIC-8"
    assert by_ref["U1"].value == "LM358"
    assert by_ref["R1"].value == "10k"


def test_parses_nets_and_nodes() -> None:
    netlist = parse_protel_netlist(SAMPLE)
    by_name = {n.name: n for n in netlist.nets}
    assert set(by_name) == {"VCC", "GND", "SIGNAL"}
    signal_nodes = {(n.designator, n.pin) for n in by_name["SIGNAL"].nodes}
    assert signal_nodes == {("U1", "1"), ("R1", "2"), ("C1", "1")}


def test_skips_malformed_node_lines_leniently() -> None:
    netlist = parse_protel_netlist("(\nN1\nU1-1\ngarbage_no_dash\n)\n")
    net = netlist.nets[0]
    assert [(n.designator, n.pin) for n in net.nodes] == [("U1", "1")]


def test_pin_with_named_pin_splits_on_first_dash() -> None:
    netlist = parse_protel_netlist("(\nN1\nU1-A2\n)\n")
    node = netlist.nets[0].nodes[0]
    assert (node.designator, node.pin) == ("U1", "A2")


def test_empty_input_yields_empty_netlist() -> None:
    netlist = parse_protel_netlist("")
    assert netlist.components == ()
    assert netlist.nets == ()


def test_unterminated_block_is_ignored_not_crashing() -> None:
    # A component block with no closing ']' should not raise.
    netlist = parse_protel_netlist("[\nU1\nSOIC-8\nLM358\n")
    assert netlist.components == ()


def test_dropped_blocks_are_surfaced_as_warnings() -> None:
    # The unterminated block is skipped but reported, not silently lost.
    netlist = parse_protel_netlist("[\nU1\nSOIC-8\n")
    assert netlist.warnings
    assert "skipped" in netlist.warnings[0]


def test_clean_netlist_has_no_warnings() -> None:
    assert parse_protel_netlist(SAMPLE).warnings == ()
