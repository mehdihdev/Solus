"""SOLUS-TU-09 (SOLUSDEV-212) — backend for the Guide side-panel.

A guide is an authored walkthrough of a real task in a supported tool: an
ordered list of control references plus per-mode narration (ADR-016 guide /
expert). It is TOOL knowledge — a vendor task procedure, shareable, with no
customer content — so it lives as committed seed data, not per-tenant state.

Guides are RESOLVED against the live KB at read time (`resolve_guide`): each
step picks up the current label / description / invocation / confidence from
the tool_knowledge store, so the Guide compounds as the KB thickens (the
strategic point of the lane). A step whose control is absent from the KB or
version-mismatched is marked **unavailable** — never faked — and the authored
narration still renders so the panel degrades gracefully. A step below the
confidence threshold renders **tentative** (precision over recall: an honest
"we're not sure" beats a confident wrong instruction).

Sourced from ladder steps 1-2 only — zero overlay dependency. This is the
first genuinely usable Guide and the graceful-degradation target for SOLX-03.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.contracts.tool_knowledge import ScreenLocator, ToolFamily
from solus_api.models import utcnow
from solus_api.toolkb.schema import ToolKnowledgeEntry, locator_of
from solus_api.toolkb.staleness import effective_confidence, is_stale
from solus_api.toolkb.storage import query_entries

#: A resolved step at or above this confidence is shown plainly; below it the
#: panel renders the step as tentative (never a confident wrong pointer).
TENTATIVE_BELOW: Final = 0.6

_GUIDES_DIR: Final = Path(__file__).resolve().parent / "guides"


@dataclass(frozen=True)
class GuideStep:
    control_id: str
    note_guide: str
    note_expert: str


@dataclass(frozen=True)
class GuideDef:
    id: str
    tool: ToolFamily
    version_range: str
    title: str
    summary: str
    steps: tuple[GuideStep, ...]


@dataclass(frozen=True)
class ResolvedStep:
    step_number: int
    control_id: str
    entry_id: str | None  # the resolved KB entry's UUID — the TU-08 feedback target
    note_guide: str
    note_expert: str
    available: bool
    tentative: bool
    stale: bool
    label: str | None
    description: str | None
    shortcut: str | None
    menu_path: list[str] | None
    surface: str | None
    confidence: float | None
    #: Normalised 0..1 box within the tool window, when the KB has one
    #: (SOLUS-TU-10 / SOLX-03). The overlay needs geometry to point at anything;
    #: the side panel ignores it. None is the COMMON case, not an error: vendor
    #: documentation carries no coordinates (TU-02 ingests `locator: None`), so
    #: today only the research-grade visual path (TU-03) ever populates it. A
    #: step without a locator is exactly what the overlay must NOT guess at — it
    #: degrades to the panel instead.
    locator: ScreenLocator | None


@dataclass(frozen=True)
class ResolvedGuide:
    id: str
    tool: ToolFamily
    title: str
    summary: str
    steps: tuple[ResolvedStep, ...]


@lru_cache(maxsize=1)
def load_guides() -> tuple[GuideDef, ...]:
    """Load and validate the committed guide seed data (cached)."""
    guides: list[GuideDef] = []
    for path in sorted(_GUIDES_DIR.glob("*.json")):
        raw = json.loads(path.read_text())
        steps = tuple(
            GuideStep(
                control_id=s["control_id"],
                note_guide=s["note_guide"],
                note_expert=s["note_expert"],
            )
            for s in raw["steps"]
        )
        guides.append(
            GuideDef(
                id=raw["id"],
                tool=ToolFamily(raw["tool"]),
                version_range=raw["version_range"],
                title=raw["title"],
                summary=raw["summary"],
                steps=steps,
            )
        )
    return tuple(guides)


def _covers(version_range: str, version: str) -> bool:
    from solus_api.toolkb.schema import version_key, version_keys

    low, high = version_keys(version_range)
    key = version_key(version)
    return low <= key and (high is None or key < high)


def list_guides(*, tool: ToolFamily, version: str) -> list[GuideDef]:
    """Authored guides for a tool whose version range covers ``version``."""
    return [
        guide
        for guide in load_guides()
        if guide.tool is tool and _covers(guide.version_range, version)
    ]


async def _lookup(
    session: AsyncSession, tool: ToolFamily, control_id: str, version: str
) -> ToolKnowledgeEntry | None:
    rows, _ = await query_entries(
        session, tool=tool, version=version, control_id=control_id, limit=1
    )
    return rows[0] if rows else None


async def resolve_guide(
    session: AsyncSession, guide_id: str, *, version: str
) -> ResolvedGuide | None:
    """Resolve a guide's steps against the live KB, or None if no such guide."""
    guide = next((g for g in load_guides() if g.id == guide_id), None)
    if guide is None:
        return None
    now = utcnow()
    resolved: list[ResolvedStep] = []
    for index, step in enumerate(guide.steps):
        entry = await _lookup(session, guide.tool, step.control_id, version)
        # Effective (decayed) confidence, so a stale entry reads as tentative
        # instead of confident — TU-07: stale-but-served-confident is the failure.
        eff = None if entry is None else effective_confidence(entry, now=now)
        resolved.append(
            ResolvedStep(
                step_number=index + 1,
                control_id=step.control_id,
                entry_id=str(entry.id) if entry else None,
                note_guide=step.note_guide,
                note_expert=step.note_expert,
                available=entry is not None,
                tentative=eff is not None and eff < TENTATIVE_BELOW,
                stale=entry is not None and is_stale(entry, now=now),
                label=entry.label if entry else None,
                description=entry.description if entry else None,
                shortcut=entry.shortcut if entry else None,
                menu_path=list(entry.menu_path) if entry and entry.menu_path else None,
                surface=entry.surface.value if entry else None,
                confidence=None if eff is None else round(eff, 3),
                locator=locator_of(entry) if entry else None,
            )
        )
    return ResolvedGuide(
        id=guide.id,
        tool=guide.tool,
        title=guide.title,
        summary=guide.summary,
        steps=tuple(resolved),
    )
