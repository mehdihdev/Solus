"""What the workspace says should exist and nothing has answered yet (SOLUSDEV-326): the planned
bus-map rows of robots (library slots too), sensor topics in ROS code, the libraries sketches
include and MCU symbols in schematics.

One read for `hardware.expected_parts` (SOL) and `GET /hardware/expected` (the Hardware page),
always under the reader's own predicate (docs/api/hardware.md §1a): a robot they may not see gives
no row and no source label. Values are the workspace's own text, uncapped — each caller cuts them
to one printable line for its surface.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.hardware.config import LifecycleState
from solus_api.models import GraphEntity, Source

logger = logging.getLogger(__name__)

#: Rows one query reads, and what one answer to the page carries.
MAX_ROWS: Final = 64
#: Source labels the page's collapsed row carries.
MAX_SOURCES: Final = 8
MAX_LIBRARIES: Final = 16


@dataclass(frozen=True)
class Expected:
    """One described part: its origin's own fields (`from` says which) and where the workspace
    says it — the robot, the file or the connected source that names it."""

    row: dict[str, Any]
    source: str


def _unanswered_row(config: Any, entry: Any) -> bool:
    """A bus-map row no part answers yet: none named, or its part still planned."""
    part = config.parts.get(str(entry.part_entity_id)) if entry.part_entity_id else None
    return entry.part_entity_id is None or (
        part is not None and part.lifecycle is LifecycleState.PLANNED
    )


async def expected_parts(
    session: AsyncSession,
    project_id: uuid.UUID,
    visible: Sequence[ColumnElement[bool]],
    robot_id: uuid.UUID | None = None,
) -> list[Expected]:
    """Planned rows of the robots `visible` admits (one robot's with `robot_id`), then — for the
    whole workspace — what its code and schematics describe."""
    rows = await _configured(session, project_id, visible, robot_id)
    if robot_id is None:
        rows += await _described(session, visible)
    return rows


async def _configured(
    session: AsyncSession,
    project_id: uuid.UUID,
    visible: Sequence[ColumnElement[bool]],
    robot_id: uuid.UUID | None,
) -> list[Expected]:
    from solus_api.hardware.runtime import resolve_runtime_config

    stmt = select(GraphEntity).where(
        *visible, GraphEntity.kind == kinds.PHYSICAL_ROBOT, GraphEntity.origin == "manual"
    )
    if robot_id is not None:
        stmt = stmt.where(GraphEntity.id == robot_id)
    rows: list[Expected] = []
    for robot in await session.scalars(stmt.order_by(GraphEntity.name).limit(MAX_ROWS)):
        try:
            config = await resolve_runtime_config(session, project_id, robot.id)
        except APIError:
            logger.warning("config unreadable robot=%s: no planned rows", robot.id)
            continue
        rows += await _planned(session, visible, robot, config)
    return rows


async def _planned(
    session: AsyncSession, visible: Sequence[ColumnElement[bool]], robot: GraphEntity, config: Any
) -> list[Expected]:
    waiting = [entry for entry in config.bus_map if _unanswered_row(config, entry)]
    ids = [entry.part_entity_id for entry in waiting if entry.part_entity_id]
    named = await session.execute(
        select(GraphEntity.id, GraphEntity.name).where(*visible, GraphEntity.id.in_(ids))
    )
    names = {part_id: name for part_id, name in named.tuples()}
    return [
        Expected(
            {
                "from": "config",
                "robot_id": str(robot.id),
                "robot": robot.name,
                "protocol": entry.protocol,
                "address": entry.address,
                "model": entry.model,
                "part_id": str(entry.part_entity_id) if entry.part_entity_id else None,
                "part": names.get(entry.part_entity_id),
            },
            robot.name,
        )
        for entry in waiting
        # A row naming a part this member may not see is no row of theirs (§1a).
        if entry.part_entity_id is None or entry.part_entity_id in names
    ]


async def _described(
    session: AsyncSession, visible: Sequence[ColumnElement[bool]]
) -> list[Expected]:
    attrs = GraphEntity.attrs
    topics = await _nodes(
        session, visible, kinds.ROS_TOPIC, attrs["type"].astext.startswith("sensor_msgs/")
    )
    sketches = await _nodes(session, visible, kinds.ARDUINO_SKETCH)
    # A symbol from an `MCU_*` library: the schematic's own word for a programmable chip.
    chips = await _nodes(
        session, visible, kinds.COMPONENT, attrs["libsource"].astext.startswith("MCU_")
    )
    return [
        *(
            Expected(
                {"from": "ros", "entity_id": str(n.id), "name": n.name, "type": n.attrs["type"]},
                source or "ROS code",
            )
            for n, source in topics
        ),
        *(found for found in (_sketch(n, source) for n, source in sketches) if found),
        *(
            Expected(
                {
                    "from": "schematic",
                    "entity_id": str(n.id),
                    "name": n.name,
                    "symbol": n.attrs.get("libsource"),
                    "value": n.attrs.get("value"),
                },
                source or "schematic",
            )
            for n, source in chips
        ),
    ]


async def _nodes(
    session: AsyncSession,
    visible: Sequence[ColumnElement[bool]],
    kind: str,
    *where: ColumnElement[bool],
) -> Sequence[tuple[GraphEntity, str | None]]:
    """Entities of `kind`, each with the name of the connected source it came from."""
    # Aliased: the reader's predicate has its own subquery over `Source`.
    origin = aliased(Source)
    stmt = (
        select(GraphEntity, origin.name)
        .outerjoin(origin, origin.id == GraphEntity.source_id)
        .where(*visible, GraphEntity.kind == kind, *where)
    )
    found = await session.execute(stmt.order_by(GraphEntity.name).limit(MAX_ROWS))
    return [(entity, name) for entity, name in found.tuples()]


def _sketch(sketch: GraphEntity, source: str | None) -> Expected | None:
    """A sketch's includes and buses, over every file it observed; None when it includes none."""
    seen = [o for o in sketch.attrs.get("observations") or [] if isinstance(o, Mapping)]
    libraries = sorted({str(name) for o in seen for name in o.get("libraries") or []})
    if not libraries:
        return None
    files = [PurePosixPath(str(o["source_file"])).name for o in seen if o.get("source_file")]
    return Expected(
        {
            "from": "sketch",
            "entity_id": str(sketch.id),
            "name": sketch.name,
            "libraries": libraries[:MAX_LIBRARIES],
            "buses": sorted({str(bus) for o in seen for bus in o.get("buses") or []}),
        },
        next(iter(files), None) or source or "sketch",
    )


__all__ = ["MAX_ROWS", "MAX_SOURCES", "Expected", "expected_parts"]
