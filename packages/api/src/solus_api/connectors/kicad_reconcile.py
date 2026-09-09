"""Netlist/board reconciliation for one KiCad source (SOLUSDEV-252, W0-08 §5.2a).

A KiCad source may hold a netlist export (`config["export"]`) and/or a
`.kicad_pcb` (`config["board"]`), each already parsed into the shared EDA IR.
The contract's reconciliation law (§5.2a, mirroring §5.3):

* the NETLIST is authoritative for component identity and connectivity — the
  output components and nets are the netlist's;
* the board CORROBORATES: its placement layer is added to a matching component
  as `properties["layer"]`, nothing else;
* disagreement is NEVER merged silently — a refdes present on one side only, a
  differing value or footprint, and a pad-net membership the netlist does not
  carry are each reported as a `Netlist.warnings` entry prefixed
  `board/netlist mismatch: `, which `build_graph` surfaces as per-item
  `SyncError`s for the checker/agent layer;
* with only one input present the reconciler is the identity — a board-only
  source uses the board as its connectivity source (`schematic_symbol_name`
  stays absent by design).

Net names are compared after normalizing ONE leading `/`: KiCad 10 prefixes
local-label nets with the sheet path (`/SDA`) where KiCad 9 wrote `SDA`, and a
board saved by either version must not read as a rewired design. The graph keeps
the netlist's names verbatim — normalization is for comparison only.

Pure function over immutable inputs, no I/O. The report is bounded twice over,
because both dimensions are attacker-controlled (CLAUDE.md §7 — bound message
sizes; `build_graph`'s own caps are the second line of defense):

* COUNT — findings are produced lazily as descriptors and only the first
  `MAX_MISMATCH_WARNINGS` are ever RENDERED into strings; the rest are counted
  without being built, so an unrelated 8 MiB board cannot materialize a string
  per pad;
* SIZE — every ingested value interpolated into a finding (designator, pin,
  value, footprint, net name) is clipped to `VALUE_LIMIT` first, so no single
  message can carry a 70 KB field verbatim onto the Sync row.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from itertools import chain
from typing import Final, Literal

from solus_api.connectors.eda import Component, Netlist
from solus_api.connectors.export_common import label as _label

#: Every reconciliation finding starts with this so the UI/agent can group them.
MISMATCH_PREFIX: Final = "board/netlist mismatch: "

#: Upper bound on mismatch warnings per reconciliation; overflow collapses into
#: one trailing count (defense in depth under `build_graph`'s `MAX_SYNC_ERRORS`).
MAX_MISMATCH_WARNINGS: Final = 200

#: Longest ingested value kept verbatim inside a finding. Chosen so the worst
#: case (a clipped subject plus two clipped values plus the fixed wording) stays
#: well under `export_common.MESSAGE_LIMIT`.
VALUE_LIMIT: Final = 96

#: KiCad 10's sheet-path prefix on local-label net names (module docstring).
_SHEET_PATH_PREFIX: Final = "/"

#: Every finding is `<subject>: <detail>`; `mismatch_item` recovers the subject.
_ITEM_SEPARATOR: Final = ": "

#: (designator, pin) → net name, one side's connectivity flattened for lookup.
_PinNets = dict[tuple[str, str], str]


def _clip(value: str) -> str:
    """An ingested value, bounded before it can enter a message (§7)."""
    return _label(value, VALUE_LIMIT)


@dataclass(frozen=True)
class _Finding:
    """One mismatch, NOT yet rendered. Holding references instead of a formatted
    string is what lets the bound be applied before any string is built — the
    overflow is counted from these and thrown away (S8)."""

    kind: Literal["ref", "pin", "net"]
    subject: str
    detail: str
    #: Ingested values for `detail`'s `{}` slots, and the pin for a `pin` subject.
    values: tuple[str, ...] = ()
    pin: str = ""

    def warning(self) -> str:
        """The finding as one `Netlist.warnings` line, values clipped.

        Named `warning` rather than the obvious alternative because
        `test_context.py` forbids that method name anywhere in production code
        (it guards prompt assembly's `Context`), by text search — a blunt guard,
        but one worth keeping strict rather than loosening for a name.
        """
        return f"{MISMATCH_PREFIX}{self._subject()}: {self.detail.format(*map(_clip, self.values))}"

    def _subject(self) -> str:
        if self.kind == "pin":
            return f"{_clip(self.subject)} pin {_clip(self.pin)}"
        if self.kind == "net":
            return f"net '{_clip(self.subject)}'"
        return _clip(self.subject)


def reconcile_kicad(netlist: Netlist | None, board: Netlist | None) -> Netlist:
    """Merge a parsed netlist and a parsed board per §5.2a.

    Exactly one present → returned unchanged. Both present → the netlist's
    components (layer-enriched from the board) and nets, with the two parsers'
    warnings followed by the bounded mismatch report. Neither present is a
    caller error (the connector refuses that input before parsing).
    """
    if netlist is None and board is None:
        raise ValueError("reconcile_kicad needs a netlist, a board, or both")
    if board is None:
        return netlist  # type: ignore[return-value]  # narrowed by the guard above
    if netlist is None:
        return board

    board_by_ref = _by_designator(board)
    components = tuple(_enrich(component, board_by_ref) for component in netlist.components)
    findings = chain(
        _refdes_mismatches(netlist, board),
        _field_mismatches(netlist, board_by_ref),
        _connectivity_mismatches(netlist, board),
    )
    return Netlist(
        components=components,
        nets=netlist.nets,
        warnings=(*netlist.warnings, *board.warnings, *_bounded(findings)),
    )


def mismatch_item(warning: str) -> str | None:
    """The `SyncError.item` label for a mismatch warning — the refdes (`R1`,
    `R1 pin 2`) or `net '<name>'` every finding leads with — or `None` for any
    other warning (parser notes, the trailing overflow count). Bounded like
    every error label (§7: an adversarial net name must not persist whole)."""
    if not warning.startswith(MISMATCH_PREFIX):
        return None
    subject, separator, _ = warning.removeprefix(MISMATCH_PREFIX).partition(_ITEM_SEPARATOR)
    return _label(subject) if separator else None


def normalize_net_name(name: str) -> str:
    """Comparison form of a net name: whitespace stripped and ONE leading `/`
    (KiCad 10's sheet-path prefix) removed. Never used to rename a net."""
    stripped = name.strip()
    return stripped.removeprefix(_SHEET_PATH_PREFIX)


# ---------------------------------------------------------------- components


def _by_designator(netlist: Netlist) -> dict[str, Component]:
    """First component per designator (duplicates are `build_graph`'s to report)."""
    indexed: dict[str, Component] = {}
    for component in netlist.components:
        indexed.setdefault(component.designator, component)
    return indexed


def _enrich(component: Component, board_by_ref: dict[str, Component]) -> Component:
    """A NEW component carrying the board's `layer` when the board places it."""
    placed = board_by_ref.get(component.designator)
    layer = placed.properties.get("layer") if placed is not None else None
    if not layer:
        return component
    return replace(component, properties={**component.properties, "layer": layer})


def _refdes_mismatches(netlist: Netlist, board: Netlist) -> Iterator[_Finding]:
    netlist_refs = {c.designator for c in netlist.components}
    board_refs = {c.designator for c in board.components}
    for component in _unique(board.components):
        if component.designator not in netlist_refs:
            yield _Finding("ref", component.designator, "placed on board but not in netlist")
    for component in _unique(netlist.components):
        if component.designator not in board_refs:
            yield _Finding("ref", component.designator, "in netlist but not placed on board")


def _unique(components: tuple[Component, ...]) -> list[Component]:
    return list(_by_designator(Netlist(components=components)).values())


def _field_mismatches(netlist: Netlist, board_by_ref: dict[str, Component]) -> Iterator[_Finding]:
    for component in _unique(netlist.components):
        placed = board_by_ref.get(component.designator)
        if placed is None:
            continue
        for field_name in ("value", "footprint"):
            ours, theirs = getattr(component, field_name), getattr(placed, field_name)
            if ours is None or theirs is None or ours.strip() == theirs.strip():
                continue
            yield _Finding(
                "ref",
                component.designator,
                f"{field_name} differs (netlist '{{}}', board '{{}}')",
                (ours.strip(), theirs.strip()),
            )


# -------------------------------------------------------------- connectivity


def _pin_nets(netlist: Netlist) -> _PinNets:
    """(designator, pin) → the net's ORIGINAL name; first membership wins."""
    pins: _PinNets = {}
    for net in netlist.nets:
        for node in net.nodes:
            pins.setdefault((node.designator, node.pin), net.name)
    return pins


def _connectivity_mismatches(netlist: Netlist, board: Netlist) -> Iterator[_Finding]:
    """Board memberships the netlist lacks or contradicts, then board nets the
    netlist has no counterpart for. Netlist nodes missing from the board are not
    reported per pin — an unplaced part is already reported per refdes."""
    netlist_refs = {c.designator for c in netlist.components}
    netlist_pins = _pin_nets(netlist)
    netlist_nets = {normalize_net_name(net.name) for net in netlist.nets}
    for net in board.nets:
        for node in net.nodes:
            if node.designator not in netlist_refs:
                continue
            finding = _membership_mismatch(node.designator, node.pin, net.name, netlist_pins)
            if finding is not None:
                yield finding
    for net in board.nets:
        if normalize_net_name(net.name) not in netlist_nets:
            yield _Finding("net", net.name, "on board but not in netlist")


def _membership_mismatch(
    designator: str, pin: str, board_net: str, netlist_pins: _PinNets
) -> _Finding | None:
    netlist_net = netlist_pins.get((designator, pin))
    if netlist_net is None:
        return _Finding(
            "pin", designator, "on board net '{}' but has no net in netlist", (board_net,), pin
        )
    if normalize_net_name(netlist_net) != normalize_net_name(board_net):
        return _Finding(
            "pin",
            designator,
            "board net '{}' but netlist net '{}'",
            (board_net, netlist_net),
            pin,
        )
    return None


# -------------------------------------------------------------------- bound


def _bounded(findings: Iterable[_Finding]) -> list[str]:
    """Render the first `MAX_MISMATCH_WARNINGS` findings and COUNT the rest.

    The overflow is never built — that is the point: an adversarial board yields
    one cheap descriptor per finding, not one string (S8)."""
    kept: list[str] = []
    overflow = 0
    for finding in findings:
        if len(kept) < MAX_MISMATCH_WARNINGS:
            kept.append(finding.warning())
        else:
            overflow += 1
    if overflow:
        kept.append(f"… {overflow} more board/netlist mismatches")
    return kept
