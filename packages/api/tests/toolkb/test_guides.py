"""SOLUS-TU-09 (SOLUSDEV-212) — backend for the Guide side-panel.

A guide is an authored walkthrough of a real task (an ordered list of control
references + narration), resolved against the LIVE KB so it always reflects
current tool knowledge — the compounding point of the lane. Steps carry
confidence; a step whose control is absent from the KB (or version-mismatched)
is marked unavailable, never faked; a low-confidence step renders tentative.
Guide sourced ONLY from ladder steps 1-2 — zero overlay.
"""

from collections.abc import Callable
from pathlib import Path

from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.toolkb.guides import (
    TENTATIVE_BELOW,
    list_guides,
    load_guides,
    resolve_guide,
)
from solus_api.toolkb.ingest.kicad import ingest_kicad_actions
from solus_api.toolkb.schema import ToolKnowledgeEntry
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]

KICAD_SRC = (Path(__file__).parent / "fixtures" / "kicad" / "sch_actions_9.0.cpp").read_text()
KICAD_URL = "https://gitlab.com/kicad/code/kicad/-/raw/9.0/eeschema/tools/sch_actions.cpp"


async def _ingest_kicad(db: AsyncSession) -> None:
    await ingest_kicad_actions(
        db, sources=[KICAD_SRC], version_range=">=9.0 <10.0", source_url=KICAD_URL
    )


# ------------------------------------------------------------ authored data
def test_seed_guides_are_well_formed() -> None:
    guides = load_guides()
    assert guides, "at least one seed guide must ship (the first usable Guide)"
    for guide in guides:
        assert guide.id and guide.title and guide.steps
        assert guide.tool in set(ToolFamily)
        for step in guide.steps:
            # narration for BOTH modes (ADR-016), and a control reference
            assert step.control_id and step.note_guide and step.note_expert


def test_list_guides_filters_by_tool_and_version() -> None:
    kicad = list_guides(tool=ToolFamily.KICAD, version="9.0.4")
    assert any(g.tool is ToolFamily.KICAD for g in kicad)
    assert list_guides(tool=ToolFamily.FUSION, version="2.0") == []
    # a KiCad 9 guide is not offered for KiCad 7
    assert list_guides(tool=ToolFamily.KICAD, version="7.0") == []


# --------------------------------------------------------------- resolution
async def test_resolve_attaches_live_kb_meaning_and_confidence(db: AsyncSession) -> None:
    await _ingest_kicad(db)
    guide = list_guides(tool=ToolFamily.KICAD, version="9.0.4")[0]

    resolved = await resolve_guide(db, guide.id, version="9.0.4")
    assert resolved is not None
    assert resolved.title == guide.title
    assert resolved.steps, "the walkthrough must resolve to ordered steps"
    # at least one step resolves to a real KB entry (TU-02 ingested these)
    available = [s for s in resolved.steps if s.available]
    assert available, "guide steps must resolve against the ingested KB"
    first = available[0]
    assert first.label  # from the live KB entry
    assert first.description
    assert first.confidence is not None
    assert 0.0 <= first.confidence <= 1.0
    assert first.note_guide and first.note_expert  # both narrations carried
    assert first.step_number == resolved.steps.index(first) + 1


async def test_missing_control_is_unavailable_never_faked(db: AsyncSession) -> None:
    # resolve WITHOUT ingesting — no KB entries exist
    guide = list_guides(tool=ToolFamily.KICAD, version="9.0.4")[0]
    resolved = await resolve_guide(db, guide.id, version="9.0.4")
    assert resolved is not None
    assert all(not s.available for s in resolved.steps)
    assert all(s.label is None and s.confidence is None for s in resolved.steps)
    # the narration still shows (authored), so the panel degrades gracefully
    assert all(s.note_guide for s in resolved.steps)


async def test_low_confidence_step_is_tentative(db: AsyncSession, make_entry: EntryFactory) -> None:
    guide = list_guides(tool=ToolFamily.KICAD, version="9.0.4")[0]
    target = guide.steps[0].control_id
    # a published entry for the first step's control, but low confidence
    from solus_api.toolkb.schema import version_keys

    low, high = version_keys(">=9.0 <10.0")
    db.add(
        make_entry(
            control_id=target,
            confidence=TENTATIVE_BELOW - 0.1,
            version_range=">=9.0 <10.0",
            version_min_key=low,
            version_max_key=high,
        )
    )
    await db.flush()

    resolved = await resolve_guide(db, guide.id, version="9.0.4")
    assert resolved is not None
    step = next(s for s in resolved.steps if s.control_id == target)
    assert step.available and step.tentative is True


async def test_unknown_guide_id_is_none(db: AsyncSession) -> None:
    assert await resolve_guide(db, "no.such.guide", version="9.0.4") is None
