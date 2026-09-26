"""KiCad netlist parser — dispatcher + XML path (SOLUSDEV-100/252, W0-08 §5.2).

`parse_kicad_netlist` sniffs the CONTENT (never a file extension — there is none
at this layer) and routes:

* XML netlist (`kicad-cli sch export netlist --format kicadxml`) — parsed here
  with the stdlib. Shape:

      <export version="E">
        <components>
          <comp ref="U1">
            <value>LM358</value> <footprint>…</footprint> <datasheet>…</datasheet>
            <fields><field name="MPN">LM358DR</field></fields>   (v5 style)
            <property name="MPN" value="LM358DR"/>               (v6+ style)
            <libsource lib="Amplifier_Operational" part="LM358"/>
          </comp>
        </components>
        <nets>
          <net code="1" name="VCC" class="Power">
            <node ref="U1" pin="8"/> …
          </net>
        </nets>
      </export>

* the default S-expression `.net` (`(export …)` root) — a first-class equal,
  parsed by `kicad_netlist_sexpr` with the IDENTICAL field mapping.
* anything else — a raw `.kicad_sch`/`.kicad_pro`, a board handed in as the
  netlist, unrecognized text — is refused with `export_format_unsupported` and
  guidance naming the accepted routes (`kicad_formats`).

Output is the shared EDA netlist IR (`eda.Netlist`); the identity fields feed
the fingerprint per W0-08 §5.2 (`part_number` from an MPN custom field,
`schematic_symbol_name` from libsource, `datasheet_ref`). The field helpers
(`MPN_ALIASES`, `is_unset`, `pop_mpn`) are shared with the S-expression netlist
and board parsers so the three cannot drift.

Ingested text is untrusted DATA (CLAUDE.md §7): a DTD/entity declaration is
refused outright (entity-expansion guard for stdlib etree) and
structurally-unusable XML raises a stable `ConnectorError`. WITHIN valid XML the
parser is lenient — items missing their identity attributes are skipped and
counted on `Netlist.warnings`, so one bad element never fails a whole sync.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Final

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.eda import Component, Net, Netlist, Node
from solus_api.connectors.kicad_formats import detect_kicad_format, refuse_unsupported

#: Custom-field names accepted as the manufacturer part number, compared after
#: lowercasing and stripping non-alphanumerics so "MPN", "Mfr. Part #" and
#: "Manufacturer_Part_Number" all land (delegated-judgment list, SOLUSDEV-100).
MPN_ALIASES: Final = frozenset(
    {"mpn", "manufacturerpartnumber", "mfrpartnumber", "mfrpn", "mfrpart"}
)

#: KiCad writes "~" for an unset value/datasheet — absence, not content.
_UNSET: Final = ("", "~")


def parse_kicad_netlist(text: str) -> Netlist:
    """Parse KiCad netlist text (XML or S-expression) into the shared EDA IR.

    Raises `ConnectorError` only when the export as a whole is unusable
    (`export_format_unsupported` for a non-netlist file, `export_invalid` for
    DTD/entity tricks, malformed input, or a non-netlist root); everything
    recoverable is skipped and surfaced via `Netlist.warnings`.
    """
    fmt = detect_kicad_format(text)
    if fmt == "xml_netlist":
        return _parse_xml_netlist(text)
    if fmt == "sexpr_netlist":
        # Imported here, not at module top: kicad_netlist_sexpr reuses this
        # module's field helpers, so a top-level import would be circular.
        from solus_api.connectors.kicad_netlist_sexpr import parse_sexpr_netlist

        return parse_sexpr_netlist(text)
    raise refuse_unsupported(fmt, expected="netlist")


def is_unset(value: str | None) -> bool:
    """True when *value* is absent or a KiCad placeholder ("" / "~")."""
    return value is None or value.strip() in _UNSET


def pop_mpn(fields: dict[str, str]) -> str | None:
    """Extract the manufacturer part number from the custom fields, removing it —
    supply-chain identity is the fingerprint's channel, not a display property."""
    for name in list(fields):
        normalized = "".join(ch for ch in name.lower() if ch.isalnum())
        if normalized in MPN_ALIASES:
            return fields.pop(name)
    return None


# -------------------------------------------------- shared record builders


@dataclass(frozen=True)
class ComponentRecord:
    """One `comp` as a format-specific reader found it, before the FAMILY rules
    (skip counting, MPN popping, libsource composition) are applied."""

    ref: str | None
    value: str | None
    footprint: str | None
    datasheet: str | None
    fields: Mapping[str, str]
    library: str | None = None
    symbol: str | None = None


@dataclass(frozen=True)
class NetRecord:
    """One `net` as a format-specific reader found it. `nodes` are raw
    `(ref, pin)` pairs — either half may be missing."""

    name: str | None
    net_class: str | None
    nodes: tuple[tuple[str | None, str | None], ...]
    pin_functions: Mapping[tuple[str | None, str | None], str | None] = dataclass_field(
        default_factory=dict
    )


def merge_pin_functions(
    declarations: Iterable[tuple[str | None, str | None, str | None]],
) -> dict[tuple[str | None, str | None], str | None]:
    """Duplicate declarations must agree; an ambiguous pin never regains a name."""
    result: dict[tuple[str | None, str | None], str | None] = {}
    for ref, pin, function in declarations:
        key = (ref, pin)
        if key not in result:
            result[key] = function
        elif result[key] != function:
            result[key] = None
    return result


