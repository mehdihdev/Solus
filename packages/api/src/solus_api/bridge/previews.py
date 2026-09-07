"""Previews for companion WRITE tools (SOLUSDEV-251 / INTEGRATIONS I4).

The approval card renders `{label, before, after}` rows; a `BridgeTool` had no
`preview`, so a KiCad write degraded to argument rows — a request, not a diff.
A before value can only come from the machine, so a preview here is one READ
dispatched over the same bridge (`kicad.extract_project_netlist` for the
schematic's project) before the write is parked. The reader is injected: it
answers `None` for anything short of a well-formed value (offline, refused,
timed out), and the preview then shows `before: None` — an honest "unknown",
never a guess. Pure otherwise; nothing here raises.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

logger = logging.getLogger("solus.bridge.previews")

#: `(tool, args) -> value | None`: one read through the bridge, declining as None.
BridgeReader = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]
PreviewBuilder = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]

KICAD_NETLIST_TOOL: Final = "kicad.extract_project_netlist"
_VALUE_CAP: Final = 500
_SCH_SUFFIX: Final = ".kicad_sch"
_PRO_SUFFIX: Final = ".kicad_pro"


def kicad_project_path(schematic_path: object) -> str | None:
    """The `.kicad_pro` beside a `.kicad_sch` (the fork's netlist tool wants the
    project); None when the argument is not a workspace-relative schematic path.
    The fork confines every path itself; refusing `..`/absolute here means the
    cloud never even dispatches a read for a model-chosen escape (review M2)."""
    if not isinstance(schematic_path, str) or not schematic_path.lower().endswith(_SCH_SUFFIX):
        return None
    if schematic_path.startswith(("/", "\\")) or ".." in schematic_path.split("/"):
        return None
    if len(schematic_path) > 1 and schematic_path[1] == ":":
        return None
    return schematic_path[: -len(_SCH_SUFFIX)] + _PRO_SUFFIX


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)[:_VALUE_CAP]


def _components(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    components = result.get("components")
    if not isinstance(components, dict):
        nested = result.get("netlist")
        components = nested.get("components") if isinstance(nested, dict) else None
    return components if isinstance(components, dict) else {}


def _current_property(result: dict[str, Any] | None, reference: str, prop: str) -> str | None:
    component = _components(result).get(reference)
    if not isinstance(component, dict):
        return None
    key = prop.lower()
    if key in ("value", "footprint"):
        return _text(component.get(key))
    properties = component.get("properties")
    if not isinstance(properties, dict):
        return None
    return _text(properties.get(prop))


def _kicad_symbol_property(read: BridgeReader) -> PreviewBuilder:
    async def build(args: dict[str, Any]) -> list[dict[str, Any]]:
        schematic = args.get("schematic_path")
        reference = args.get("reference")
        prop = args.get("property")
        before: str | None = None
        project = kicad_project_path(schematic)
        if project and isinstance(reference, str) and isinstance(prop, str):
            logger.info("preview read %s for kicad.set_symbol_property", KICAD_NETLIST_TOOL)
            try:
                result = await read(KICAD_NETLIST_TOOL, {"project_path": project})
            except Exception:  # noqa: BLE001 — a preview never blocks the park
                logger.warning("kicad preview read failed; showing no before value")
                result = None
            before = _current_property(result, reference, prop)
        label = f"{_text(reference) or '?'} · {_text(prop) or '?'}"
        return [
            {"label": label, "before": before, "after": _text(args.get("value"))},
            {"label": "schematic", "before": None, "after": _text(schematic)},
        ]

    return build


PREVIEWABLE_TOOLS: Final[dict[str, Callable[[BridgeReader], PreviewBuilder]]] = {
    "kicad.set_symbol_property": _kicad_symbol_property,
}


def preview_builder(tool_name: str, read: BridgeReader) -> PreviewBuilder | None:
    """The preview for a companion write tool, or None (argument rows apply)."""
    factory = PREVIEWABLE_TOOLS.get(tool_name)
    return None if factory is None else factory(read)
