"""SOLUS-TU-04 — read side of the tool-knowledge store.

The read path is the tenant-facing surface of the shared KB: it must serve
published, live rows only — candidates and soft-deleted rows are invisible by
construction, which is half of the TU-06 staging story.
"""

from collections.abc import Callable

import pytest
from solus_api.contracts.tool_knowledge import ControlEffect, ToolFamily, UiSurface
from solus_api.models import utcnow
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry, version_keys
from solus_api.toolkb.storage import MAX_QUERY_LIMIT, query_entries
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]


@pytest.fixture
def make_kicad(make_entry: EntryFactory) -> EntryFactory:
    def _kicad(
        control_id: str = "kicad.eeschema.place_net_label", **overrides: object
    ) -> ToolKnowledgeEntry:
        low, high = version_keys(">=8.0 <9.0")
        fields: dict[str, object] = {
            "control_id": control_id,
            "version_min_key": low,
            "version_max_key": high,
        }
        fields.update(overrides)
        return make_entry(**fields)

    return _kicad


async def test_requires_sane_limit(db: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await query_entries(db, tool=ToolFamily.KICAD, limit=0)
    with pytest.raises(ValueError):
        await query_entries(db, tool=ToolFamily.KICAD, limit=MAX_QUERY_LIMIT + 1)


async def test_serves_published_live_rows_only(db: AsyncSession, make_kicad: EntryFactory) -> None:
    db.add(make_kicad("kicad.eeschema.place_net_label"))
    db.add(make_kicad("kicad.eeschema.candidate_thing", status=KnowledgeStatus.CANDIDATE))
    deleted = make_kicad("kicad.eeschema.deleted_thing")
    deleted.deleted_at = utcnow()
    db.add(deleted)
    await db.flush()

    rows, meta = await query_entries(db, tool=ToolFamily.KICAD)
    assert [row.control_id for row in rows] == ["kicad.eeschema.place_net_label"]
    assert meta == {"limit": 50, "has_next": False, "next_cursor": None}


async def test_version_window_boundaries(db: AsyncSession, make_kicad: EntryFactory) -> None:
    db.add(make_kicad("kicad.eeschema.place_net_label"))
    open_low, open_high = version_keys(">=9.0")
    db.add(
        make_kicad(
            "kicad.eeschema.new_in_nine",
            version_range=">=9.0",
            version_min_key=open_low,
            version_max_key=open_high,
        )
    )
    await db.flush()

    async def ids_at(version: str) -> set[str]:
        rows, _ = await query_entries(db, tool=ToolFamily.KICAD, version=version)
        return {row.control_id for row in rows}

    assert await ids_at("8.0.6") == {"kicad.eeschema.place_net_label"}
    assert await ids_at("8.0") == {"kicad.eeschema.place_net_label"}
    # exclusive upper bound: 9.0 leaves the 8.x window, enters the open-ended one
    assert await ids_at("9.0") == {"kicad.eeschema.new_in_nine"}
    assert await ids_at("42.0.1") == {"kicad.eeschema.new_in_nine"}
    assert await ids_at("7.9.9") == set()


async def test_version_must_be_parseable(db: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await query_entries(db, tool=ToolFamily.KICAD, version="latest")


async def test_filters_surface_effect_control_id(
    db: AsyncSession, make_kicad: EntryFactory
) -> None:
    db.add(make_kicad("kicad.eeschema.place_net_label"))
    db.add(
        make_kicad(
            "kicad.pcbnew.route_track",
            surface=UiSurface.TOOLBAR,
            effect=ControlEffect.MODIFY_FEATURE,
        )
    )
    await db.flush()

    rows, _ = await query_entries(db, tool=ToolFamily.KICAD, surface=UiSurface.TOOLBAR)
    assert [row.control_id for row in rows] == ["kicad.pcbnew.route_track"]

    rows, _ = await query_entries(db, tool=ToolFamily.KICAD, effect=ControlEffect.CREATE_FEATURE)
    assert [row.control_id for row in rows] == ["kicad.eeschema.place_net_label"]

    rows, _ = await query_entries(db, tool=ToolFamily.KICAD, control_id="kicad.pcbnew.route_track")
    assert [row.control_id for row in rows] == ["kicad.pcbnew.route_track"]

    rows, _ = await query_entries(db, tool=ToolFamily.FUSION)
    assert rows == []


async def test_cursor_pagination_walks_every_row_once(
    db: AsyncSession, make_kicad: EntryFactory
) -> None:
    for i in range(5):
        db.add(make_kicad(f"kicad.eeschema.control_{i}"))
    await db.flush()

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        rows, meta = await query_entries(db, tool=ToolFamily.KICAD, limit=2, cursor=cursor)
        seen.extend(row.control_id for row in rows)
        pages += 1
        if not meta["has_next"]:
            break
        cursor = meta["next_cursor"]
    assert pages == 3
    assert len(seen) == 5 and len(set(seen)) == 5
