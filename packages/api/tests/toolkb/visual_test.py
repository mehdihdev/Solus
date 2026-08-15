"""SOLUS-TU-03 (SOLUSDEV-206) — visual-understanding path [RESEARCH-GRADE].

A spike, not a committed deliverable. Vision over an annotated screenshot →
(control, locator, confidence). Two hard invariants keep it safe:

- Model output is UNTRUSTED (CLAUDE.md §7): every proposal passes a firewall
  (shape, control-id slug, 0..1 locator, unit-interval confidence) before it is
  allowed anywhere near the store.
- Visual proposals may only attach geometry to a control vendor docs ALREADY
  know (the guard's visual path enforces this) and always land as CANDIDATE —
  never auto-promoted into the shared KB. Below-threshold proposals are dropped.

Routes model calls through the MO-01 gateway (RouteType.VISUAL_LOG) — never a
parallel provider stack. Keyless here → the extractor returns [] (no signal),
so tests drive it with an injected fake model.
"""

from collections.abc import Callable

from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.toolkb.ingest.visual import (
    VISUAL_MIN_CONFIDENCE,
    VisualProposal,
    ingest_visual_proposals,
    parse_vision_output,
)
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry
from solus_api.toolkb.storage import query_entries
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]


def _one(*, control_id: str = "kicad.x.y", x: float = 0.1, confidence: float = 0.7) -> str:
    import json

    return json.dumps(
        [
            {
                "control_id": control_id,
                "label": "L",
                "x": x,
                "y": 0.1,
                "w": 0.1,
                "h": 0.1,
                "confidence": confidence,
            }
        ]
    )


# ------------------------------------------------------------ output firewall
class TestParse:
    def test_extracts_valid_proposals(self) -> None:
        raw = (
            '[{"control_id": "kicad.eeschema.place_wire", "label": "Wire",'
            ' "x": 0.1, "y": 0.2, "w": 0.03, "h": 0.04, "confidence": 0.7}]'
        )
        out = parse_vision_output(raw)
        assert len(out) == 1
        p = out[0]
        assert p.control_id == "kicad.eeschema.place_wire"
        assert (p.x, p.y, p.w, p.h) == (0.1, 0.2, 0.03, 0.04)
        assert p.confidence == 0.7

    def test_rejects_out_of_range_locator(self) -> None:
        assert parse_vision_output(_one(x=1.5)) == []

    def test_rejects_bad_control_id_slug(self) -> None:
        assert parse_vision_output(_one(control_id="~/designs/arm.kicad_sch")) == []

    def test_rejects_confidence_out_of_unit_interval(self) -> None:
        assert parse_vision_output(_one(confidence=5)) == []

    def test_garbage_is_empty_not_an_error(self) -> None:
        assert parse_vision_output("the model rambled") == []
        assert parse_vision_output("") == []


# ------------------------------------------------------------- ingestion
async def test_only_known_controls_are_ingested_as_candidates(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    # a docs-published entry makes place_wire a known vendor control
    from solus_api.toolkb.schema import version_keys

    low, high = version_keys(">=9.0 <10.0")
    db.add(
        make_entry(
            control_id="kicad.eeschema.place_wire",
            version_range=">=9.0 <10.0",
            version_min_key=low,
            version_max_key=high,
        )
    )
    await db.flush()

    proposals = [
        VisualProposal("kicad.eeschema.place_wire", "Wire", 0.1, 0.2, 0.03, 0.04, 0.8),
        VisualProposal("kicad.eeschema.never_documented", "Mystery", 0.5, 0.5, 0.1, 0.1, 0.8),
    ]
    summary = await ingest_visual_proposals(
        db, proposals, tool=ToolFamily.KICAD, version_range=">=9.0 <10.0"
    )
    assert summary.ingested == 1  # only the known control
    assert summary.rejected == 1  # the undocumented one, by the guard

    # the ingested visual entry is a CANDIDATE — never auto-promoted, so it is
    # not served to tenants until an operator approves it
    served, _ = await query_entries(db, tool=ToolFamily.KICAD, version="9.0.4")
    assert all(r.acquired_via.value != "visual" for r in served)
    total = await db.scalar(
        select(func.count())
        .select_from(ToolKnowledgeEntry)
        .where(ToolKnowledgeEntry.acquired_via == "visual")
    )
    assert total == 1
    visual_row = (
        await db.execute(
            select(ToolKnowledgeEntry).where(ToolKnowledgeEntry.acquired_via == "visual")
        )
    ).scalar_one()
    assert visual_row.status is KnowledgeStatus.CANDIDATE


async def test_below_threshold_proposals_are_dropped(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    from solus_api.toolkb.schema import version_keys

    low, high = version_keys(">=9.0 <10.0")
    db.add(
        make_entry(
            control_id="kicad.eeschema.place_wire",
            version_range=">=9.0 <10.0",
            version_min_key=low,
            version_max_key=high,
        )
    )
    await db.flush()

    weak = [
        VisualProposal(
            "kicad.eeschema.place_wire", "Wire", 0.1, 0.2, 0.03, 0.04, VISUAL_MIN_CONFIDENCE - 0.05
        )
    ]
    summary = await ingest_visual_proposals(
        db, weak, tool=ToolFamily.KICAD, version_range=">=9.0 <10.0"
    )
    assert summary.ingested == 0
    assert summary.below_threshold == 1
