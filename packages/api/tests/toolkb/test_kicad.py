"""SOLUS-TU-02 (SOLUSDEV-205) — KiCad documentation-ingestion path.

The source is KiCad's own `TOOL_ACTION` definitions — the authoritative,
version-scoped, vendor-pure catalog of every command (name, friendly label,
tooltip, default hotkey). The parser is deterministic; the classifier is
conservative (precision over recall — it SKIPS any action whose surface or
effect it cannot derive confidently rather than guess a wrong pointer); and
every ingested entry rides the TU-06 guard's docs path (published,
provenance=vendor_docs, version-scoped).
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from solus_api.contracts.tool_knowledge import ControlEffect, ToolFamily, UiSurface
from solus_api.toolkb.ingest.kicad import (
    KicadAction,
    classify,
    control_id_for,
    ingest_kicad_actions,
    parse_tool_actions,
)
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry
from solus_api.toolkb.storage import query_entries
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURE = Path(__file__).parent / "fixtures" / "kicad" / "sch_actions_9.0.cpp"
KICAD_SOURCE_URL = "https://gitlab.com/kicad/code/kicad/-/raw/9.0/eeschema/tools/sch_actions.cpp"

type EntryFactory = Callable[..., ToolKnowledgeEntry]

_SAMPLE = """
// SCH_INSPECTION_TOOL
TOOL_ACTION SCH_ACTIONS::runERC( TOOL_ACTION_ARGS()
        .Name( "eeschema.InspectionTool.runERC" )
        .Scope( AS_GLOBAL )
        .FriendlyName( _( "Electrical Rules Checker" ) )
        .Tooltip( _( "Show the electrical rules checker window" ) )
        .Icon( BITMAPS::erc ) );

TOOL_ACTION SCH_ACTIONS::placeSymbolPin( TOOL_ACTION_ARGS()
        .Name( "eeschema.SymbolDrawing.placeSymbolPin" )
        .Scope( AS_GLOBAL )
        .DefaultHotkey( 'P' )
        .FriendlyName( _( "Draw Pins" ) )
        .Icon( BITMAPS::pin )
        .Flags( AF_ACTIVATE )
        .Parameter( SCH_PIN_T ) );

TOOL_ACTION SCH_ACTIONS::zoomIn( TOOL_ACTION_ARGS()
        .Name( "common.Control.zoomIn" )
        .Scope( AS_GLOBAL )
        .DefaultHotkey( '+' )
        .FriendlyName( _( "Zoom In" ) )
        .Icon( BITMAPS::zoom_in ) );
