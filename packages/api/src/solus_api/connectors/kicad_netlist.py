"""KiCad-XML-netlist parser (SOLUSDEV-100, W0-08 §5.2).

KiCad's v1 committed export is the XML netlist (`kicad-cli sch export netlist
--format kicadxml`) — the documented intermediate every other format derives
from, schema-stable across v5–v10 and parseable with the stdlib (no third-party
dep, no eval, no subprocess). Shape:

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

Output is the shared EDA netlist IR (`eda.Netlist`); the identity fields feed
the fingerprint per W0-08 §5.2 (`part_number` from an MPN custom field,
`schematic_symbol_name` from libsource, `datasheet_ref`).

Ingested text is untrusted DATA (CLAUDE.md §7): a DTD/entity declaration is
refused outright (entity-expansion guard for stdlib etree), the S-expr `.net`
format is rejected with re-export guidance (XML-only v1, design review Q2), and
structurally-unusable XML raises a stable `ConnectorError`. WITHIN valid XML the
parser is lenient — items missing their identity attributes are skipped and
counted on `Netlist.warnings`, so one bad element never fails a whole sync.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Final

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.eda import Component, Net, Netlist, Node

#: Custom-field names accepted as the manufacturer part number, compared after
#: lowercasing and stripping non-alphanumerics so "MPN", "Mfr. Part #" and
#: "Manufacturer_Part_Number" all land (delegated-judgment list, SOLUSDEV-100).
_MPN_ALIASES: Final = frozenset(
    {"mpn", "manufacturerpartnumber", "mfrpartnumber", "mfrpn", "mfrpart"}
)

#: KiCad writes "~" for an unset value/datasheet — absence, not content.
_UNSET: Final = ("", "~")

_REEXPORT_HINT: Final = (
    "kicad: the S-expression netlist is not supported in v1; re-export as XML "
    "with `kicad-cli sch export netlist --format kicadxml`."
)


def parse_kicad_netlist(text: str) -> Netlist:
    """Parse KiCad XML netlist text into the shared EDA IR.

    Raises `ConnectorError` only when the export as a whole is unusable
    (`export_format_unsupported` for the S-expr format, `export_invalid` for
    DTD/entity tricks, malformed XML, or a non-netlist root); everything
    recoverable is skipped and surfaced via `Netlist.warnings`.
    """
    root = _parse_xml(text)

    warnings: list[str] = []
    components = _components(root, warnings)
    nets = _nets(root, warnings)
    return Netlist(components=tuple(components), nets=tuple(nets), warnings=tuple(warnings))


def _parse_xml(text: str) -> ET.Element:
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped.startswith("(export"):
        raise ConnectorError("export_format_unsupported", _REEXPORT_HINT)
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
            "export_invalid",
            "kicad: not a KiCad XML netlist (expected <export> root; "
            "produce one with `kicad-cli sch export netlist --format kicadxml`)",
        )
    return root


def _components(root: ET.Element, warnings: list[str]) -> list[Component]:
    components: list[Component] = []
    skipped = 0
    for comp in _children(root, "components", "comp"):
        ref = comp.get("ref")
        if not ref:
            skipped += 1
            continue
        fields = _custom_fields(comp)
        part_number = _pop_mpn(fields)
        libsource = comp.find("libsource")
        symbol = libsource.get("part") if libsource is not None else None
        library = libsource.get("lib") if libsource is not None else None
        if library and symbol:
            fields["libsource"] = f"{library}:{symbol}"
        components.append(
            Component(
                designator=ref,
                footprint=_child_text(comp, "footprint"),
                value=_child_text(comp, "value"),
                part_number=part_number,
                schematic_symbol_name=symbol or None,
                datasheet_ref=_child_text(comp, "datasheet"),
                properties=fields,
            )
        )
    if skipped:
        warnings.append(f"skipped {skipped} component(s) without a ref designator")
    return components


def _nets(root: ET.Element, warnings: list[str]) -> list[Net]:
    nets: list[Net] = []
    skipped_nets = 0
    skipped_nodes = 0
    for net in _children(root, "nets", "net"):
        name = net.get("name")
        if not name:
            skipped_nets += 1
            continue
        nodes: list[Node] = []
        for node in net.findall("node"):
            ref, pin = node.get("ref"), node.get("pin")
            if not ref or not pin:
                skipped_nodes += 1
                continue
            nodes.append(Node(designator=ref, pin=pin))
        nets.append(Net(name=name, nodes=tuple(nodes), net_class=net.get("class")))
    if skipped_nets:
        warnings.append(f"skipped {skipped_nets} net(s) without a name")
    if skipped_nodes:
        warnings.append(f"skipped {skipped_nodes} net node(s) missing ref/pin")
    return nets


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


def _pop_mpn(fields: dict[str, str]) -> str | None:
    """Extract the manufacturer part number from the custom fields, removing it —
    supply-chain identity is the fingerprint's channel, not a display property."""
    for name in list(fields):
        normalized = "".join(ch for ch in name.lower() if ch.isalnum())
        if normalized in _MPN_ALIASES:
            return fields.pop(name)
    return None


def _child_text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return None if text in _UNSET else text
