"""KiCad `.kicad_pcb` board parser (SOLUSDEV-252, W0-08 §5.2a).

A board file is a design file, not an export, but it carries what the graph
needs: placed footprints with their symbol fields, and pad→net memberships.

    (kicad_pcb (version 20241229) (generator "pcbnew")
      (net 0 "") (net 1 "VCC") …                       ← net header (code → name)
      (footprint "Package_SO:SOIC-8_…"                  ← lib id
        (layer "F.Cu")
        (property "Reference" "U1" (at …) (effects …))  ← KiCad 8+ fields
        (property "Value" "LM358" …) (property "MPN" "LM358DR" …)
        (fp_text reference "U1" …)                      ← KiCad ≤7 (property wins)
        (pad "8" smd roundrect (at …) (net 1 "VCC") …)  ← pad number = pin
        (fp_line …) (model …))                          ← pruned unread
      (segment …) (via …) (zone …) (gr_line …))         ← pruned unread

Mapping (§5.2a): a footprint carrying a Reference → `Component`; the MPN alias
property → `part_number`; `Datasheet` → `datasheet_ref`; `layer`, `Description`
and the remaining custom properties (minus KiCad-internal `ki_*` ones) →
`properties`. **`schematic_symbol_name` is None by design** — a board carries no
libsource, and the hint is never guessed. Pad `(net <code> "<name>")` → `Node`
on that net; code 0 / an empty name mean unconnected. Board-only footprints
(mounting holes, fiducials) remain components with no connectivity. Footprints
without a reference (or with the `REF**` placeholder) are skipped and counted.

Pruning keeps only the documented positions (§7 scoped traversal): depth-1 `net`
and `footprint`; inside a footprint `layer`/`property`/`fp_text`/`pad`; inside a
pad only `net`. Copper, zones, graphics and 3D models are never materialized.
"""

from __future__ import annotations

from typing import Any, Final

from solus_api.connectors.eda import Component, Net, Netlist, Node
from solus_api.connectors.kicad_formats import (
    detect_kicad_format,
    read_sexpr_root,
    refuse_unsupported,
)
from solus_api.connectors.kicad_netlist import is_unset, pop_mpn
from solus_api.connectors.kicad_sexpr import Sexp, child, children, string_at

_TOP_LEVEL: Final = frozenset({"net", "footprint"})
_FOOTPRINT_LEVEL: Final = frozenset({"layer", "property", "fp_text", "pad"})
_PAD_LEVEL: Final = frozenset({"net"})

_REFERENCE: Final = "Reference"
_VALUE: Final = "Value"
_FOOTPRINT: Final = "Footprint"
_DATASHEET: Final = "Datasheet"
_DESCRIPTION: Final = "Description"
_WELL_KNOWN: Final = frozenset({_REFERENCE, _VALUE, _FOOTPRINT, _DATASHEET, _DESCRIPTION})
#: KiCad's unplaced-reference placeholder — a footprint never annotated.
_PLACEHOLDER_REFERENCE: Final = "REF**"
#: KiCad-internal symbol metadata (ki_keywords, ki_fp_filters, …): tool noise.
_INTERNAL_PREFIX: Final = "ki_"
#: Net code 0 is KiCad's "no net".
_UNCONNECTED_CODE: Final = "0"

_Memberships = dict[str, list[Node]]


def parse_kicad_pcb(text: str) -> Netlist:
    """Parse KiCad board text into the shared EDA IR.

    Raises `ConnectorError("export_format_unsupported")` when the content is
    not a board (a netlist, a schematic, a project file, unrecognized text) and
    `ConnectorError("export_invalid")` for malformed text or a tripped guard.
    """
    fmt = detect_kicad_format(text)
    if fmt != "pcb":
        raise refuse_unsupported(fmt, expected="board")
    root = read_sexpr_root(text, prune=_prune, expected_head="kicad_pcb", kind="KiCad board")
    warnings: list[str] = []
    net_names = _net_header(root)
    components, memberships = _footprints(root, net_names, warnings)
    return Netlist(
        components=tuple(components),
        nets=tuple(_nets(net_names, memberships)),
        warnings=tuple(warnings),
    )


def _prune(head: str, depth: int) -> bool:
    if depth == 0:
        return False
    if depth == 1:
        return head not in _TOP_LEVEL
    if depth == 2:
        return head not in _FOOTPRINT_LEVEL
    if depth == 3:
        return head not in _PAD_LEVEL
    return True


