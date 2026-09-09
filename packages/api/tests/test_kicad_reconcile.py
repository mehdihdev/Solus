"""Netlist/board reconciliation tests (SOLUSDEV-252, W0-08 §5.2a).

One KiCad source may hold a netlist export AND a `.kicad_pcb`. The netlist is
authoritative for identity and connectivity; the board corroborates (layer) and
every disagreement is REPORTED as a `board/netlist mismatch: ` warning, never
merged silently. Inputs are the shared EDA IR parsed from the hand fixtures
(one design in XML, S-expression and board form) plus string-replaced variants.
Pure unit — no DB, no network.
"""

from __future__ import annotations

import copy

import pytest
from fixtures.kicad_sample import KICAD_PCB, KICAD_SEXPR, KICAD_XML
from solus_api.connectors.eda import Component, Net, Netlist, Node
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.connectors.kicad_pcb import parse_kicad_pcb
from solus_api.connectors.kicad_reconcile import (
    MAX_MISMATCH_WARNINGS,
    MISMATCH_PREFIX,
    mismatch_item,
    reconcile_kicad,
)

NETLIST = parse_kicad_netlist(KICAD_XML)
BOARD = parse_kicad_pcb(KICAD_PCB)

#: The two footprints present on the fixture board but absent from the netlist.
BOARD_ONLY_REPORTS = (
    f"{MISMATCH_PREFIX}H1: placed on board but not in netlist",
    f"{MISMATCH_PREFIX}FID1: placed on board but not in netlist",
)


def _mismatches(netlist: Netlist) -> list[str]:
    """The reconciliation report: prefixed findings plus the trailing `… N more` note."""
    return [w for w in netlist.warnings if w.startswith((MISMATCH_PREFIX, "…"))]


def _board(text: str = KICAD_PCB) -> Netlist:
    return parse_kicad_pcb(text)


# ------------------------------------------------------------ passthrough


def test_netlist_only_is_returned_unchanged() -> None:
    assert reconcile_kicad(NETLIST, None) is NETLIST


def test_board_only_is_returned_unchanged_as_the_connectivity_source() -> None:
    merged = reconcile_kicad(None, BOARD)
    assert merged is BOARD
    # The board carries no libsource: the hint stays absent, never guessed (§5.2a).
    assert all(c.schematic_symbol_name is None for c in merged.components)
    assert {n.name for n in merged.nets} == {"VCC", "GND", "SIGNAL"}


def test_neither_input_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        reconcile_kicad(None, None)


# ------------------------------------------------------- netlist authority


@pytest.mark.parametrize("netlist_text", [KICAD_XML, KICAD_SEXPR], ids=["xml", "sexpr"])
def test_netlist_is_authoritative_for_identity_and_connectivity(netlist_text: str) -> None:
    netlist = parse_kicad_netlist(netlist_text)
    merged = reconcile_kicad(netlist, BOARD)

    # Components are the netlist's (H1/FID1 are NOT added); nets are the netlist's.
    assert [c.designator for c in merged.components] == ["U1", "R1", "C1"]
    assert merged.nets == netlist.nets
    identity = {
        c.designator: (c.value, c.footprint, c.part_number, c.schematic_symbol_name)
        for c in merged.components
    }
    assert identity == {
        c.designator: (c.value, c.footprint, c.part_number, c.schematic_symbol_name)
        for c in netlist.components
    }
    assert merged.components[0].schematic_symbol_name == "LM358"


def test_board_layer_enriches_matching_components() -> None:
    merged = reconcile_kicad(NETLIST, BOARD)
    layers = {c.designator: c.properties.get("layer") for c in merged.components}
    assert layers == {"U1": "F.Cu", "R1": "F.Cu", "C1": "B.Cu"}
    # Corroborating metadata only — the netlist's own properties are kept.
    u1 = merged.components[0]
    assert u1.properties["libsource"] == "Amplifier_Operational:LM358"
    assert u1.properties["Grade"] == "industrial"


