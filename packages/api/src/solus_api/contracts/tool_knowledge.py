"""SOLUSDEV-220 (CTR-05) — the tool-knowledge typed boundary.

⚠ HIGHEST-RISK CONTRACT ON THE BOARD. The tool-knowledge store holds TOOL
knowledge only — "the extrude icon in Fusion v2.x is here and does this" — and
it is read by EVERY tenant. A customer's parts, dimensions, files or designs
entering it would be a cross-tenant leak of proprietary robot design, which
CLAUDE.md §7 calls the highest-severity invariant in this codebase.

So the boundary is not a rule people follow. It is the SHAPE:

1. **Closed column set.** ``extra="forbid"``. There is no ``properties``,
   ``attrs``, ``metadata``, ``payload`` or ``notes`` to put anything in.
2. **No identifier of anything customer-owned.** No project, team, entity,
   document, element or file field exists to be filled.
3. **Every categorical field is an enum.** A free-text category is a blob with
   extra steps.
4. **The prose fields are validated, not trusted.** ``_vendor_text`` caps length
   and rejects an enumerated list of mechanical shapes.

.. warning::
   **Points 1-3 are structural. Point 4 is not.** ``_vendor_text`` cannot
   classify open-world prose — a security review passed "Hero Arm Bracket Rev C"
   and "Net MOTOR_PWM_1 connects U3 pin 14 to Q2 gate" straight through it. The
   prose fields are a bounded free-text channel with a backstop, and an ingestion
   path that writes them from a per-document or per-project API must apply its
   own allowlist. See the "What this contract does not do" section of the doc.

The TypeScript twin brands its prose fields so a raw string does not compile,
and `packages/shared-types/src/tool-knowledge.illegal.ts` proves twenty illegal
constructions fail `tsc`. This module is the runtime half of the same boundary.

The store is a **schema-level and review-level** constraint, explicitly NOT a
convention. Adding an escape hatch here is a security change, not a contract
change. See `docs/contracts/tool-knowledge.md`.
"""

from __future__ import annotations

import enum
import json
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core.core_schema import ValidationInfo

#: Cap on any single piece of vendor prose. An unbounded string IS a blob field.
MAX_VENDOR_TEXT: Final = 400


class ToolFamily(enum.StrEnum):
    """Tools Solus models the UI of. Closed: a new tool is a decision, not a value."""

    FUSION = "fusion"
    ONSHAPE = "onshape"
    SOLIDWORKS = "solidworks"
    AUTOCAD = "autocad"
    KICAD = "kicad"
    ALTIUM = "altium"
    SPICE = "spice"


class UiSurface(enum.StrEnum):
    """Where in the tool's UI the control lives."""

    TOOLBAR = "toolbar"
    MENU = "menu"
    CONTEXT_MENU = "context_menu"
    PANEL = "panel"
    DIALOG = "dialog"
    KEYBOARD = "keyboard"
    STATUS_BAR = "status_bar"


class ControlEffect(enum.StrEnum):
    """What the control DOES, from a closed set.

    Categorising the effect rather than describing it freely lets the Guide
    reason about a control without reading prose — and removes one more place a
    sentence about a customer's design could live.
    """

    CREATE_FEATURE = "create_feature"
    MODIFY_FEATURE = "modify_feature"
    DELETE_FEATURE = "delete_feature"
    SELECT = "select"
    NAVIGATE = "navigate"
    MEASURE = "measure"
    TOGGLE_VISIBILITY = "toggle_visibility"
    IMPORT = "import"
    EXPORT = "export"
    UNDO = "undo"
    SETTINGS = "settings"


class Provenance(enum.StrEnum):
    """Where the knowledge came from. There is deliberately no customer option."""

    VENDOR_DOCS = "vendor_docs"
    OBSERVED_UI = "observed_ui"
    OPERATOR_AUTHORED = "operator_authored"


#: Shapes that mean "this text is about a design, not about the tool".
#:
#: ⚠ A BACKSTOP, NOT A FILTER — see the module warning above.
#:
#: Loaded from the SAME json file the TypeScript mirror reads. The two lists were
#: hand-maintained and had already drifted within a single ticket (``AWG`` was
#: here and not in TypeScript), which is why they no longer live in two places.
_SHAPES_FILE: Final = (
    Path(__file__).resolve().parents[4]
    / "shared-types"
    / "fixtures"
    / "tool-knowledge"
    / "customer-shapes.json"
)


def _load_customer_shapes() -> tuple[tuple[re.Pattern[str], str], ...]:
    raw = json.loads(_SHAPES_FILE.read_text())
    return tuple((re.compile(entry["re"], re.I), entry["why"]) for entry in raw["patterns"])


_CUSTOMER_SHAPED: Final = _load_customer_shapes()