def _net_header(root: Sexp) -> dict[str, str]:
    """Depth-1 `(net <code> "<name>")` entries, code → name, in board order;
    the unconnected net (code 0 / empty name) is dropped."""
    names: dict[str, str] = {}
    for net in children(root, "net"):
        code, name = string_at(net, 1), string_at(net, 2)
        if code is None or code == _UNCONNECTED_CODE or not name:
            continue
        names[code] = name
    return names


def _footprints(
    root: Sexp, net_names: dict[str, str], warnings: list[str]
) -> tuple[list[Component], _Memberships]:
    components: list[Component] = []
    memberships: _Memberships = {}
    skipped = 0
    orphan_pads = 0
    for footprint in children(root, "footprint"):
        props = _properties(footprint)
        texts = _fp_texts(footprint)
        reference = props.get(_REFERENCE) or texts.get("reference")
        if not reference or reference == _PLACEHOLDER_REFERENCE:
            skipped += 1
            continue
        components.append(_component(footprint, reference, props, texts))
        orphan_pads += _collect_pads(footprint, reference, net_names, memberships)
    if skipped:
        warnings.append(f"skipped {skipped} footprint(s) without a reference designator")
    if orphan_pads:
        warnings.append(f"skipped {orphan_pads} pad(s) on a net code absent from the net header")
    return components, memberships


def _properties(footprint: Sexp) -> dict[str, str]:
    """KiCad 8+ `(property "Name" "Value" …)` direct children, name → value."""
    props: dict[str, str] = {}
    for prop in children(footprint, "property"):
        name = string_at(prop, 1)
        if name:
            props[name] = (string_at(prop, 2) or "").strip()
    return props


def _fp_texts(footprint: Sexp) -> dict[str, str]:
    """KiCad ≤7 `(fp_text reference|value "…" …)` direct children, kind → text."""
    texts: dict[str, str] = {}
    for item in children(footprint, "fp_text"):
        kind, text = string_at(item, 1), string_at(item, 2)
        if kind in ("reference", "value") and text is not None:
            texts[kind] = text.strip()
    return texts


def _component(
    footprint: Sexp, reference: str, props: dict[str, str], texts: dict[str, str]
) -> Component:
    custom = {
        name: value
        for name, value in props.items()
        if name not in _WELL_KNOWN and value and not name.startswith(_INTERNAL_PREFIX)
    }
    part_number = pop_mpn(custom)
    properties: dict[str, Any] = {}
    layer = string_at(child(footprint, "layer"), 1)
    if layer:
        properties["layer"] = layer
    description = _clean(props.get(_DESCRIPTION))
    if description:
        properties["description"] = description
    properties.update(custom)
    return Component(
        designator=reference,
        footprint=_clean(props.get(_FOOTPRINT)) or string_at(footprint, 1),
        value=_clean(props.get(_VALUE) or texts.get("value")),
        part_number=part_number,
        schematic_symbol_name=None,  # a board has no libsource (§5.2a)
        datasheet_ref=_clean(props.get(_DATASHEET)),
        properties=properties,
    )


def _collect_pads(
    footprint: Sexp, reference: str, net_names: dict[str, str], memberships: _Memberships
) -> int:
    """Append a `Node` per connected pad to its net; returns how many pads named
    a net code with no name anywhere (pad or header) and were dropped."""
    orphans = 0
    for pad in children(footprint, "pad"):
        number = string_at(pad, 1)
        net = child(pad, "net")
        if not number or net is None:
            continue  # NPTH holes have no number; netless pads have no membership
        code = string_at(net, 1)
        if code is None or code == _UNCONNECTED_CODE:
            continue
        name = string_at(net, 2) or net_names.get(code)
        if not name:
            orphans += 1
            continue
        memberships.setdefault(name, []).append(Node(designator=reference, pin=number))
    return orphans


def _nets(net_names: dict[str, str], memberships: _Memberships) -> list[Net]:
    """Nets with at least one pad, header order first, pad-only names after."""
    ordered = dict.fromkeys([*net_names.values(), *memberships])
    return [
        Net(name=name, nodes=tuple(memberships[name])) for name in ordered if name in memberships
    ]


def _clean(value: str | None) -> str | None:
    return None if value is None or is_unset(value) else value.strip()
