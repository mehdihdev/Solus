"""SOLUS-TU-06 — operator review CLI (the mechanical "review level").

Only the session-level handlers are tested; `main()` is engine wiring. The
approve/reject state transitions themselves are guard functions, tested in
test_guard.py — this file covers what the operator sees.
"""

from collections.abc import Callable

import pytest
from solus_api.models import utcnow
from solus_api.toolkb.review import format_row, list_candidates, show_entry
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]


async def test_list_candidates_returns_only_live_candidates(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    db.add(make_entry(control_id="kicad.eeschema.published_thing"))
    candidate = make_entry(
        control_id="kicad.eeschema.pending_thing", status=KnowledgeStatus.CANDIDATE
    )
    db.add(candidate)
    deleted = make_entry(control_id="kicad.eeschema.dead_thing", status=KnowledgeStatus.CANDIDATE)
    deleted.deleted_at = utcnow()
    db.add(deleted)
    await db.flush()

    rows = await list_candidates(db)
    assert [row.control_id for row in rows] == ["kicad.eeschema.pending_thing"]


async def test_format_row_names_the_essentials(db: AsyncSession, make_entry: EntryFactory) -> None:
    row = make_entry(status=KnowledgeStatus.CANDIDATE)
    db.add(row)
    await db.flush()

    line = format_row(row)
    assert str(row.id) in line
    assert "kicad" in line
    assert "kicad.eeschema.place_net_label" in line
    assert "candidate" in line
    assert "0.8" in line


async def test_show_entry_renders_contract_and_bookkeeping(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    row = make_entry(status=KnowledgeStatus.CANDIDATE)
    db.add(row)
    await db.flush()

    text = await show_entry(db, row.id)
    assert "Add Net Label" in text  # the operator must see what they approve
    assert "vendor_docs" in text
    assert "candidate" in text
    assert "confidence" in text


async def test_show_entry_missing_raises(db: AsyncSession) -> None:
    import uuid

    with pytest.raises(LookupError):
        await show_entry(db, uuid.uuid4())