def test_component_without_a_board_layer_is_not_enriched() -> None:
    board = Netlist(components=(Component(designator="U1"),))
    merged = reconcile_kicad(NETLIST, board)
    assert "layer" not in merged.components[0].properties


def test_warnings_from_both_parsers_are_kept_in_order() -> None:
    netlist = Netlist(
        components=(Component(designator="U1"),),
        warnings=("skipped 1 component(s) without a ref designator",),
    )
    merged = reconcile_kicad(netlist, BOARD)
    assert merged.warnings[0] == "skipped 1 component(s) without a ref designator"
    # The fixture board's reference-less logo footprint is counted by the board parser.
    assert merged.warnings[1] == "skipped 1 footprint(s) without a reference designator"
    assert all(w.startswith(MISMATCH_PREFIX) for w in merged.warnings[2:])


# ----------------------------------------------------------- refdes mismatch


def test_fixture_board_only_parts_are_reported_not_added() -> None:
    merged = reconcile_kicad(NETLIST, BOARD)
    assert _mismatches(merged) == list(BOARD_ONLY_REPORTS)
    assert {c.designator for c in merged.components}.isdisjoint({"H1", "FID1"})


def test_netlist_part_missing_from_the_board_is_reported() -> None:
    netlist = Netlist(
        components=(*NETLIST.components, Component(designator="U3", value="X")),
        nets=NETLIST.nets,
    )
    merged = reconcile_kicad(netlist, BOARD)
    assert f"{MISMATCH_PREFIX}U3: in netlist but not placed on board" in merged.warnings
    assert "U3" in {c.designator for c in merged.components}


# --------------------------------------------------- value/footprint mismatch


def test_value_difference_is_reported() -> None:
    board = _board(KICAD_PCB.replace('(property "Value" "10k"', '(property "Value" "22k"'))
    merged = reconcile_kicad(NETLIST, board)
    assert f"{MISMATCH_PREFIX}R1: value differs (netlist '10k', board '22k')" in merged.warnings
    # Identity stays the netlist's.
    assert next(c for c in merged.components if c.designator == "R1").value == "10k"


def test_footprint_difference_is_reported() -> None:
    board = _board(
        KICAD_PCB.replace(
            '(property "Footprint" "Resistor_SMD:R_0603_1608Metric"',
            '(property "Footprint" "Resistor_SMD:R_0805_2012Metric"',
        )
    )
    merged = reconcile_kicad(NETLIST, board)
    assert (
        f"{MISMATCH_PREFIX}R1: footprint differs (netlist 'Resistor_SMD:R_0603_1608Metric', "
        "board 'Resistor_SMD:R_0805_2012Metric')"
    ) in merged.warnings


def test_value_comparison_strips_whitespace_and_skips_none() -> None:
    netlist = Netlist(
        components=(Component(designator="R1", value=" 10k ", footprint=None),),
        nets=(),
    )
    board = Netlist(components=(Component(designator="R1", value="10k", footprint="X"),))
    assert _mismatches(reconcile_kicad(netlist, board)) == []


# ------------------------------------------------------ connectivity mismatch


def test_board_pin_on_a_different_net_is_reported() -> None:
    # R1 pad 2 is on SIGNAL in the netlist; move it to GND on the board.
    board = _board(
        KICAD_PCB.replace(
            '(roundrect_rratio 0.25) (net 3 "SIGNAL") (pintype "passive")\n'
            '      (uuid "0b2a6d3e-0000-4000-8000-000000000222")',
            '(roundrect_rratio 0.25) (net 2 "GND") (pintype "passive")\n'
            '      (uuid "0b2a6d3e-0000-4000-8000-000000000222")',
        )
    )
    merged = reconcile_kicad(NETLIST, board)
    assert f"{MISMATCH_PREFIX}R1 pin 2: board net 'GND' but netlist net 'SIGNAL'" in merged.warnings
    # The board's move never reaches the graph: connectivity stays the netlist's.
    assert merged.nets == NETLIST.nets


