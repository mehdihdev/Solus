"""Create generic simulation definitions over existing project graph entities."""

import hashlib
import json
import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.agent.tools.isaac_models import SimulationModel
from solus_api.core.errors import APIError
from solus_api.graph.read_scope import current_scope
from solus_api.models import Domain, GraphEdge, GraphEntity, Project


class SimulationModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Annotated[str, Field(min_length=1, max_length=120)]
    model: SimulationModel

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model name must not be blank")
        return value


def _conflict() -> APIError:
    return APIError(
        409,
        "simulation_model_conflict",
        "The existing simulation definition or its bindings changed; review its graph.",
    )


def _reference(body: SimulationModelCreate) -> str:
    canonical = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
    return "solus:simulation:v2:" + hashlib.sha256(canonical.encode()).hexdigest()


class SimulationModelService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, project_id: uuid.UUID, body: SimulationModelCreate
    ) -> tuple[GraphEntity, SimulationModel, bool]:
        # Serialize duplicate requests within the existing project transaction.
        project = await self.session.scalar(
            select(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update()
        )
        if project is None:
            raise APIError(404, "not_found", "Project not found")
        reference = _reference(body)
        existing = list(
            await self.session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.source_id.is_(None),
                    GraphEntity.external_ref == reference,
                )
                .execution_options(populate_existing=True)
            )
        )
        if existing:
            if len(existing) != 1:
                raise _conflict()
            await self._validate(existing[0], project_id, body)
            return existing[0], body.model, False
        components = await self._components(project_id, body.model)
        root = GraphEntity(
            id=uuid7(),
            project_id=project_id,
            kind="simulation_model",
            domain=Domain.SIMULATION,
            origin="manual",
            external_ref=reference,
            name=body.name,
            attrs={"simulation_model": body.model.model_dump()},
        )
        self.session.add(root)
        await self.session.flush()
        self.session.add_all(
            [
                GraphEdge(
                    project_id=project_id,
                    src_id=root.id,
                    dst_id=component.id,
                    relation_type="contains",
                    domain_pair=f"simulation<->{component.domain.value}",
                    origin="manual",
                )
                for component in components
            ]
        )
        await self.session.flush()
        return root, body.model, True

    async def _components(self, project_id: uuid.UUID, model: SimulationModel) -> list[GraphEntity]:
        ids = {uuid.UUID(identity) for identity in model.entity_ids()}
        rows = list(
            await self.session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(ids),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.domain != Domain.WORKSPACE,
                    current_scope(project_id).entity_predicate(),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if {row.id for row in rows} != ids:
            raise APIError(404, "not_found", "A simulation binding is unavailable in this project.")
        return rows

    async def _validate(
        self, root: GraphEntity, project_id: uuid.UUID, body: SimulationModelCreate
    ) -> None:
        if (
            root.deleted_at is not None
            or root.origin != "manual"
            or root.domain != Domain.SIMULATION
            or root.kind != "simulation_model"
            or root.name != body.name
            or root.attrs != {"simulation_model": body.model.model_dump()}
            or str(root.id) in body.model.entity_ids()
        ):
            raise _conflict()
        components = await self._components(project_id, body.model)
        edges = list(
            await self.session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.src_id == root.id,
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        expected = {row.id: f"simulation<->{row.domain.value}" for row in components}
        if len(edges) != len(expected) or {edge.dst_id for edge in edges} != set(expected):
            raise _conflict()
        if any(
            edge.relation_type != "contains"
            or edge.origin != "manual"
            or edge.source_id is not None
            or edge.domain_pair != expected[edge.dst_id]
            for edge in edges
        ):
            raise _conflict()
