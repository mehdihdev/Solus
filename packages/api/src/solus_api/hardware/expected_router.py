"""docs/api/hardware.md §4 "Described, not seen yet" (SOLUSDEV-326 P3) — the Hardware page's rows
for what the workspace describes and nothing has answered. A read for any project member, as
themselves (§1a); the workspace's own text reaches the page as short single lines only.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from solus_api.agent.cards import single_line
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.graph.read_scope import resolve_scope
from solus_api.hardware.expected_parts import MAX_ROWS, MAX_SOURCES, Expected, expected_parts
from solus_api.models import GraphEntity

router = APIRouter(prefix="/api/v1/projects/{project_id}/hardware")
_TEXT = 80


class ExpectedRow(BaseModel):
    name: str
    what: str
    robot_id: uuid.UUID | None
    source: str


class ExpectedParts(BaseModel):
    expected: list[ExpectedRow]
    #: Where the rows come from, for the collapsed row; never more than `MAX_SOURCES`.
    sources: list[str]
    #: Rows left out of `expected` (the cap).
    more: int


class ExpectedPartsEnvelope(BaseModel):
    data: ExpectedParts


def _named(row: Mapping[str, Any]) -> tuple[object, object]:
    """A described part's name and what it is, by where the workspace says it."""
    if row["from"] == "config":
        bus = f"{row['protocol']} {row['address']}"
        return row["part"] or row["model"] or bus, row["model"] or bus
    if row["from"] == "ros":
        return row["name"], row["type"]
    if row["from"] == "sketch":
        return row["name"], "uses " + ", ".join(row["libraries"])
    return row["name"], row["value"] or row["symbol"]


def _page_row(part: Expected) -> ExpectedRow:
    name, what = _named(part.row)
    return ExpectedRow(
        name=single_line(name, _TEXT),
        what=single_line(what, _TEXT),
        robot_id=part.row.get("robot_id"),
        source=single_line(part.source, _TEXT),
    )


@router.get("/expected", response_model=ExpectedPartsEnvelope)
async def list_expected(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """What the caller's workspace describes and nothing has answered yet: planned rows of the
    robots they may see, sensor topics, sketches and MCU symbols."""
    # The caller's own view, resolved here: never whatever scope happens to be bound.
    scope = await resolve_scope(session, ctx.project.id, ctx.user.id)
    visible = (scope.entity_predicate(), GraphEntity.deleted_at.is_(None))
    rows = [_page_row(part) for part in await expected_parts(session, ctx.project.id, visible)]
    listed = rows[:MAX_ROWS]
    sources = list(dict.fromkeys(row.source for row in listed))  # never a row past the cut
    return {
        "data": ExpectedParts(
            expected=listed,
            sources=sources[:MAX_SOURCES],
            more=max(0, len(rows) - MAX_ROWS),
        ).model_dump(mode="json")
    }
