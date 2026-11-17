"""Manual robot instances and durable ownership evidence (Workspace Phase 4).

A robot contains its parts directly (SOLUSDEV-326): `ownership_edge` is the one ownership
rule every reader uses. The transaction-scoped creation method is also the future R2
detection hook. It always creates a new instance; callers authorize, commit and publish hints.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator
from pydantic.json_schema import JsonSchemaValue, SkipJsonSchema
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Select
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import visibility_attrs
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, utcnow

RobotName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512, strict=True)
]


class _RobotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def string_fields_only(cls, value: object) -> object:
        # These bodies contain only strings. Reject unsupported shapes before
        # Pydantic echoes raw inputs (including NaN) into the error serializer.
        # Omitted name defaults to the project; explicit null is not a name.
        if not isinstance(value, dict) or any(
            key not in cls.model_fields or not isinstance(item, str) for key, item in value.items()
        ):
            raise APIError(
                422, "validation_error", "Robot input must use its documented string fields"
            )
        return value


def _omit_schema_default(schema: JsonSchemaValue) -> None:
    schema.pop("default", None)


class PhysicalRobotCreate(_RobotInput):
    type: Literal["physical_robot"]
    name: RobotName | SkipJsonSchema[None] = Field(
        default=None,
        description="Omit to use the project's name.",
        json_schema_extra=_omit_schema_default,
    )


class PhysicalRobotRename(_RobotInput):
    name: RobotName


@dataclass(frozen=True)
class GraphChangeCounts:
    entities_created: int = 0
    entities_updated: int = 0
    entities_deleted: int = 0
    relations_created: int = 0
    relations_deleted: int = 0


@dataclass(frozen=True)
class RobotRemoval:
    root: GraphEntity
    retained_part_ids: list[uuid.UUID]
    counts: GraphChangeCounts


def _container_ids(project_id: uuid.UUID, *, deleted: bool) -> Select[tuple[uuid.UUID]]:
    """Manual, source-less Physical Robot roots: the only owners of parts.

    The same definition is used for live ownership and deleted evidence. There
    is no recursive walk through the CAD/code/fingerprint graph.
    """
    return select(GraphEntity.id).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind == "physical_robot",
        GraphEntity.origin == "manual",
        GraphEntity.source_id.is_(None),
        GraphEntity.deleted_at.is_not(None) if deleted else GraphEntity.deleted_at.is_(None),
    )


def ownership_edge(project_id: uuid.UUID, *, deleted: bool = False) -> ColumnElement[bool]:
    """THE ownership rule (SOLUSDEV-326): a `graph_edge` row is a robot owning a part when it
    is a live manual (source-less) `contains` edge from a live manual Physical Robot root.
    `deleted` reads the durable evidence of removed ownership: deleted edges, deleted roots."""
    return and_(
        GraphEdge.project_id == project_id,
        GraphEdge.relation_type == "contains",
        GraphEdge.origin == "manual",
        GraphEdge.source_id.is_(None),
        GraphEdge.deleted_at.is_not(None) if deleted else GraphEdge.deleted_at.is_(None),
        GraphEdge.src_id.in_(_container_ids(project_id, deleted=deleted)),
    )


def orphaned_robot_part_filter(project_id: uuid.UUID) -> ColumnElement[bool]:
    """Filter live entity reads by durable removed ownership, excluding live owners."""

    def targets(*, deleted: bool) -> Select[tuple[uuid.UUID]]:
        return select(GraphEdge.dst_id).where(ownership_edge(project_id, deleted=deleted))

    # `robot_category` is a retired legacy kind (a32600000001); excluding it stays harmless.
    return (
        GraphEntity.id.in_(targets(deleted=True))
        & GraphEntity.id.not_in(targets(deleted=False))
        & GraphEntity.kind.not_in(("physical_robot", "robot_category"))
    )


class PhysicalRobotService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _lock_project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.scalar(
            select(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if project is None:
            raise APIError(404, "not_found", "Project not found")
        return project

    async def create(
        self,
        project_id: uuid.UUID,
        name: str | None = None,
        *,
        in_graph: bool = True,
        onboarded_by: uuid.UUID | None = None,
    ) -> GraphEntity:
        """Create one robot root, without committing or calling a provider. Its parts join
        later through `contains` edges from this root. Out of the graph (SOLUSDEV-326) only its
        onboarder sees it, and the parts, brains and config nodes it gets follow it."""
        project = await self._lock_project(project_id)
        root = GraphEntity(
            id=uuid7(),
            project_id=project_id,
            kind="physical_robot",
            domain=Domain.PROJECT,
            origin="manual",
            name=TypeAdapter(RobotName).validate_python(project.name if name is None else name),
            attrs={
                "hardware_config_ref": None,
                "transport_refs": None,
                **visibility_attrs(in_graph=in_graph, onboarded_by=onboarded_by),
            },
        )
        self.session.add(root)
        await self.session.flush()
        return root

    async def _editable_root(
        self, project_id: uuid.UUID, entity_id: uuid.UUID, version: int
    ) -> GraphEntity:
        await self._lock_project(project_id)
        root = await self.session.scalar(
            select(GraphEntity)
            .where(
                GraphEntity.id == entity_id,
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            raise APIError(404, "not_found", "Entity not found")
        if root.kind != "physical_robot" or root.origin != "manual" or root.source_id is not None:
            raise APIError(409, "conflict", "Only manual Physical Robot roots can be changed here")
        if root.version != version:
            raise APIError(
                409,
                "conflict",
                "Robot changed; reload it before saving",
                details=[{"version": root.version, "name": root.name}],
            )
        return root

    async def rename(
        self, project_id: uuid.UUID, entity_id: uuid.UUID, version: int, name: str
    ) -> GraphEntity:
        root = await self._editable_root(project_id, entity_id, version)
        root.name = TypeAdapter(RobotName).validate_python(name)
        root.version += 1
        await self.session.flush()
        return root

    async def delete(
        self, project_id: uuid.UUID, entity_id: uuid.UUID, version: int
    ) -> RobotRemoval:
        root = await self._editable_root(project_id, entity_id, version)
        edges = list(
            await self.session.scalars(
                select(GraphEdge).where(ownership_edge(project_id), GraphEdge.src_id == root.id)
            )
        )
        retained = list(
            await self.session.scalars(
                select(GraphEntity.id)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_({edge.dst_id for edge in edges}),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.kind.not_in(("physical_robot", "robot_category")),
                )
                .order_by(GraphEntity.id)
            )
        )
        from solus_api.hardware.bindings import disable_part_bindings

        await disable_part_bindings(self.session, project_id, [], retired_owner_ids=[root.id])
        now = utcnow()
        root.deleted_at = now
        root.version += 1
        for edge in edges:
            edge.deleted_at = now
        await self.session.flush()
        return RobotRemoval(
            root=root,
            retained_part_ids=retained,
            counts=GraphChangeCounts(entities_deleted=1, relations_deleted=len(edges)),
        )
