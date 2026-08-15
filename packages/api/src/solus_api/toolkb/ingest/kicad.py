"""SOLUS-TU-02 — KiCad documentation-ingestion (ladder step 2).

Source: KiCad's own ``TOOL_ACTION`` definitions (``eeschema/tools/
sch_actions.cpp`` et al.). This is the authoritative, machine-precise,
vendor-pure catalog of every KiCad command — name, friendly label, tooltip,
default hotkey — and it is version-scoped by the git tag it is read at (per the
TU-01 matrix, "the cleanest seed of the six").

What this source DOES carry: command existence, meaning, and hotkey. What it
does NOT carry: where the control sits on screen. So the classifier is
deliberately conservative — it derives a surface only from the two signals the
source actually provides (an ``AF_ACTIVATE`` flag ⇒ an interactive toolbar
tool; a default hotkey ⇒ keyboard-invocable) and an effect only from a verb it
recognizes — and SKIPS anything else rather than guess a wrong pointer. A
confident wrong entry propagates to every tenant; an honest gap does not. The
skipped commands are reported for the TU-01 menu-structure / TU-03 visual
ladder steps.

Every ingested entry rides the TU-06 guard's docs path (published,
provenance=vendor_docs, version-scoped) — nothing here writes the store
directly.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.contracts.tool_knowledge import ControlEffect, ToolFamily, UiSurface
from solus_api.toolkb.catalog import is_vendor_doc_url
from solus_api.toolkb.guard import IngestContext, IngestRejectedError, ingest
from solus_api.toolkb.schema import AcquisitionMethod

logger = logging.getLogger("solus.toolkb.ingest")


@dataclass(frozen=True)
class KicadAction:
    """One parsed ``TOOL_ACTION`` — the fields the KB cares about."""

    name: str
    friendly_name: str
    tooltip: str | None
    hotkey: str | None
    activates: bool


@dataclass
class IngestSummary:
    parsed: int = 0
    ingested: int = 0
    skipped: int = 0
    rejected: int = 0
    skipped_names: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- parse
# Each definition is `TOOL_ACTION <CLASS>::<var>( TOOL_ACTION_ARGS() <chain> );`.
_BLOCK_RE: Final = re.compile(r"TOOL_ACTION\s+\w+::\w+\(\s*TOOL_ACTION_ARGS\((.*?)\)\s*\);", re.S)
_NAME_RE: Final = re.compile(r'\.Name\(\s*"([^"]+)"\s*\)')
# FriendlyName/Tooltip/MenuText wrap their string in the `_( "..." )` gettext macro.
_FRIENDLY_RE: Final = re.compile(r'\.FriendlyName\(\s*_\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
_MENUTEXT_RE: Final = re.compile(r'\.MenuText\(\s*_\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
_TOOLTIP_RE: Final = re.compile(r'\.Tooltip\(\s*_\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
# A single printable-char default hotkey, optionally with modifiers. Named keys
# (WXK_*) and computed expressions are left as None — an honest omission.
_HOTKEY_RE: Final = re.compile(r"\.DefaultHotkey\(\s*((?:MD_\w+\s*\+\s*)*)'(\\?.)'\s*\)")


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace("\\\\", "\\").strip()


def parse_tool_actions(source: str) -> list[KicadAction]:
    """Parse every ``TOOL_ACTION`` in a KiCad tool-actions source file."""
    actions: list[KicadAction] = []
    for match in _BLOCK_RE.finditer(source):
        body = match.group(1)
        name_m = _NAME_RE.search(body)
        friendly_m = _FRIENDLY_RE.search(body) or _MENUTEXT_RE.search(body)
        if name_m is None or friendly_m is None:
            continue  # not a user-facing command (no name or no label)
        tooltip_m = _TOOLTIP_RE.search(body)
        hotkey_m = _HOTKEY_RE.search(body)
        hotkey = None
        if hotkey_m is not None:
            mods = "".join(
                m.replace("MD_", "").title() + "+"
                for m in re.findall(r"MD_(\w+)", hotkey_m.group(1))
            )
            hotkey = mods + _unescape(hotkey_m.group(2)).upper()
        actions.append(
            KicadAction(
                name=name_m.group(1),
                friendly_name=_unescape(friendly_m.group(1)),
                tooltip=_unescape(tooltip_m.group(1)) if tooltip_m else None,
                hotkey=hotkey,
                activates=".Flags( AF_ACTIVATE )" in body,
            )
        )
    return actions


# ---------------------------------------------------------------- control_id
_CAMEL_1: Final = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_2: Final = re.compile(r"([A-Z]+)([A-Z][a-z])")


def _snake(segment: str) -> str:
    return _CAMEL_2.sub(r"\1_\2", _CAMEL_1.sub(r"\1_\2", segment)).lower()


def control_id_for(name: str) -> str:
    """``eeschema.InspectionTool.runERC`` → ``kicad.eeschema.inspection_tool.run_erc``."""
    return "kicad." + ".".join(_snake(part) for part in name.split("."))


# ------------------------------------------------------------------ classify
#: FriendlyName leading verb → effect. Conservative: an unlisted verb ⇒ skip.
_EFFECT_BY_VERB: Final[dict[str, ControlEffect]] = {
    "add": ControlEffect.CREATE_FEATURE,
    "place": ControlEffect.CREATE_FEATURE,
    "draw": ControlEffect.CREATE_FEATURE,
    "create": ControlEffect.CREATE_FEATURE,
    "new": ControlEffect.CREATE_FEATURE,
    "insert": ControlEffect.CREATE_FEATURE,
    "delete": ControlEffect.DELETE_FEATURE,
    "remove": ControlEffect.DELETE_FEATURE,
    "edit": ControlEffect.MODIFY_FEATURE,
    "move": ControlEffect.MODIFY_FEATURE,
    "rotate": ControlEffect.MODIFY_FEATURE,
    "mirror": ControlEffect.MODIFY_FEATURE,
    "flip": ControlEffect.MODIFY_FEATURE,
    "drag": ControlEffect.MODIFY_FEATURE,
    "align": ControlEffect.MODIFY_FEATURE,
    "duplicate": ControlEffect.MODIFY_FEATURE,
    "copy": ControlEffect.MODIFY_FEATURE,
    "cut": ControlEffect.MODIFY_FEATURE,
    "paste": ControlEffect.MODIFY_FEATURE,
    "fill": ControlEffect.CREATE_FEATURE,
    "repeat": ControlEffect.CREATE_FEATURE,
    "update": ControlEffect.MODIFY_FEATURE,
    "assign": ControlEffect.MODIFY_FEATURE,
    "annotate": ControlEffect.MODIFY_FEATURE,
    "swap": ControlEffect.MODIFY_FEATURE,
    "replace": ControlEffect.MODIFY_FEATURE,
    "unfill": ControlEffect.DELETE_FEATURE,
    "select": ControlEffect.SELECT,
    "deselect": ControlEffect.SELECT,
    "zoom": ControlEffect.NAVIGATE,
    "pan": ControlEffect.NAVIGATE,
    "scroll": ControlEffect.NAVIGATE,
    "center": ControlEffect.NAVIGATE,
    "fit": ControlEffect.NAVIGATE,
    "find": ControlEffect.NAVIGATE,
    "enter": ControlEffect.NAVIGATE,
    "leave": ControlEffect.NAVIGATE,
    "measure": ControlEffect.MEASURE,
    "show": ControlEffect.TOGGLE_VISIBILITY,
    "hide": ControlEffect.TOGGLE_VISIBILITY,
    "toggle": ControlEffect.TOGGLE_VISIBILITY,
    "highlight": ControlEffect.TOGGLE_VISIBILITY,
    "display": ControlEffect.TOGGLE_VISIBILITY,
    "import": ControlEffect.IMPORT,
    "export": ControlEffect.EXPORT,
    "print": ControlEffect.EXPORT,
    "plot": ControlEffect.EXPORT,
    "generate": ControlEffect.EXPORT,
    "undo": ControlEffect.UNDO,
    "redo": ControlEffect.UNDO,
    # dialog-openers (paired with a dialog surface, below)
    "preferences": ControlEffect.SETTINGS,
    "properties": ControlEffect.SETTINGS,
    "settings": ControlEffect.SETTINGS,
    "configure": ControlEffect.SETTINGS,
}


def _opens_dialog(action: KicadAction) -> bool:
    """KiCad's own signals that a command opens a dialog: the GUI '...' menu
    convention, or a tooltip that literally says it shows a window/dialog."""
    if action.friendly_name.rstrip().endswith("..."):
        return True
    tip = (action.tooltip or "").lower()
    # "window"/"dialog" only — "editor" catches "on the editor canvas" (a view,
    # not a dialog), so it is deliberately excluded.
    return "window" in tip or "dialog" in tip


def _surface_of(action: KicadAction) -> UiSurface | None:
    if action.activates:
        return UiSurface.TOOLBAR  # AF_ACTIVATE = an interactive placement tool
    if _opens_dialog(action):
        return UiSurface.DIALOG  # vendor's own '...'/'show ... window' signal
    if action.hotkey is not None:
        return UiSurface.KEYBOARD  # bound to a key — a fact, not a guess
    return None  # no surface signal in this source


def _effect_of(action: KicadAction) -> ControlEffect | None:
    words = re.split(r"[\s.]+", action.friendly_name.strip().lower())
    for word in words:  # first recognized verb anywhere in the label
        effect = _EFFECT_BY_VERB.get(word)
        if effect is not None:
            return effect
    return None


def classify(action: KicadAction) -> tuple[UiSurface, ControlEffect] | None:
    """(surface, effect) if BOTH are confidently derivable, else None (skip).

    Precision over recall: an unknown surface or an unrecognized verb ⇒ skip,
    never a guessed pointer. The skipped commands feed the TU-01 menu-structure
    / TU-03 visual ladder steps.
    """
    surface = _surface_of(action)
    if surface is None:
        return None
    # A dialog-opener with no action verb is still a settings-class command.
    effect = _effect_of(action)
    if effect is None and surface is UiSurface.DIALOG:
        effect = ControlEffect.SETTINGS
    if effect is None:
        return None
    return surface, effect


# ------------------------------------------------------------------- ingest
def _submission(
    action: KicadAction, surface: UiSurface, effect: ControlEffect, version_range: str
) -> dict[str, Any]:
    shortcut = action.hotkey if action.hotkey and re.fullmatch(r"[\w+]+", action.hotkey) else None
    return {
        "tool": "kicad",
        "version_range": version_range,
        "surface": surface.value,
        "control_id": control_id_for(action.name),
        "label": action.friendly_name,
        "effect": effect.value,
        "description": action.tooltip or action.friendly_name,
        "invocation": None if shortcut is None else {"menu_path": None, "shortcut": shortcut},
        "locator": None,
        "provenance": "vendor_docs",
    }


async def ingest_kicad_actions(
    session: AsyncSession,
    *,
    sources: Sequence[str],
    version_range: str,
    source_url: str,
) -> IngestSummary:
    """Parse KiCad tool-action sources and ingest the classifiable commands.

    ``source_url`` must be an allowlisted KiCad vendor-doc URL (the guard's docs
    path checks it). Unclassifiable commands are skipped and counted, never
    guessed at; customer-shaped content that slips into a tooltip is rejected by
    the guard's CTR-05 net and counted, never stored.
    """
    if not is_vendor_doc_url(ToolFamily.KICAD, source_url):
        # Defensive: the guard would reject it anyway, but fail loud and early.
        raise ValueError(f"source_url is not an allowlisted KiCad vendor-doc host: {source_url}")
    ctx = IngestContext(acquired_via=AcquisitionMethod.DOCS, doc_url=source_url)
    summary = IngestSummary()
    for source in sources:
        for action in parse_tool_actions(source):
            summary.parsed += 1
            classified = classify(action)
            if classified is None:
                summary.skipped += 1
                summary.skipped_names.append(action.name)
                continue
            surface, effect = classified
            try:
                await ingest(
                    session,
                    entry=_submission(action, surface, effect, version_range),
                    ctx=ctx,
                )
                summary.ingested += 1
            except IngestRejectedError:
                summary.rejected += 1  # reason is logged by the guard; content never is
    logger.info(
        "kicad ingest: parsed=%d ingested=%d skipped=%d rejected=%d (%s)",
        summary.parsed,
        summary.ingested,
        summary.skipped,
        summary.rejected,
        source_url,
    )
    return summary