"""


# ------------------------------------------------------------------- parser
class TestParse:
    def test_extracts_core_fields(self) -> None:
        actions = {a.name: a for a in parse_tool_actions(_SAMPLE)}
        erc = actions["eeschema.InspectionTool.runERC"]
        assert erc.friendly_name == "Electrical Rules Checker"
        assert erc.tooltip == "Show the electrical rules checker window"
        assert erc.hotkey is None
        assert erc.activates is False

        pin = actions["eeschema.SymbolDrawing.placeSymbolPin"]
        assert pin.friendly_name == "Draw Pins"
        assert pin.tooltip is None
        assert pin.hotkey == "P"
        assert pin.activates is True

    def test_parses_the_real_fixture(self) -> None:
        actions = parse_tool_actions(FIXTURE.read_text())
        # sch_actions_9.0.cpp has ~205 TOOL_ACTION definitions
        assert len(actions) > 180
        assert all(a.name and a.friendly_name for a in actions)
        # every name is a dotted vendor slug
        assert all("." in a.name for a in actions)


# -------------------------------------------------------------- control_id
class TestControlId:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("eeschema.InspectionTool.runERC", "kicad.eeschema.inspection_tool.run_erc"),
            (
                "eeschema.SymbolDrawing.placeSymbolPin",
                "kicad.eeschema.symbol_drawing.place_symbol_pin",
            ),
            ("common.Control.zoomIn", "kicad.common.control.zoom_in"),
        ],
    )
    def test_normalizes_to_a_valid_slug(self, name: str, expected: str) -> None:
        from solus_api.contracts.tool_knowledge import _CONTROL_ID_RE

        result = control_id_for(name)
        assert result == expected
        # the CTR-05 slug validator must accept it (guard re-checks this)
        assert _CONTROL_ID_RE.fullmatch(result) is not None


# ---------------------------------------------------------------- classify
class TestClassify:
    def test_activate_flag_is_a_toolbar_tool(self) -> None:
        action = KicadAction(
            name="eeschema.SymbolDrawing.placeSymbolPin",
            friendly_name="Draw Pins",
            tooltip=None,
            hotkey="P",
            activates=True,
        )
        result = classify(action)
        assert result == (UiSurface.TOOLBAR, ControlEffect.CREATE_FEATURE)

    def test_hotkey_without_activate_is_keyboard(self) -> None:
        action = KicadAction(
            name="common.Control.zoomIn",
            friendly_name="Zoom In",
            tooltip=None,
            hotkey="+",
            activates=False,
        )
        assert classify(action) == (UiSurface.KEYBOARD, ControlEffect.NAVIGATE)

    def test_dialog_signal_from_tooltip(self) -> None:
        # the vendor's own tooltip says it shows a window — that IS the surface
        action = KicadAction(
            name="eeschema.InspectionTool.checkSymbol",
            friendly_name="Symbol Checker",
            tooltip="Show the symbol checker window",
            hotkey=None,
            activates=False,
        )
        assert classify(action) == (UiSurface.DIALOG, ControlEffect.SETTINGS)

    def test_dialog_signal_from_ellipsis_menu_convention(self) -> None:
        action = KicadAction(
            name="pcbnew.LengthTuner.settingsDialog",
            friendly_name="Length Tuning Settings...",
            tooltip=None,
            hotkey=None,
            activates=False,
        )
        assert classify(action) == (UiSurface.DIALOG, ControlEffect.SETTINGS)

    def test_no_surface_signal_is_skipped(self) -> None:
        # no hotkey, no activate flag, no dialog signal — unknowable surface
        action = KicadAction(
            name="eeschema.SomeTool.internalThing",
            friendly_name="Internal Thing",
            tooltip="Does an internal thing",
            hotkey=None,
            activates=False,
        )
        assert classify(action) is None

    def test_unclassifiable_effect_is_skipped(self) -> None:
        # has a hotkey (surface derivable) but the verb maps to no effect
        action = KicadAction(
            name="eeschema.SomeTool.frobnicate",
            friendly_name="Frobnicate Widget",
            tooltip=None,
            hotkey="Q",
            activates=False,
        )
        assert classify(action) is None


# ----------------------------------------------------------- ingestion e2e
async def test_ingests_the_kicad_catalog(db: AsyncSession) -> None:
    summary = await ingest_kicad_actions(
        db,
        sources=[FIXTURE.read_text()],
        version_range=">=9.0 <10.0",
        source_url=KICAD_SOURCE_URL,
    )
    # meaningful coverage, honestly bounded — not every action is classifiable
    assert summary.ingested > 40
    assert summary.ingested + summary.skipped == summary.parsed
    assert summary.rejected == 0

    total = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    assert total == summary.ingested

    # every entry landed published, vendor_docs, version-scoped to 9.x
    rows, _ = await query_entries(db, tool=ToolFamily.KICAD, version="9.0.4", limit=100)
    assert rows, "the ingested KiCad 9.0 catalog must be queryable at 9.0.4"
    sample = rows[0]
    assert sample.status is KnowledgeStatus.PUBLISHED
    assert sample.provenance.value == "vendor_docs"
    assert sample.acquired_via.value == "docs"
    assert sample.version_min_key == "0009.0000.0000"

    # not served for a different major
    outside, _ = await query_entries(db, tool=ToolFamily.KICAD, version="8.0.6", limit=100)
    assert outside == []


async def test_ingestion_is_idempotent(db: AsyncSession) -> None:
    first = await ingest_kicad_actions(
        db, sources=[FIXTURE.read_text()], version_range=">=9.0 <10.0", source_url=KICAD_SOURCE_URL
    )
    before = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    second = await ingest_kicad_actions(
        db, sources=[FIXTURE.read_text()], version_range=">=9.0 <10.0", source_url=KICAD_SOURCE_URL
    )
    after = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    assert first.ingested == second.ingested
    assert before == after  # re-run added nothing


async def test_customer_shaped_tooltip_is_rejected_not_ingested(db: AsyncSession) -> None:
    # A poisoned source block: a plausible-looking action whose tooltip carries
    # a customer file path. The guard's CTR-05 net must catch it; the run
    # continues, and it is COUNTED as rejected, never stored.
    poisoned = (
        _SAMPLE
        + """
TOOL_ACTION SCH_ACTIONS::openRecent( TOOL_ACTION_ARGS()
        .Name( "eeschema.Control.openRecent" )
        .Scope( AS_GLOBAL )
        .DefaultHotkey( 'R' )
        .FriendlyName( _( "Open Recent" ) )
        .Tooltip( _( "Open ~/designs/arm_v3.kicad_sch" ) )
        .Icon( BITMAPS::open ) );
"""
    )
    summary = await ingest_kicad_actions(
        db, sources=[poisoned], version_range=">=9.0 <10.0", source_url=KICAD_SOURCE_URL
    )
    assert summary.rejected >= 1
    rows, _ = await query_entries(
        db, tool=ToolFamily.KICAD, control_id="kicad.eeschema.control.open_recent"
    )
    assert rows == []
