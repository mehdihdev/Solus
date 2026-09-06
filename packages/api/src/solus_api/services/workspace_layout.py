"""Bounded, versioned project canvas coordinates (docs/api/workspace.md)."""

import math
import uuid
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import GraphEntity, Project, WorkspaceLayout

MAX_POSITIONS = 5000
MAX_COORDINATE = 100000


def _finite_number(value: object) -> object:
    # The shared validation handler echoes rejected inputs. A raw NaN/Infinity
    # would itself fail JSON serialization there, turning a bad input into 500.
    if isinstance(value, float) and not math.isfinite(value):
        raise APIError(422, "validation_error", "Layout numbers must be finite")
    return value


Coordinate = Annotated[
    float,
    BeforeValidator(_finite_number),
    Field(strict=True, allow_inf_nan=False, ge=-MAX_COORDINATE, le=MAX_COORDINATE),
]
LayoutVersion = Annotated[int, BeforeValidator(_finite_number), Field(strict=True, ge=0)]


class WorkspacePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: Coordinate
    y: Coordinate


Positions = Annotated[dict[uuid.UUID, WorkspacePosition], Field(max_length=MAX_POSITIONS)]


class WorkspaceLayoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: LayoutVersion
    positions: Positions

    @model_validator(mode="before")
    @classmethod
    def reject_nonfinite_input(cls, value: object) -> object:
        # Validate malformed/unknown fields too: Pydantic includes their raw
        # values in errors, which the shared handler must be able to serialize.
        pending = [value]
        visited = 0
        while pending:
            item = pending.pop()
            visited += 1
            if visited > MAX_POSITIONS * 4:
                raise APIError(422, "validation_error", "Layout input is too large")
            _finite_number(item)
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return value


class WorkspaceLayoutData(BaseModel):
    version: LayoutVersion
    positions: Positions


async def _require_live_project(
    session: AsyncSession, project_id: uuid.UUID, *, lock: bool = False
) -> None:
    statement = select(Project.id).where(Project.id == project_id, Project.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    if await session.scalar(statement) is None:
        raise APIError(404, "not_found", "Project not found")


async def _live_entity_ids(
    session: AsyncSession, project_id: uuid.UUID, entity_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not entity_ids:
        return set()
    return set(
        await session.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_(entity_ids),
                GraphEntity.deleted_at.is_(None),
            )
        )
    )


async def load_workspace_layout(
    session: AsyncSession, project_id: uuid.UUID
) -> WorkspaceLayoutData:
    await _require_live_project(session, project_id)
    layout = await session.get(WorkspaceLayout, project_id)
    if layout is None:
        return WorkspaceLayoutData(version=0, positions={})
    positions = {
        uuid.UUID(key): WorkspacePosition(**point) for key, point in layout.positions.items()
    }
    live = await _live_entity_ids(session, project_id, set(positions))
    return WorkspaceLayoutData(
        version=layout.version,
        positions={key: point for key, point in positions.items() if key in live},
    )


async def save_workspace_layout(
    session: AsyncSession, project_id: uuid.UUID, body: WorkspaceLayoutInput
) -> WorkspaceLayoutData:
    # Lock the stable parent before looking for the optional layout row. Locking
    # only the layout cannot serialize two first saves when no row exists yet.
    await _require_live_project(session, project_id, lock=True)
    layout = await session.get(WorkspaceLayout, project_id, populate_existing=True)
    current_version = layout.version if layout is not None else 0
    if body.version != current_version:
        raise APIError(409, "conflict", "Workspace layout changed; reload it before saving")
    entity_ids = set(body.positions)
    if await _live_entity_ids(session, project_id, entity_ids) != entity_ids:
        raise APIError(404, "not_found", "Layout entity not found")
    if layout is None:
        layout = WorkspaceLayout(project_id=project_id)
        session.add(layout)
    layout.version = current_version + 1
    layout.positions = {
        str(key): {"x": point.x, "y": point.y} for key, point in body.positions.items()
    }
    await session.flush()
    return WorkspaceLayoutData(version=layout.version, positions=body.positions)
