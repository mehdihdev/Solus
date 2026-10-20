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

from solus_api.bridge.command_previews import (
    capture_rows,
    command_rows,
    existing_profiles,
    legacy_rows,
    parse_plan,
)
from solus_api.bridge.process_input_preview import INPUT_TOOL, STATUS_TOOL, input_rows

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


CODE_PLAN_TOOL: Final = "code.plan"
#: §9 item 6: the capture card says whether it replaces an existing profile.
PROFILE_LIST_TOOL: Final = "code.profile_list"
CODE_ACTIONS: Final = ("create_environment", "install", "run", "test")
#: SOLUSDEV-317 executing tools whose card rows come from `bridge/command_previews.py`.
COMMAND_ACTIONS: Final = ("exec", "process_start", "profile_capture")


async def _read(read: BridgeReader, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return await read(tool, args)
    except Exception:  # noqa: BLE001 — the caller refuses on a missing answer
        logger.warning("code preview read failed for %s", tool)
        return None


def _code_action(action: str) -> Callable[[BridgeReader], PreviewBuilder]:
    """SOLUSDEV-250: the approval card shows the EXACT argv the `code` server will
    run — read back from the server's own `plan` (one source of truth), never
    re-assembled cloud-side. A declined plan refuses with its reason
    (`PreviewRefusal`, SOLUSDEV-317) instead of parking argument rows."""

    def factory(read: BridgeReader) -> PreviewBuilder:
        async def build(args: dict[str, Any]) -> list[dict[str, Any]]:
            plan = await _read(read, CODE_PLAN_TOOL, {"action": action, "args": dict(args)})
            if action == "profile_capture":
                parse_plan(plan)  # a refused plan's reason wins over the listing read
                listing = await _read(read, PROFILE_LIST_TOOL, {})
                return capture_rows(plan, args, existing_profiles(listing))
            if action in ("exec", "process_start"):
                return command_rows(plan, args, process=action == "process_start")
            return code_plan_rows(plan)

        return build

    return factory


def code_plan_rows(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One lossless, bounded presentation; a plan that cannot fit cannot execute."""
    return legacy_rows(plan)


def _process_input(read: BridgeReader) -> PreviewBuilder:
    """§11.2: the card reads the process's live status (prompt and sequence)."""

    async def build(args: dict[str, Any]) -> list[dict[str, Any]]:
        process_id = args.get("process_id")
        status = (
            await _read(read, STATUS_TOOL, {"process_id": process_id})
            if isinstance(process_id, str)
            else None
        )
        return input_rows(status, args)

    return build


PREVIEWABLE_TOOLS: Final[dict[str, Callable[[BridgeReader], PreviewBuilder]]] = {
    "kicad.set_symbol_property": _kicad_symbol_property,
    INPUT_TOOL: _process_input,
    **{f"code.{action}": _code_action(action) for action in CODE_ACTIONS + COMMAND_ACTIONS},
}


def preview_builder(tool_name: str, read: BridgeReader) -> PreviewBuilder | None:
    """The preview for a companion write tool, or None (argument rows apply)."""
    factory = PREVIEWABLE_TOOLS.get(tool_name)
    return None if factory is None else factory(read)
