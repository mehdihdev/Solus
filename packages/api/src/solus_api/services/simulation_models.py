"""One reviewed SO101 graph template; no arbitrary graph or runtime execution."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.agent.tools.isaac_models import LIMITS, LINKS, SimulationModel
from solus_api.core.errors import APIError
from solus_api.models import Domain, GraphEdge, GraphEntity, Project

TEMPLATE = "so101_new_calib_v1"
REFERENCE = "solus:simulation:" + TEMPLATE
PROVENANCE = {
    "repository": "https://github.com/TheRobotStudio/SO-ARM100",
    "commit": "eecbe3e0a9ebb23e25ad7b2759b03884c6660903",
    "path": "Simulation/SO101/so101_new_calib.urdf",
    "license": "Apache-2.0",
    "asset_sha256": "a1be9138359e044a007a4981817f3a8783fca47985b424f3fa9ca3d02e12b5b9",
}
# Reviewed parent/child facts from the exact pinned official URDF above.
JOINT_LINKS = {
    "shoulder_pan": ("base_link", "shoulder_link"),
    "shoulder_lift": ("shoulder_link", "upper_arm_link"),
    "elbow_flex": ("upper_arm_link", "lower_arm_link"),
    "wrist_flex": ("lower_arm_link", "wrist_link"),
    "wrist_roll": ("wrist_link", "gripper_link"),
    "gripper": ("gripper_link", "moving_jaw_so101_v1_link"),
}


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    template: Literal["so101_new_calib_v1"]


def _conflict() -> APIError:
    return APIError(
        409,
        "simulation_model_conflict",
        "The existing simulation template is incomplete or changed; review its graph.",
    )


def _model(existing_ids: list[str] | None = None) -> SimulationModel:
    identities = iter(
        existing_ids if existing_ids is not None else [str(uuid7()) for _ in range(16)]
    )
    links = [{"entity_id": next(identities), "name": name} for name in LINKS]
    return SimulationModel.model_validate(
        {
            "schema_version": 1,
            "asset": TEMPLATE,
            "asset_sha256": PROVENANCE["asset_sha256"],
            "links": links,
            "joints": [{"entity_id": next(identities), "name": name} for name in LIMITS],
            "sensors": [
                {
                    "entity_id": next(identities),
                    "parent_link_entity_id": links[-1]["entity_id"],
                    "kind": "contact",
                    "translation_m": [0.0, 0.0, 0.0],
                    "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
                    "radius_m": 0.01,
                }
            ],
            "bottle": {
                "entity_id": next(identities),
                "translation_m": [0.25, 0.2, 0.075],
                "radius_m": 0.025,
                "height_m": 0.15,
                "mass_kg": 0.1,
            },
        }
    )


def _parts(model: SimulationModel) -> list[tuple[str, str, str]]:
    return (
        [(link.entity_id, "robot_link", link.name) for link in model.links]
        + [(joint.entity_id, "robot_joint", joint.name) for joint in model.joints]
        + [(sensor.entity_id, "sensor", "Jaw contact sensor") for sensor in model.sensors]
        + [(model.bottle.entity_id, "simulation_object", "Bottle")]
    )


def _relations(root: uuid.UUID, model: SimulationModel) -> set[tuple[uuid.UUID, uuid.UUID, str]]:
    links = {link.name: uuid.UUID(link.entity_id) for link in model.links}
    edges = {(root, uuid.UUID(identity), "contains") for identity in model.entity_ids()}
    for joint in model.joints:
        edges.update(
            (uuid.UUID(joint.entity_id), links[name], "connected_to")
            for name in JOINT_LINKS[joint.name]
        )
    edges.add((links["gripper_link"], links["gripper_frame_link"], "connected_to"))
    edges.update(
        (uuid.UUID(sensor.entity_id), uuid.UUID(sensor.parent_link_entity_id), "attached_to")
        for sensor in model.sensors
    )
    return edges


class SimulationModelService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, project_id: uuid.UUID) -> tuple[GraphEntity, SimulationModel, bool]:
        project = await self.session.scalar(
            select(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update()
        )
        if project is None:
            raise APIError(404, "not_found", "Project not found")
        existing = list(
            await self.session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.source_id.is_(None),
                    or_(
                        GraphEntity.external_ref == REFERENCE,
                        GraphEntity.kind == "simulation_model",
                    ),
                )
                .execution_options(populate_existing=True)
            )
        )
        if existing:
            if len(existing) != 1:
                raise _conflict()
            model = await self._validate(existing[0], project_id)
            return existing[0], model, False
        model = _model()
        root = GraphEntity(
            id=uuid7(),
            project_id=project_id,
            kind="simulation_model",
            domain=Domain.SIMULATION,
            origin="manual",
            external_ref=REFERENCE,
            name="SO-101 simulation model",
            attrs={
                "template": TEMPLATE,
                "provenance": PROVENANCE,
                "simulation_model": model.model_dump(),
            },
        )
        nodes = [
            GraphEntity(
                id=uuid.UUID(identity),
                project_id=project_id,
                kind=kind,
                domain=Domain.SIMULATION,
                origin="manual",
                name=name,
                attrs={"model_entity_id": str(root.id)},
            )
            for identity, kind, name in _parts(model)
        ]
        self.session.add_all([root, *nodes])
        await self.session.flush()
        self.session.add_all(
            [
                GraphEdge(
                    project_id=project_id,
                    src_id=src,
                    dst_id=dst,
                    relation_type=kind,
                    domain_pair="simulation<->simulation",
                    origin="manual",
                )
                for src, dst, kind in _relations(root.id, model)
            ]
        )
        await self.session.flush()
        return root, model, True

    async def _validate(self, root: GraphEntity, project_id: uuid.UUID) -> SimulationModel:
        try:
            model = SimulationModel.model_validate(root.attrs.get("simulation_model"))
        except (ValidationError, AttributeError):
            raise _conflict() from None
        if (
            root.deleted_at is not None
            or root.origin != "manual"
            or root.domain != Domain.SIMULATION
            or root.kind != "simulation_model"
            or root.external_ref != REFERENCE
            or root.name != "SO-101 simulation model"
            or root.attrs
            != {
                "template": TEMPLATE,
                "provenance": PROVENANCE,
                "simulation_model": _model(model.entity_ids()).model_dump(),
            }
            or str(root.id) in model.entity_ids()
        ):
            raise _conflict()
        ids = {uuid.UUID(identity) for identity in model.entity_ids()}
        rows = list(
            await self.session.scalars(
                select(GraphEntity)
                .where(GraphEntity.project_id == project_id, GraphEntity.id.in_(ids))
                .execution_options(populate_existing=True)
            )
        )
        expected = {uuid.UUID(identity): (kind, name) for identity, kind, name in _parts(model)}
        if {row.id for row in rows} != ids or any(
            row.deleted_at is not None
            or row.origin != "manual"
            or row.source_id is not None
            or row.domain != Domain.SIMULATION
            or (row.kind, row.name) != expected[row.id]
            or row.attrs != {"model_entity_id": str(root.id)}
            for row in rows
        ):
            raise _conflict()
        ids.add(root.id)
        edges = list(
            await self.session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.src_id.in_(ids),
                    GraphEdge.dst_id.in_(ids),
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        expected_edges = _relations(root.id, model)
        if (
            len(edges) != len(expected_edges)
            or {(edge.src_id, edge.dst_id, edge.relation_type) for edge in edges} != expected_edges
            or any(
                edge.origin != "manual"
                or edge.source_id is not None
                or edge.domain_pair != "simulation<->simulation"
                for edge in edges
            )
        ):
            raise _conflict()
        return model