def build_components(records: Iterable[ComponentRecord], warnings: list[str]) -> list[Component]:
    """Apply the §5.2 component rules to whatever a reader found.

    Shared by the XML and S-expression readers so the identity handling — MPN
    popped into `part_number`, libsource composed into `properties`, a ref-less
    component skipped and COUNTED — cannot drift between the two formats.
    """
    components: list[Component] = []
    skipped = 0
    for record in records:
        if not record.ref:
            skipped += 1
            continue
        fields = dict(record.fields)  # never mutate the reader's mapping
        part_number = pop_mpn(fields)
        if record.library and record.symbol:
            fields["libsource"] = f"{record.library}:{record.symbol}"
        components.append(
            Component(
                designator=record.ref,
                footprint=record.footprint,
                value=record.value,
                part_number=part_number,
                schematic_symbol_name=record.symbol or None,
                datasheet_ref=record.datasheet,
                properties=fields,
            )
        )
    if skipped:
        warnings.append(f"skipped {skipped} component(s) without a ref designator")
    return components


def build_nets(records: Iterable[NetRecord], warnings: list[str]) -> list[Net]:
    """Apply the §5.2 net rules: a nameless net and a node missing either half
    are skipped and counted, so a partial parse stays visible (never silent)."""
    nets: list[Net] = []
    skipped_nets = 0
    skipped_nodes = 0
    for record in records:
        if not record.name:
            skipped_nets += 1
            continue
        nodes: list[Node] = []
        for ref, pin in record.nodes:
            if not ref or not pin:
                skipped_nodes += 1
                continue
            function = record.pin_functions.get((ref, pin))
            nodes.append(Node(designator=ref, pin=pin, pin_function=function))
        nets.append(Net(name=record.name, nodes=tuple(nodes), net_class=record.net_class))
    if skipped_nets:
        warnings.append(f"skipped {skipped_nets} net(s) without a name")
    if skipped_nodes:
        warnings.append(f"skipped {skipped_nodes} net node(s) missing ref/pin")
    return nets


# ------------------------------------------------------------------ XML path


def _parse_xml_netlist(text: str) -> Netlist:
    root = _parse_xml(text)
    warnings: list[str] = []
    components = build_components(_component_records(root), warnings)
    nets = build_nets(_net_records(root), warnings)
    return Netlist(components=tuple(components), nets=tuple(nets), warnings=tuple(warnings))


def _parse_xml(text: str) -> ET.Element:
    # stdlib etree still expands internal entities — refuse any DTD outright
    # (billion-laughs guard); a KiCad netlist never declares one.
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ConnectorError("export_invalid", "kicad: XML with a DTD/entity declaration refused")
    try:
        root = ET.fromstring(text)  # noqa: S314 — DTDs refused above; stdlib per W0-08 §8
    except ET.ParseError as exc:
        raise ConnectorError("export_invalid", f"kicad: not parseable as XML ({exc})") from exc
    if root.tag != "export":
        raise ConnectorError(
            "export_invalid", "kicad: not a KiCad XML netlist (expected <export> root)"
        )
    return root


def _component_records(root: ET.Element) -> Iterator[ComponentRecord]:
    """Walk the documented XML positions only (§7 scoped traversal) and yield
    what was found; the family rules live in `build_components`."""
    for comp in _children(root, "components", "comp"):
        libsource = comp.find("libsource")
        yield ComponentRecord(
            ref=comp.get("ref"),
            value=_child_text(comp, "value"),
            footprint=_child_text(comp, "footprint"),
            datasheet=_child_text(comp, "datasheet"),
            fields=_custom_fields(comp),
            library=libsource.get("lib") if libsource is not None else None,
            symbol=libsource.get("part") if libsource is not None else None,
        )


def _net_records(root: ET.Element) -> Iterator[NetRecord]:
    for net in _children(root, "nets", "net"):
        yield NetRecord(
            name=net.get("name"),
            net_class=net.get("class"),
            nodes=tuple((node.get("ref"), node.get("pin")) for node in net.findall("node")),
            pin_functions=merge_pin_functions(
                (node.get("ref"), node.get("pin"), node.get("pinfunction"))
                for node in net.findall("node")
            ),
        )


def _custom_fields(comp: ET.Element) -> dict[str, str]:
    """Merge both custom-field encodings: v5 `<fields><field name>text</field>`
    and v6+ comp-direct `<property name value>` (later wins on a name collision).

    Traversal is scoped to those documented positions — never a whole-subtree
    walk, so adversarial content nested elsewhere (§7) can't be smuggled in.
    """
    fields: dict[str, str] = {}
    for field in _children(comp, "fields", "field"):
        name, value = field.get("name"), (field.text or "").strip()
        if name and value:
            fields[name] = value
    for prop in comp.findall("property"):
        name, value = prop.get("name"), (prop.get("value") or "").strip()
        if name and value:
            fields[name] = value
    return fields


def _children(parent: ET.Element, section: str, tag: str) -> list[ET.Element]:
    """Direct `tag` children of `parent`'s direct `section` child ([] if absent)."""
    container = parent.find(section)
    return [] if container is None else container.findall(tag)


def _child_text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return None if is_unset(text) else text