def test_board_pin_with_no_netlist_net_is_reported() -> None:
    # R1 pad 1 is unconnected in the netlist; connect it to GND on the board.
    board = _board(
        KICAD_PCB.replace(
            '(roundrect_rratio 0.25) (uuid "0b2a6d3e-0000-4000-8000-000000000221"))',
            '(roundrect_rratio 0.25) (net 2 "GND") (uuid "0b2a6d3e-0000-4000-8000-000000000221"))',
        )
    )
    merged = reconcile_kicad(NETLIST, board)
    assert (
        f"{MISMATCH_PREFIX}R1 pin 1: on board net 'GND' but has no net in netlist"
        in merged.warnings
    )


def test_board_net_absent_from_the_netlist_is_reported_once() -> None:
    board = Netlist(
        components=(Component(designator="H1"),),
        nets=(Net(name="SHIELD", nodes=(Node("H1", "1"), Node("H1", "2"))),),
    )
    merged = reconcile_kicad(NETLIST, board)
    mismatches = _mismatches(merged)
    assert mismatches.count(f"{MISMATCH_PREFIX}net 'SHIELD': on board but not in netlist") == 1
    # H1 is not in the netlist, so its pins are not reported individually.
    assert not any("H1 pin" in m for m in mismatches)


def test_netlist_nodes_absent_from_the_board_are_not_reported_per_pin() -> None:
    # Strip C1's pads from the board: C1 stays placed, its pins just aren't wired.
    board = Netlist(
        components=BOARD.components,
        nets=tuple(
            Net(name=n.name, nodes=tuple(x for x in n.nodes if x.designator != "C1"))
            for n in BOARD.nets
        ),
    )
    merged = reconcile_kicad(NETLIST, board)
    assert not any("C1 pin" in m for m in _mismatches(merged))


def test_kicad10_sheet_path_prefix_is_normalized_before_comparing() -> None:
    # KiCad 10 writes local labels as "/SIGNAL" where KiCad 9 wrote "SIGNAL";
    # the same design across producers must not read as a connectivity mismatch.
    board = _board(KICAD_PCB.replace('"SIGNAL"', '"/SIGNAL"'))
    merged = reconcile_kicad(NETLIST, board)
    assert _mismatches(merged) == list(BOARD_ONLY_REPORTS)
    # Normalization is for COMPARISON only — the graph keeps the netlist's names.
    assert {n.name for n in merged.nets} == {"VCC", "GND", "SIGNAL"}


def test_only_one_leading_slash_is_normalized() -> None:
    board = _board(KICAD_PCB.replace('"SIGNAL"', '"//SIGNAL"'))
    merged = reconcile_kicad(NETLIST, board)
    assert f"{MISMATCH_PREFIX}net '//SIGNAL': on board but not in netlist" in merged.warnings


# --------------------------------------------------------------- the cap


def test_mismatch_warnings_are_capped_with_a_trailing_count() -> None:
    # A totally unrelated board: every one of its parts is a mismatch. The
    # report is bounded so it cannot amplify into megabytes (§7).
    extra = MAX_MISMATCH_WARNINGS + 57
    board = Netlist(components=tuple(Component(designator=f"X{i}") for i in range(extra)))
    merged = reconcile_kicad(NETLIST, board)
    mismatches = _mismatches(merged)
    assert len(mismatches) == MAX_MISMATCH_WARNINGS + 1
    # extra board-only + 3 netlist parts not placed → 60 over the cap.
    assert mismatches[-1] == f"… 60 more {MISMATCH_PREFIX.rstrip(': ')}es"
    assert mismatches[0] == f"{MISMATCH_PREFIX}X0: placed on board but not in netlist"


def test_no_trailing_count_when_under_the_cap() -> None:
    merged = reconcile_kicad(NETLIST, BOARD)
    assert not any(m.startswith("…") for m in _mismatches(merged))


# ----------------------------------------------------------- immutability


def test_inputs_are_not_mutated() -> None:
    netlist = parse_kicad_netlist(KICAD_XML)
    board = parse_kicad_pcb(KICAD_PCB)
    netlist_before, board_before = copy.deepcopy(netlist), copy.deepcopy(board)
    merged = reconcile_kicad(netlist, board)
    assert netlist == netlist_before
    assert board == board_before
    assert merged is not netlist
    # Enrichment produced NEW component objects; the originals carry no layer.
    assert all("layer" not in c.properties for c in netlist.components)


