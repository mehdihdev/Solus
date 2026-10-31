"""SOLUSDEV-321 P3-T1 — `annotate_edge`, the one seam that caches `checker_results` on an edge
(docs/api/relations.md §2). It reassigns that one key on the LIVE edge of the project and leaves
the rest of the row as the writer that made it left it; a `write_edge(edge_id=…)` instead replaces
attrs and evidence, revives tombstones and 409s on `managed_by` (plan row 2)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Final

import pytest
from pydantic import ValidationError
from solus_api.core.errors import APIError
from solus_api.graph.edges import annotate_edge, retire_edge, write_edge
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team
from solus_contracts.relations import EdgeEvidence, EvidenceKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_edge_writer_ratchet import ALLOWED, SRC_ROOT, edge_offenders

_ITEM: Final[dict[str, Any]] = {
    "rule_id": "pin_in_code_vs_wiring",
    "status": "fail",
    "severity": "critical",
    "message": "pin 9 is commanded but not wired",
    "evidence": {"pin": "9"},
    "at": "2026-10-27T12:00:00+02:00",
}


async def _project(db: AsyncSession) -> uuid.UUID:
    team = Team(name="annotate")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="annotate")
    db.add(project)
    await db.flush()
    return project.id


async def _wired(db: AsyncSession, project_id: uuid.UUID) -> GraphEdge:
    """A managed `wires` edge as the netlist inference writes it: nets, pins, evidence."""
    a, b = (
        GraphEntity(
            project_id=project_id,
            kind="component",
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=name,
        )
        for name in ("U1", "J2")
    )
    db.add_all([a, b])
    await db.flush()
    return await write_edge(
        db,
        project_id=project_id,
        src_id=a.id,
        dst_id=b.id,
        relation_type="wires",
        origin="inferred",
        confidence=0.9,
        evidence=[EdgeEvidence(kind=EvidenceKind.NETLIST, ref="SDA")],
        created_by=None,
        attrs={"nets": ["SDA"], "pins": {str(a.id): ["3"], str(b.id): ["1"]}, "managed_by": "m"},
        edge_id=uuid.uuid5(project_id, "wires:U1:J2"),
        managed_by="m",
    )


async def test_keeps_nets_pins_evidence_origin_confidence(db: AsyncSession) -> None:
    pid = await _project(db)
    edge = await _wired(db, pid)
    before = edge.attrs
    kept = dict(before)

    annotated = await annotate_edge(db, pid, edge.id, checker_results=[_ITEM])

    assert annotated is edge and annotated.attrs is not before and before == kept  # reassigned
    item = {**_ITEM, "at": "2026-10-27T10:00:00Z"}  # validated as a CheckerResult, in UTC
    assert annotated.attrs == {**kept, "checker_results": [item]}
    assert (annotated.origin, annotated.confidence, annotated.deleted_at) == ("inferred", 0.9, None)
    await db.refresh(annotated)  # flushed: the row itself holds it
    assert annotated.attrs["checker_results"] == [item]
    assert annotated.attrs["evidence"] == kept["evidence"] and annotated.attrs["managed_by"] == "m"

    again = await annotate_edge(db, pid, edge.id, checker_results=[])
    assert again is not None and again.attrs == {**kept, "checker_results": []}  # replaced


async def test_a_change_committed_since_the_callers_read_is_kept(engine: AsyncEngine) -> None:
    """I1 (P3-T3 fix 1): a matrix run reads its edges, judges them, and only then writes their
    results. A sync or an acceptance may commit new attrs on a row in between. `annotate_edge`
    re-reads the row fresh, under a row lock, and keeps them: it never writes back the caller's
    stale copy."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        pid = await _project(setup)
        edge_id = (await _wired(setup, pid)).id
        await setup.commit()

    async with maker() as run:
        # The run's read, held as the run holds its rows: the identity map keeps only what is
        # referenced, so an unheld copy would be re-read and hide the bug.
        held = await run.get(GraphEdge, edge_id)
        async with maker() as sync:  # a sync commits a new net meanwhile
            row = await sync.get(GraphEdge, edge_id)
            assert row is not None
            row.attrs = {**row.attrs, "nets": ["SDA", "SCL"]}
            await sync.commit()
        await annotate_edge(run, pid, edge_id, checker_results=[_ITEM])
        await run.commit()
        assert held is not None and held.attrs["nets"] == ["SDA", "SCL"]

    async with maker() as check:
        kept = await check.get(GraphEdge, edge_id)
        assert kept is not None and kept.attrs["nets"] == ["SDA", "SCL"]
        assert [item["rule_id"] for item in kept.attrs["checker_results"]] == [_ITEM["rule_id"]]


