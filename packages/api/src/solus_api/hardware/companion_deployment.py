"""Retained, scoped plans for an explicitly installed local deployment provider."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.bridge.registry import BridgeSessionRegistry
from solus_api.core.errors import APIError
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, User
from solus_api.services.artifacts import fetch_artifact_bytes
from solus_api.services.events import emit_event
from solus_api.services.solus_graph import lock_project
from solus_api.storage import ArtifactStore

KIND = "companionDeploymentPlan"
MAX_BUNDLE_BYTES = 32 * 1024 * 1024


class PrepareCompanionDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: uuid.UUID
    artifact_id: uuid.UUID


class DeploymentTargetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: uuid.UUID
    version: int = Field(ge=1)
    host: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    user: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    companion_instance_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    host_keys_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeploymentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["succeeded", "failed", "refused"]
    remote_state: Literal["unchanged", "running", "rolled_back", "unknown"]
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z_]+$")


class DeploymentProvider(Protocol):
    project_id: uuid.UUID
    user_id: uuid.UUID

    async def resolve_target(self, target_id: uuid.UUID) -> DeploymentTargetSnapshot: ...
    def bundle_allowed(self, artifact_id: uuid.UUID, sha256: str) -> bool: ...
    async def validate(self, target: DeploymentTargetSnapshot) -> bool: ...
    async def execute(
        self,
        plan_id: uuid.UUID,
        artifact_id: uuid.UUID,
        target: DeploymentTargetSnapshot,
        bundle: bytes,
        sha256: str,
    ) -> DeploymentOutcome: ...


class CompanionDeploymentService:
    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        store: ArtifactStore,
        provider: DeploymentProvider,
    ):
        if (provider.project_id, provider.user_id) != (project_id, user_id):
            raise APIError(503, "companion_deployment_unavailable", "Local deployment unavailable")
        self.session, self.project_id, self.user_id = session, project_id, user_id
        self.store, self.provider = store, provider

    async def _target(self, target_id: uuid.UUID) -> DeploymentTargetSnapshot:
        exists = await self.session.scalar(
            select(GraphEntity.id).where(
                GraphEntity.id == target_id,
                GraphEntity.project_id == self.project_id,
                GraphEntity.deleted_at.is_(None),
            )
        )
        if exists is None:
            raise APIError(404, "not_found", "Deployment target not found")
        try:
            target = DeploymentTargetSnapshot.model_validate(
                await self.provider.resolve_target(target_id)
            )
            if target.id != target_id or not await self.provider.validate(target):
                raise ValueError()
            return target
        except (ValueError, LookupError):
            raise APIError(409, "deployment_changed", "Target enrollment changed") from None

    async def _bundle(self, artifact_id: uuid.UUID) -> tuple[bytes, str]:
        artifact, bundle = await fetch_artifact_bytes(
            self.session,
            self.store,
            project_id=self.project_id,
            artifact_id=artifact_id,
            requester_id=self.user_id,
            ttl_seconds=3600,
            max_bytes=MAX_BUNDLE_BYTES,
        )
        sha256 = hashlib.sha256(bundle).hexdigest()
        if (
            not artifact.retained
            or artifact.created_by != self.user_id
            or not bundle
            or not self.provider.bundle_allowed(artifact_id, sha256)
        ):
            raise APIError(409, "deployment_changed", "Retained bundle is not operator-authorized")
        return bundle, sha256

    async def prepare(self, body: PrepareCompanionDeployment) -> dict[str, Any]:
        await lock_project(self.session, self.project_id)
        target = await self._target(body.target_id)
        _, sha256 = await self._bundle(body.artifact_id)
        entity = GraphEntity(
            project_id=self.project_id,
            kind=KIND,
            origin="system",
            domain=Domain.RUNTIME,
            name="Prepared onboard companion deployment",
            attrs={
                "created_by": str(self.user_id),
                "target_id": str(body.target_id),
                "artifact_id": str(body.artifact_id),
                "artifact_sha256": sha256,
                "target": target.model_dump(mode="json"),
                "status": "prepared",
            },
        )
        self.session.add(entity)
        await self.session.flush()
        self.session.add(
            GraphEdge(
                project_id=self.project_id,
                src_id=entity.id,
                dst_id=body.target_id,
                relation_type="deployment_for_target",
                domain_pair="runtime:runtime",
                origin="system",
                attrs={},
            )
        )
        await self._event(entity, "prepared")
        await self.session.flush()
        return {
            "plan_id": str(entity.id),
            "target_id": str(body.target_id),
            "artifact_id": str(body.artifact_id),
            "artifact_sha256": sha256,
            "target_version": target.version,
            "status": "prepared",
        }

    async def plan(self, plan_id: uuid.UUID) -> GraphEntity:
        entity = await self.session.scalar(
            select(GraphEntity)
            .where(
                GraphEntity.id == plan_id,
                GraphEntity.project_id == self.project_id,
                GraphEntity.kind == KIND,
                GraphEntity.origin == "system",
                GraphEntity.source_id.is_(None),
                GraphEntity.deleted_at.is_(None),
                GraphEntity.attrs["created_by"].astext == str(self.user_id),
            )
            .execution_options(populate_existing=True)
        )
        if entity is None:
            raise APIError(404, "not_found", "Deployment plan not found")
        return entity

    async def checked(
        self, plan_id: uuid.UUID
    ) -> tuple[GraphEntity, DeploymentTargetSnapshot, bytes]:
        entity = await self.plan(plan_id)
        if entity.attrs["status"] != "prepared":
            raise APIError(409, "deployment_changed", "Deployment has already been attempted")
        target = await self._target(uuid.UUID(entity.attrs["target_id"]))
        bundle, sha256 = await self._bundle(uuid.UUID(entity.attrs["artifact_id"]))
        if (
            target.model_dump(mode="json") != entity.attrs["target"]
            or sha256 != entity.attrs["artifact_sha256"]
        ):
            raise APIError(409, "deployment_changed", "Deployment target or bundle changed")
        return entity, target, bundle

    async def preview(self, plan_id: uuid.UUID) -> list[dict[str, Any]]:
        entity, target, _ = await self.checked(plan_id)
        return [
            {"label": key, "before": None, "after": str(value)}
            for key, value in (
                ("Target", f"{target.user}@{target.host}"),
                ("Companion instance", target.companion_instance_id),
                ("Target version", target.version),
                ("SSH host-key authority SHA256", target.host_keys_sha256),
                ("Bundle SHA256", entity.attrs["artifact_sha256"]),
                (
                    "Prerequisites",
                    "Pre-enrolled active service and trusted deploy helper; no bootstrap",
                ),
                (
                    "Operation",
                    "Install offline bundle, restart, verify fresh authenticated handshake; "
                    "rollback on failure. Unknown restoration retains recovery journal.",
                ),
            )
        ]

    async def _event(self, entity: GraphEntity, status: str) -> None:
        user = await self.session.get(User, self.user_id)
        team_id = await self.session.scalar(
            select(Project.team_id).where(Project.id == self.project_id)
        )
        if user is not None and team_id is not None:
            emit_event(
                self.session,
                user=user,
                team_id=team_id,
                project_id=self.project_id,
                event_type="hardware.companion_deployment",
                payload={
                    "plan_id": str(entity.id),
                    "target_id": entity.attrs["target_id"],
                    "artifact_id": entity.attrs["artifact_id"],
                    "artifact_sha256": entity.attrs["artifact_sha256"],
                    "status": status,
                },
            )

    async def execute(self, plan_id: uuid.UUID) -> dict[str, Any]:
        """Registered central tool invoke only; no HTTP write/approval flag endpoint."""
        await lock_project(self.session, self.project_id)
        entity, target, bundle = await self.checked(plan_id)
        attrs = dict(entity.attrs)
        entity.attrs = {**attrs, "status": "unknown"}
        await self._event(entity, "unknown")
        await self.session.commit()
        try:
            await lock_project(self.session, self.project_id)
            if await self._target(target.id) != target:
                raise ValueError()
            latest, sha256 = await self._bundle(uuid.UUID(attrs["artifact_id"]))
            if latest != bundle or sha256 != attrs["artifact_sha256"]:
                raise ValueError()
            outcome = DeploymentOutcome.model_validate(
                await self.provider.execute(
                    plan_id, uuid.UUID(attrs["artifact_id"]), target, bundle, sha256
                )
            )
            if outcome.artifact_sha256 != sha256:
                raise ValueError()
        except (Exception, asyncio.CancelledError):
            await self.session.rollback()
            raise APIError(
                409, "deployment_unknown", "Deployment interrupted; inspect retained plan"
            ) from None
        entity = await self.plan(plan_id)
        entity.attrs = {**attrs, "status": outcome.status, "outcome": outcome.model_dump()}
        await self._event(entity, outcome.status)
        await self.session.commit()
        return {"plan_id": str(plan_id), **outcome.model_dump()}


def get_companion_deployment_service(
    request: Request, session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> CompanionDeploymentService:
    factory = getattr(request.app.state, "companion_deployment_service_factory", None)
    if factory is None:
        raise APIError(503, "companion_deployment_unavailable", "Local deployment unavailable")
    service = factory(session, project_id, user_id, request.app.state.artifact_store)
    if not isinstance(service, CompanionDeploymentService) or (
        service.project_id,
        service.user_id,
    ) != (project_id, user_id):
        raise APIError(503, "companion_deployment_unavailable", "Local deployment unavailable")
    return service


class FreshCompanionHandshake:
    """Capture BEFORE restart. SSH verifies bytes; bridge verifies a fresh connection."""

    def __init__(
        self,
        registry: BridgeSessionRegistry,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        team_id: uuid.UUID,
        expected_sha256: str,
        timeout_seconds: float = 25,
    ):
        self.registry, self.scope = registry, (user_id, team_id, project_id)
        old = registry.get(*self.scope)
        self.previous = old.session_id if old else None
        self.started = datetime.now(UTC)
        self.expected_sha256, self.timeout = expected_sha256, timeout_seconds

    async def __call__(self, instance_id: str, sha256: str) -> bool:
        if sha256 != self.expected_sha256:
            return False
        deadline = asyncio.get_running_loop().time() + self.timeout
        while asyncio.get_running_loop().time() < deadline:
            current = self.registry.get(*self.scope)
            now = datetime.now(UTC)
            if (
                current is not None
                and current.scope == self.scope
                and current.may_write
                and current.session_id != self.previous
                and current.connected_at >= self.started
                and current.token_exp > now
                and current.companion_instance_id == instance_id
            ):
                return True
            await asyncio.sleep(min(0.1, self.timeout))
        return False