# ------------------------------------------------------------- item labels


@pytest.mark.parametrize(
    ("warning", "item"),
    [
        (f"{MISMATCH_PREFIX}H1: placed on board but not in netlist", "H1"),
        (f"{MISMATCH_PREFIX}R1: value differs (netlist '10k', board '22k')", "R1"),
        (f"{MISMATCH_PREFIX}R1 pin 2: board net 'GND' but netlist net 'SIGNAL'", "R1 pin 2"),
        (f"{MISMATCH_PREFIX}net 'SHIELD': on board but not in netlist", "net 'SHIELD'"),
        ("… 60 more board/netlist mismatches", None),
        ("skipped 1 footprint(s) without a reference designator", None),
    ],
)
def test_mismatch_item_recovers_the_refdes_or_net_label(warning: str, item: str | None) -> None:
    # The connector relabels `build_graph`'s generic `parse` SyncErrors with this
    # so the sync record says WHICH part disagrees (CLAUDE.md §6 — debuggable).
    assert mismatch_item(warning) == item


def test_mismatch_item_bounds_an_adversarial_label() -> None:
    long_name = "N" * 500
    item = mismatch_item(f"{MISMATCH_PREFIX}net '{long_name}': on board but not in netlist")
    assert item is not None and len(item) < 100


# ------------------------------------------------------ bounded messages (S2)


def test_interpolated_ingested_values_are_bounded_in_every_message() -> None:
    from solus_api.connectors.eda import build_graph
    from solus_api.connectors.export_common import MESSAGE_LIMIT, TOTAL_BYTES_LIMIT

    huge_a, huge_b, huge_net = "A" * 70_000, "B" * 70_000, "N" * 70_000
    netlist = Netlist(
        components=(
            Component(designator="R1", value=huge_a, footprint=huge_a),
            Component(designator="R2"),
            Component(designator=huge_a),
        ),
        nets=(Net(name="SIG", nodes=(Node("R1", "1"),)),),
    )
    board = Netlist(
        components=(Component(designator="R1", value=huge_b, footprint=huge_b),),
        nets=(
            Net(name=huge_net, nodes=(Node("R1", "1"), Node("R2", "1"))),
            Net(name="SIG", nodes=(Node("R1", "2"),)),
        ),
    )
    merged = reconcile_kicad(netlist, board)
    mismatches = _mismatches(merged)
    assert len(mismatches) >= 6  # value, footprint, 2 pins, net, unplaced R2, unplaced huge
    assert all(len(w) <= MESSAGE_LIMIT for w in merged.warnings)
    assert any("value differs" in w and "…" in w for w in mismatches)

    _, _, errors = build_graph(merged)
    assert all(len(e.message) <= MESSAGE_LIMIT for e in errors)
    assert sum(len(e.message) + len(e.item) for e in errors) < TOTAL_BYTES_LIMIT


# ------------------------------------------------- bounded materialization (S8)


class _CountingStr(str):
    """A designator that counts how many times it is rendered into a message."""

    renders = 0

    def __format__(self, spec: str) -> str:
        type(self).renders += 1
        return str.__format__(self, spec)


def test_at_most_the_cap_of_finding_strings_are_ever_built() -> None:
    _CountingStr.renders = 0
    board_only = 5_000 - len(NETLIST.components)  # + 3 netlist parts not placed = 5,000
    board = Netlist(
        components=tuple(Component(designator=_CountingStr(f"X{i}")) for i in range(board_only))
    )

    merged = reconcile_kicad(NETLIST, board)

    mismatches = _mismatches(merged)
    assert len(mismatches) == MAX_MISMATCH_WARNINGS + 1
    assert mismatches[-1] == f"… {5_000 - MAX_MISMATCH_WARNINGS} more board/netlist mismatches"
    # The remainder was COUNTED, never rendered: only kept findings became strings.
    assert _CountingStr.renders <= MAX_MISMATCH_WARNINGS