_CONTROL_ID_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
#: The ``\s?`` inside the starred group used to be ambiguous with the ``\s+``
#: that opened it, so every double space doubled the parse count — 83 characters
#: took seconds to reject. Dropping the redundant ``\s?`` and bounding the repeat
#: makes it linear. ``version_range`` is the one string not routed through
#: ``_vendor_text``, so its ``max_length`` is the only thing that was containing it.
_VERSION_RANGE_RE: Final = re.compile(
    r"(?:[<>=~^]{0,2}\d+(?:\.\d+){0,2})(?:\s+[<>=~^]{0,2}\d+(?:\.\d+){0,2}){0,3}"
)
#: Key combinations: "E", "Ctrl+E", "Shift+Alt+D". Deliberately NOT an alternation
#: of Ctrl|Alt|Shift|... against [A-Za-z0-9]+ — every one of those literals is
#: also alphanumeric, so each token would have two parses and a non-matching
#: input would backtrack exponentially. One unambiguous class instead.
_SHORTCUT_RE: Final = re.compile(r"^[A-Za-z0-9]{1,10}(\+[A-Za-z0-9]{1,10}){0,4}$")


def _vendor_text(raw: str, field: str) -> str:
    """Check a piece of vendor UI text, or raise.

    The TypeScript side brands the result so a raw string cannot even be
    assigned; Python has no equivalent, so this is the enforcement point and it
    is applied to EVERY string that reaches the store.
    """
    # NFKC FIRST. Without it "／home／mehdi／chassis․f3d" (fullwidth solidus, one-dot
    # leader) is a different string to every pattern below while rendering
    # identically to a human — homoglyph evasion, demonstrated in review.
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text:
        raise ValueError(f"{field}: must not be empty")
    if len(text) > MAX_VENDOR_TEXT:
        raise ValueError(f"{field}: exceeds the {MAX_VENDOR_TEXT}-character length cap")
    for pattern, why in _CUSTOMER_SHAPED:
        if pattern.search(text):
            raise ValueError(f"{field}: rejected — {why}. Tool knowledge never describes a design.")
    return text


class Invocation(BaseModel):
    """How a user triggers the control. Both halves optional; it may be icon-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Vendor menu labels, outermost first. EVERY segment is checked —
    #: "File > Open Recent > ~/designs/arm.f3d" is a real vendor menu carrying
    #: real customer content.
    menu_path: list[str] | None = Field(default=None, max_length=8)
    shortcut: str | None = Field(default=None, max_length=64)

    @field_validator("menu_path")
    @classmethod
    def _check_menu_path(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [_vendor_text(segment, f"menu_path[{i}]") for i, segment in enumerate(value)]

    @field_validator("shortcut")
    @classmethod
    def _check_shortcut(cls, value: str | None) -> str | None:
        if value is not None and not _SHORTCUT_RE.fullmatch(value):
            raise ValueError("shortcut: must be a key combination like 'E' or 'Ctrl+Shift+D'")
        return value


class ScreenLocator(BaseModel):
    """Where the control sits, as a NORMALISED box in 0..1 of the window.

    Numbers, never an image. A screenshot of a customer's screen is customer
    content, so there is no field to put one in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]
    w: Annotated[float, Field(ge=0, le=1)]
    h: Annotated[float, Field(ge=0, le=1)]


class ToolKnowledge(BaseModel):
    """One fact about one tool's UI.

    THE COMPLETE COLUMN SET. There is no escape hatch, and adding one is a
    security change that goes to a human (CLAUDE.md §7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: ToolFamily
    #: A version range the fact holds for, e.g. ">=2.0 <3.0".
    version_range: str = Field(max_length=64)
    surface: UiSurface
    #: A vendor control identifier: a slug, never a sentence.
    control_id: str = Field(max_length=128)
    #: The on-screen text of the control.
    label: str = Field(max_length=MAX_VENDOR_TEXT)
    effect: ControlEffect
    #: What the control does, in one or two sentences about the TOOL.
    description: str = Field(max_length=MAX_VENDOR_TEXT)
    invocation: Invocation | None = None
    locator: ScreenLocator | None = None
    provenance: Provenance

    @field_validator("label", "description")
    @classmethod
    def _check_prose(cls, value: str, info: ValidationInfo) -> str:
        # Name the field: "why did this sync fail?" must be answerable (CLAUDE.md §6).
        return _vendor_text(value, info.field_name or "text")

    @field_validator("control_id")
    @classmethod
    def _check_control_id(cls, value: str) -> str:
        text = _vendor_text(value, "control_id")
        if not _CONTROL_ID_RE.fullmatch(text):
            raise ValueError(
                "control_id: must be a lowercase dotted slug, e.g. 'fusion.solid.extrude'"
            )
        return text

    @field_validator("version_range")
    @classmethod
    def _check_version_range(cls, value: str) -> str:
        if not _VERSION_RANGE_RE.fullmatch(value.strip()):
            raise ValueError("version_range: must be a version range like '>=2.0 <3.0'")
        return value.strip()


__all__ = [
    "MAX_VENDOR_TEXT",
    "ControlEffect",
    "Invocation",
    "Provenance",
    "ScreenLocator",
    "ToolFamily",
    "ToolKnowledge",
    "UiSurface",
]