async def test_a_row_another_transaction_holds_is_skipped_not_waited_for(
    engine: AsyncEngine,
) -> None:
    """NB1 (P3-T3 fix 2, R68): a sync locks edge rows before it takes the project lock, so a caller
    holding the project lock must never wait for an edge row. A row another transaction holds is
    not written: `annotate_edge` returns None at once, and a later call writes it."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        pid = await _project(setup)
        edge_id = (await _wired(setup, pid)).id
        await setup.commit()

    async with maker() as sync, maker() as run:
        await sync.execute(select(GraphEdge.id).where(GraphEdge.id == edge_id).with_for_update())
        skipped = await asyncio.wait_for(
            annotate_edge(run, pid, edge_id, checker_results=[_ITEM]), timeout=10
        )
        await sync.rollback()  # the sync commits: the row is free again
        written = await annotate_edge(run, pid, edge_id, checker_results=[_ITEM])
        await run.commit()

    assert skipped is None and written is not None
    assert [item["rule_id"] for item in written.attrs["checker_results"]] == [_ITEM["rule_id"]]


async def test_a_tombstoned_foreign_or_unknown_edge_is_not_found(db: AsyncSession) -> None:
    pid, other = await _project(db), await _project(db)
    theirs = await _wired(db, other)
    retired = await _wired(db, pid)
    retire_edge(retired)
    await db.flush()
    for project_id, edge_id in ((pid, theirs.id), (pid, retired.id), (pid, uuid.uuid4())):
        with pytest.raises(APIError) as exc:
            await annotate_edge(db, project_id, edge_id, checker_results=[_ITEM])
        assert (exc.value.status_code, exc.value.code) == (404, "not_found")
    assert "checker_results" not in theirs.attrs and "checker_results" not in retired.attrs
    assert retired.deleted_at is not None  # never revived


async def test_a_malformed_item_writes_nothing(db: AsyncSession) -> None:
    pid = await _project(db)
    edge = await _wired(db, pid)
    with pytest.raises(ValidationError):
        await annotate_edge(db, pid, edge.id, checker_results=[{**_ITEM, "status": "ok"}])
    assert "checker_results" not in edge.attrs


async def test_outside_evidence_raises_the_edge_to_one_and_keeps_the_rest(db: AsyncSession) -> None:
    """R131 (SOLUSDEV-321 P6): `confirmed_by` is evidence from outside the graph that the edge holds
    (a live `ros2` listing). It raises the live edge to 1.0 and merges that evidence, deduped on
    `(kind, ref)`; origin, cached results and every other key stay as they were."""
    pid = await _project(db)
    edge = await _wired(db, pid)
    await annotate_edge(db, pid, edge.id, checker_results=[_ITEM])
    kept = dict(edge.attrs)
    seen = EdgeEvidence(
        kind=EvidenceKind.BUS_ENUMERATION, ref="ros2 node list", detail="seen live: /talker"
    )

    raised = await annotate_edge(db, pid, edge.id, confirmed_by=seen)

    assert raised is edge and (raised.origin, raised.confidence) == ("inferred", 1.0)
    assert raised.attrs == {**kept, "evidence": [*kept["evidence"], seen.model_dump(mode="json")]}
    first = raised.attrs
    again = await annotate_edge(db, pid, edge.id, confirmed_by=seen)
    assert again is not None and again.attrs == first  # the same listing adds nothing


def test_edge_writer_ratchet_unchanged() -> None:
    """`annotate_edge` sits in `graph/edges.py` and constructs no edge: the allowed sites are
    the same two and nothing else constructs a `GraphEdge`."""
    assert ALLOWED == {"graph/edges.py", "connectors/runtime.py"}
    assert edge_offenders(SRC_ROOT) == []
