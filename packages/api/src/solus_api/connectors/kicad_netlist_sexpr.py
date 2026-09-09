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

from typing import Final

from solus_api.connectors.eda import Component, Net, Netlist, Node
from solus_api.connectors.kicad_formats import read_sexpr_root
from solus_api.connectors.kicad_netlist import is_unset, pop_mpn
from solus_api.connectors.kicad_sexpr import Sexp, child, children, string_at

#: The only depth-1 sections the mapping reads; everything else (design,
#: libparts, libraries, groups, variants) is skipped without materializing.
_SECTIONS: Final = frozenset({"components", "nets"})
#: Per-component `(units (unit (pins (pin …))))` — the bulk of a large netlist's
#: nodes, never read (pin membership comes from `nets`); skipped unread too.
_COMPONENT_NOISE: Final = frozenset({"units"})


def parse_sexpr_netlist(text: str) -> Netlist:
    """Parse KiCad S-expression netlist text into the shared EDA IR.

    Raises `ConnectorError("export_invalid")` for malformed text, a tripped
    resource guard, or a root other than `(export …)`.
    """
    root = read_sexpr_root(
        text, prune=_prune, expected_head="export", kind="KiCad S-expression netlist"
    )
    warnings: list[str] = []
    components = _components(root, warnings)
    nets = _nets(root, warnings)
    return Netlist(components=tuple(components), nets=tuple(nets), warnings=tuple(warnings))


def _prune(head: str, depth: int) -> bool:
    if depth == 1:
        return head not in _SECTIONS
    return depth == 3 and head in _COMPONENT_NOISE


def _components(root: Sexp, warnings: list[str]) -> list[Component]:
    components: list[Component] = []
    skipped = 0
    for comp in children(child(root, "components"), "comp"):
        ref = _text(comp, "ref")
        if not ref:
            skipped += 1
            continue
        fields = _custom_fields(comp)
        part_number = pop_mpn(fields)
        libsource = child(comp, "libsource")
        symbol, library = _text(libsource, "part"), _text(libsource, "lib")
        if library and symbol:
            fields["libsource"] = f"{library}:{symbol}"
        components.append(
            Component(
                designator=ref,
                footprint=_value_text(comp, "footprint"),
                value=_value_text(comp, "value"),
                part_number=part_number,
                schematic_symbol_name=symbol or None,
                datasheet_ref=_value_text(comp, "datasheet"),
                properties=fields,
            )
        )
    if skipped:
        warnings.append(f"skipped {skipped} component(s) without a ref designator")
    return components


def _nets(root: Sexp, warnings: list[str]) -> list[Net]:
    nets: list[Net] = []
    skipped_nets = 0
    skipped_nodes = 0
    for net in children(child(root, "nets"), "net"):
        name = _text(net, "name")
        if not name:
            skipped_nets += 1
            continue
        nodes: list[Node] = []
        for node in children(net, "node"):
            ref, pin = _text(node, "ref"), _text(node, "pin")
            if not ref or not pin:
                skipped_nodes += 1
                continue
            nodes.append(Node(designator=ref, pin=pin))
        nets.append(Net(name=name, nodes=tuple(nodes), net_class=_text(net, "class")))
    if skipped_nets:
        warnings.append(f"skipped {skipped_nets} net(s) without a name")
    if skipped_nodes:
        warnings.append(f"skipped {skipped_nodes} net node(s) missing ref/pin")
    return nets


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
