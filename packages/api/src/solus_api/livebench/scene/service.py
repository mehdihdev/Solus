"""Project-scoped retained model graph records and optimistic mapping review."""

import asyncio
import hashlib
import json
import uuid
from typing import Any

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import resolve_scope
from solus_api.hardware.config import part_ref
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, SolusSection
from solus_api.services.artifacts import fetch_artifact_bytes
from solus_api.services.solus_config import add_artifact_entry
from solus_api.storage import ArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .meshes import MAX_BYTES
from .parser import parse_model
from .schemas import ImportModel, Mapping

KIND = "bench_scene_model"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class SceneService:
    def __init__(self, session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID):
        self.session, self.project_id, self.user_id = session, project_id, user_id

    async def entity(self, identity: uuid.UUID, kind: str | None = None) -> GraphEntity:
        scope = await resolve_scope(self.session, self.project_id, self.user_id)
        entity = await self.session.scalar(
            select(GraphEntity)
            .where(
                GraphEntity.id == identity,
                scope.entity_predicate(),
                GraphEntity.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if entity is None or (kind and entity.kind != kind):
            raise APIError(404, "not_found", "Scene resource not found")
        if kind in (KIND, "physical_robot", "bench_scene_cad_import") and (
            entity.origin != "manual" or entity.source_id is not None
        ):
            raise APIError(404, "not_found", "Scene resource not found")
        return entity

    async def lock(self) -> None:
        await self.session.scalar(
            select(Project).where(Project.id == self.project_id).with_for_update()
        )

    async def all(self) -> list[GraphEntity]:
        return list(
            await self.session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == self.project_id,
                    GraphEntity.kind == KIND,
                    GraphEntity.deleted_at.is_(None),
                )
                .order_by(GraphEntity.id)
                .limit(32)
            )
        )

    async def config_digest(self, robot_id: uuid.UUID) -> str:
        config = await resolve_runtime_config(self.session, self.project_id, robot_id)
        return digest(config.model_dump(mode="json"))

    async def output(self, entity: GraphEntity) -> dict[str, Any]:
        attrs = dict(entity.attrs)
        try:
            robot = await self.entity(uuid.UUID(attrs["robot_id"]), "physical_robot")
            current = attrs.get("config_digest") in (None, await self.config_digest(robot.id))
            source_id = attrs.get("source_entity_id")
            if source_id:
                source = await self.entity(uuid.UUID(source_id))
                current = current and attrs.get("source_digest") == digest(
                    [source.version, source.attrs]
                )
        except (APIError, ValueError, KeyError):
            current = False
        from .cad_refresh import output_status

        refresh_status = await output_status(self, attrs)
        return {
            "cad_bindings": attrs.get("cad_bindings", []),
            "refresh_status": refresh_status,
            "refresh_error": attrs.get("refresh_error"),
            "id": str(entity.id),
            "name": entity.name,
            "version": entity.version,
            **{
                key: attrs.get(key)
                for key in (
                    "robot_id",
                    "artifact_id",
                    "source_entity_id",
                    "source_revision",
                    "model",
                )
            },
            "source_current": current,
            "bindings": attrs.get("bindings", []) if current else [],
        }

    async def import_model(
        self,
        body: ImportModel,
        store: ArtifactStore,
        ttl: int,
        identity: uuid.UUID | None = None,
        expected_version: int | None = None,
    ) -> GraphEntity:
        # Read via the same access/TTL guard as artifact GET. No private paths accepted.
        _, content = await fetch_artifact_bytes(
            self.session,
            store,
            project_id=self.project_id,
            artifact_id=body.artifact_id,
            requester_id=self.user_id,
            ttl_seconds=ttl,
            max_bytes=1024 * 1024,
        )
        mesh_bytes = await self.read_meshes(body, store, ttl, len(content))
        try:
            normalized = await asyncio.to_thread(parse_model, content, body.format, mesh_bytes)
        except (ValueError, OverflowError):
            raise APIError(
                422, "invalid_model", "Model XML is invalid, unsupported or exceeds scene limits."
            ) from None
        await self.lock()
        robot = await self.entity(body.robot_id, "physical_robot")
        source = await self.entity(body.source_entity_id) if body.source_entity_id else None
        existing = await self.entity(identity, KIND) if identity else None
        if existing and existing.version != expected_version:
            raise APIError(409, "version_conflict", "Model changed; reload before replacing it.")
        if existing is None and len(await self.all()) >= 32:
            raise APIError(409, "scene_full", "The scene supports at most 32 models.")
        entry = await add_artifact_entry(
            self.session,
            self.project_id,
            SolusSection.DOCS,
            artifact_id=body.artifact_id,
            name=body.name,
            created_by=self.user_id,
        )
        mesh_entries = [
            await add_artifact_entry(
                self.session,
                self.project_id,
                SolusSection.DOCS,
                artifact_id=mesh.artifact_id,
                name=f"{body.name} mesh {index + 1}",
                created_by=self.user_id,
            )
            for index, mesh in enumerate(body.meshes)
        ]
        attrs: dict[str, Any] = {
            "robot_id": str(robot.id),
            "artifact_id": str(body.artifact_id),
            "source_entity_id": str(source.id) if source else None,
            "source_revision": body.source_revision,
            "source_digest": digest([source.version, source.attrs]) if source else None,
            "model": normalized,
            "bindings": [],
            "config_digest": None,
        }
        if existing:
            old = existing.attrs
            if (
                old.get("robot_id") == attrs["robot_id"]
                and old.get("source_digest") == attrs["source_digest"]
                and old.get("source_revision") == attrs["source_revision"]
                and old.get("model", {}).get("joints") == normalized["joints"]
            ):
                attrs["bindings"] = old.get("bindings", [])
                attrs["config_digest"] = old.get("config_digest")
            existing.name, existing.attrs, existing.version = body.name, attrs, existing.version + 1
            entity = existing
            edges = await self.session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == self.project_id,
                    GraphEdge.src_id == entity.id,
                    GraphEdge.origin == "manual",
                    GraphEdge.deleted_at.is_(None),
                )
            )
            for edge in edges:
                await self.session.delete(edge)
        else:
            entity = GraphEntity(
                project_id=self.project_id,
                kind=KIND,
                domain=Domain.SIMULATION,
                origin="manual",
                name=body.name,
                attrs=attrs,
            )
            self.session.add(entity)
        await self.session.flush()
        targets = {
            robot.id,
            entry.entity_id,
            *(mesh_entry.entity_id for mesh_entry in mesh_entries),
        }
        if source:
            targets.add(source.id)
        self.session.add_all(
            [
                GraphEdge(
                    project_id=self.project_id,
                    src_id=entity.id,
                    dst_id=target,
                    relation_type="references",
                    domain_pair="simulation<->project",
                    origin="manual",
                )
                for target in targets
            ]
        )
        await self.session.flush()
        return entity

    async def mapping(self, identity: uuid.UUID, body: Mapping) -> GraphEntity:
        await self.lock()
        entity = await self.entity(identity, KIND)
        if entity.version != body.expected_version:
            raise APIError(409, "version_conflict", "Model changed; reload before mapping.")
        attrs = dict(entity.attrs)
        robot = await self.entity(uuid.UUID(attrs["robot_id"]), "physical_robot")
        # A changed source needs reimport, not a mapping confirmation over stale geometry.
        source_id = attrs.get("source_entity_id")
        if source_id:
            source = await self.entity(uuid.UUID(source_id))
            if attrs.get("source_digest") != digest([source.version, source.attrs]):
                raise APIError(409, "source_changed", "Reimport the changed source before mapping.")
        config = await resolve_runtime_config(self.session, self.project_id, robot.id)
        accepted = {
            str(item.part_entity_id): part_ref(config.identity.device_ref, item.address)
            for item in config.bus_map
            if item.part_entity_id and config.identity
        }
        joints = {item["name"]: item for item in attrs["model"]["joints"]}
        used_joints: set[str] = set()
        used_signals: set[tuple[uuid.UUID, str]] = set()
        for binding in body.bindings:
            await self.entity(binding.part_entity_id)
            item = joints.get(binding.joint)
            key = (binding.part_entity_id, binding.signal)
            if (
                not item
                or item["type"] == "fixed"
                or binding.joint in used_joints
                or key in used_signals
                or accepted.get(str(binding.part_entity_id)) != binding.device_id
            ):
                raise APIError(
                    422,
                    "invalid_mapping",
                    "Choose unique movable joints and accepted robot device mappings.",
                )
            if (item["type"] == "prismatic") != (binding.unit == "m"):
                raise APIError(
                    422, "invalid_mapping", "Joint and telemetry dimensions are incompatible."
                )
            used_joints.add(binding.joint)
            used_signals.add(key)
        attrs["bindings"] = [binding.model_dump(mode="json") for binding in body.bindings]
        attrs["config_digest"] = digest(config.model_dump(mode="json"))
        entity.attrs, entity.version = attrs, entity.version + 1
        await self.session.flush()
        return entity

    async def read_meshes(
        self, body: ImportModel, store: ArtifactStore, ttl: int, total: int
    ) -> dict[str, bytes]:
        mesh_bytes: dict[str, bytes] = {}
        for mesh in body.meshes:
            if mesh.reference in mesh_bytes:
                raise APIError(422, "invalid_model", "Mesh references must be unique.")
            _, data = await fetch_artifact_bytes(
                self.session,
                store,
                project_id=self.project_id,
                artifact_id=mesh.artifact_id,
                requester_id=self.user_id,
                ttl_seconds=ttl,
                max_bytes=max(0, MAX_BYTES - total),
            )
            total += len(data)
            if total > MAX_BYTES:
                raise APIError(422, "invalid_model", "Model and mesh files exceed 8 MiB.")
            mesh_bytes[mesh.reference] = data
        return mesh_bytes
