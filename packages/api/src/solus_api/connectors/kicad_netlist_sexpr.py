"""KiCad S-expression netlist parser (SOLUSDEV-252, W0-08 §5.2).

The default `kicad-cli sch export netlist` output (`.net`, format `kicadsexpr`)
is the S-expression rendering of the same document the XML export carries:

    (export (version "E")
      (design …)                                   ← pruned unread
      (components
        (comp (ref "U1") (value "LM358") (footprint "…") (datasheet "~")
          (description "…")                        ← ignored (XML path ignores it too)
          (fields (field (name "MPN") "LM358DR"))  ← v5 style: value follows (name …)
          (property (name "MPN") (value "LM358DR")) ← v6+ style: later wins on collision
          (libsource (lib "Amplifier_Operational") (part "LM358") …)
          (sheetpath …) (tstamps …) (units …)))    ← ignored
      (libparts …) (libraries …)                   ← pruned unread
      (nets
        (net (code "1") (name "VCC") (class "Power")
          (node (ref "U1") (pin "8") (pinfunction …) (pintype …)))))

The field mapping is IDENTICAL to `kicad_netlist`'s XML path — same identity
channels (`part_number` via the shared MPN aliases, `schematic_symbol_name` from
libsource, `datasheet_ref`), same "~"/"" = unset rule, same leniency (items
missing ref/name/pin are skipped and counted on `Netlist.warnings`) and the same
scoped traversal: only the documented positions are read, so a `comp` smuggled
under `design` is invisible (§7). Parity is asserted by the test suite against
both the hand fixture and the real `kicad-cli` export of the committed sample.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from solus_api.connectors.eda import Netlist
from solus_api.connectors.kicad_formats import read_sexpr_root
from solus_api.connectors.kicad_netlist import (
    ComponentRecord,
    NetRecord,
    build_components,
    build_nets,
    is_unset,
    merge_pin_functions,
)
from solus_api.connectors.kicad_sexpr import Sexp, child, children, string_at

#: The only depth-1 sections the mapping reads; everything else (design,
#: libparts, libraries, groups, variants) is skipped without materializing.
_SECTIONS: Final = frozenset({"components", "nets"})

#: Heads this mapping never reads, at any depth — `(units (unit (pins (pin …))))`
#: alone is the bulk of a large netlist's nodes (pin membership comes from
#: `nets`), and the rest are free-text KiCad writes beside the fields we map.
#: Skipping them unread is what keeps the node guard's headroom honest: the
#: budget must bound ADVERSARIAL input, so legitimate noise must not consume it.
_UNREAD: Final = frozenset(
    {
        "units",
        "description",
        "sheetpath",
        "tstamps",
        "tstamp",
        "pintype",
    }
)


def parse_sexpr_netlist(text: str) -> Netlist:
    """Parse KiCad S-expression netlist text into the shared EDA IR.

    Raises `ConnectorError("export_invalid")` for malformed text, a tripped
    resource guard, or a root other than `(export …)`.
    """
    root = read_sexpr_root(
        text, prune=_prune, expected_head="export", kind="KiCad S-expression netlist"
    )
    warnings: list[str] = []
    components = build_components(_component_records(root), warnings)
    nets = build_nets(_net_records(root), warnings)
    return Netlist(components=tuple(components), nets=tuple(nets), warnings=tuple(warnings))


def _prune(head: str, depth: int) -> bool:
    if depth == 1:
        return head not in _SECTIONS
    return head in _UNREAD


def _component_records(root: Sexp) -> Iterator[ComponentRecord]:
    """Walk the documented S-expression positions only (§7 scoped traversal) and
    yield what was found — the family rules live in `build_components`, shared
    with the XML reader so the two mappings cannot drift."""
    for comp in children(child(root, "components"), "comp"):
        libsource = child(comp, "libsource")
        yield ComponentRecord(
            ref=_text(comp, "ref"),
            value=_value_text(comp, "value"),
            footprint=_value_text(comp, "footprint"),
            datasheet=_value_text(comp, "datasheet"),
            fields=_custom_fields(comp),
            library=_text(libsource, "lib"),
            symbol=_text(libsource, "part"),
        )


def _net_records(root: Sexp) -> Iterator[NetRecord]:
    for net in children(child(root, "nets"), "net"):
        yield NetRecord(
            name=_text(net, "name"),
            net_class=_text(net, "class"),
            nodes=tuple((_text(node, "ref"), _text(node, "pin")) for node in children(net, "node")),
            pin_functions=merge_pin_functions(
                (_text(node, "ref"), _text(node, "pin"), _text(node, "pinfunction"))
                for node in children(net, "node")
            ),
        )


def _custom_fields(comp: Sexp) -> dict[str, str]:
    """Merge both custom-field encodings: v5 `(fields (field (name N) "V"))` and
    v6+ comp-direct `(property (name N) (value V))` (later wins on a collision).
    Empty values are absence, exactly as on the XML path."""
    fields: dict[str, str] = {}
    for field in children(child(comp, "fields"), "field"):
        name, value = _text(field, "name"), _field_value(field).strip()
        if name and value:
            fields[name] = value
    for prop in children(comp, "property"):
        name, value = _text(prop, "name"), (_text(prop, "value") or "").strip()
        if name and value:
            fields[name] = value
    return fields


def _field_value(field: tuple[Sexp, ...]) -> str:
    """v5-style field value: the first string item after the `(name …)` sublist
    (`(field (name "MPN") "LM358DR")`); absent for an empty field."""
    return next((item for item in field[1:] if isinstance(item, str)), "")


def _text(node: Sexp | None, head: str) -> str | None:
    """The string argument of *node*'s direct child `(head "…")`, or None."""
    return string_at(child(node, head), 1)


def _value_text(node: Sexp, head: str) -> str | None:
    """Like `_text`, stripped, with KiCad's ""/"~" placeholders read as absence."""
    raw = _text(node, head)
    if raw is None:
        return None
    stripped = raw.strip()
    return None if is_unset(stripped) else stripped
