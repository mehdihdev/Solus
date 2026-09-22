"""Complete bounded official-XML topology for the existing schematic read tools."""

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET  # noqa: S405 - DTD/entities refused before parsing

from solus.cli_detect import detect_kicad_cli
from solus.netlist_export import _cli_export, _find_schematic, _schematic_snapshot
from solus.trimming import SupportsToolDecorator

_MAX_XML = 32 * 1024 * 1024
_MAX_RESULT = 3900  # below the unchanged 4000-character tool outcome envelope


def _text(value: str | None, limit: int = 160) -> str:
    if value is None or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_native_topology")
    return value


def _components(root: ET.Element) -> dict[str, dict[str, str]]:
    groups = root.findall("components")
    if len(groups) != 1:
        raise ValueError("invalid_native_topology")
    result: dict[str, dict[str, str]] = {}
    nodes = groups[0].findall("comp")
    if len(nodes) > 256:
        raise ValueError("topology_too_large")
    for node in nodes:
        ref = _text(node.get("ref"), 64)
        if ref in result:
            raise ValueError("invalid_native_topology")
        values = node.findall("value")
        if len(values) > 1:
            raise ValueError("invalid_native_topology")
        value = values[0].text if values else None
        result[ref] = {"value": _text(value) if value else ""}
    return result


def _nets(root: ET.Element, components: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    groups = root.findall("nets")
    if len(groups) != 1:
        raise ValueError("invalid_native_topology")
    result: dict[str, list[dict[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    nodes = groups[0].findall("net")
    if len(nodes) > 512:
        raise ValueError("topology_too_large")
    for net in nodes:
        name = _text(net.get("name"))
        if name in result:
            raise ValueError("invalid_native_topology")
        pins = []
        for node in net.findall("node"):
            ref, pin = _text(node.get("ref"), 64), _text(node.get("pin"), 32)
            if ref not in components or (ref, pin) in seen:
                raise ValueError("invalid_native_topology")
            seen.add((ref, pin))
            if len(seen) > 4096:
                raise ValueError("topology_too_large")
            pins.append({"component": ref, "pin": pin})
        if not pins:
            raise ValueError("invalid_native_topology")
        result[name] = pins
    return result


def topology(data: bytes) -> dict[str, Any]:
    """Only direct documented XML positions participate; ambiguity fails closed."""
    if len(data) > _MAX_XML:
        raise ValueError("topology_too_large")
    try:
        text = data.decode("utf-8")
        if "<!DOCTYPE" in text or "<!ENTITY" in text or "\x00" in text:
            raise ValueError("invalid_native_topology")
        root = ET.fromstring(text)  # noqa: S314 - size/UTF-8/DTD guard above
    except (UnicodeError, ET.ParseError):
        raise ValueError("invalid_native_topology") from None
    if root.tag != "export":
        raise ValueError("invalid_native_topology")
    components = _components(root)
    nets = _nets(root, components)
    result = {
        "success": True,
        "complete": True,
        "basis": "official_kicadxml",
        "component_count": len(components),
        "net_count": len(nets),
        "components": components,
        "nets": nets,
    }
    encoded = json.dumps({"ok": True, "value": result}, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.replace("<", "\\u003c")) > _MAX_RESULT:
        raise ValueError("topology_too_large: complete topology exceeds the model result limit")
    return result


def read_topology(schematic: Path) -> dict[str, Any]:
    cli = detect_kicad_cli()
    if cli is None:
        raise ValueError("authoritative_topology_unavailable: kicad-cli is unavailable")
    if schematic.suffix != ".kicad_sch":
        raise ValueError("expected_schematic_path")
    with _schematic_snapshot(schematic) as snapshot:
        data = _cli_export(cli, snapshot, "topology.xml")
    if data is None:
        raise ValueError("authoritative_topology_unavailable: kicad-cli export failed")
    return topology(data)


def register_netlist_reads(mcp: SupportsToolDecorator) -> None:
    async def extract_project_netlist(project_path: str) -> dict[str, Any]:
        """Read complete official KiCad XML component/net/pin topology for a .kicad_pro.
        Includes singleton unconnected nets. Refuses unavailable CLI or oversized topology;
        never treats a clipped export or legacy schematic regex parse as complete evidence.
        """
        project = Path(project_path)
        if project.suffix != ".kicad_pro" or not project.is_file():
            raise ValueError("expected_project_path")
        return read_topology(_find_schematic(project))

    async def analyze_schematic_connections(schematic_path: str) -> dict[str, Any]:
        """Read complete official component/net/pin memberships for a .kicad_sch.
        Net names and singleton nodes do not establish ratings or intentional no-connects.
        Refuses unavailable CLI or oversized topology rather than presenting partial analysis.
        """
        return read_topology(Path(schematic_path))

    for function in (extract_project_netlist, analyze_schematic_connections):
        mcp.tool()(function)
