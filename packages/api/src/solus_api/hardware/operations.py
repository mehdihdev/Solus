"""Atomic reviewed hardware creation and bounded, account-scoped replay."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.hardware.config import ConfigDraft, EntityHardwareConfig
from solus_api.hardware.ownership import assign_parent
from solus_api.hardware.store import put_entity_config
from solus_api.models import Domain, GraphEntity, HardwareOperation, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.physical_robots import PhysicalRobotService, RobotName
from solus_api.services.solus_graph import lock_project

Category = Literal[
    "sensors", "actuators", "controllers", "end_effectors", "power", "structure", "wiring"
]


class HardwareEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["robot", "part"]
    name: RobotName
    parent_id: uuid.UUID | None = None
    category: Category | None = None
    config: ConfigDraft | None = None

    @model_validator(mode="after")
    def _parent_shape(self) -> HardwareEntityCreate:
        if self.kind == "robot" and (self.parent_id is not None or self.category is not None):
            raise ValueError("A robot cannot have a hardware parent or category")
        return self


class ReviewedHardwareOperations:
    def __init__(self, session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.session, self.project_id, self.user_id = session, project_id, user_id

    async def replay(
        self, key: uuid.UUID, operation: str, payload: dict[str, Any]
    ) -> tuple[HardwareOperation | None, str]:
        await lock_project(self.session, self.project_id)
        now = utcnow()
        await self.session.execute(
            delete(HardwareOperation).where(
                HardwareOperation.project_id == self.project_id,
                HardwareOperation.user_id == self.user_id,
                HardwareOperation.expires_at <= now,
            )
        )
        digest = hashlib.sha256(
            json.dumps(
                {"operation": operation, "payload": payload},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        previous = await self.session.scalar(
            select(HardwareOperation).where(
                HardwareOperation.project_id == self.project_id,
                HardwareOperation.user_id == self.user_id,
                HardwareOperation.idempotency_key == key,
            )
        )
        if previous is not None and (
            previous.operation != operation or previous.payload_digest != digest
        ):
            raise APIError(
                409,
                "idempotency_conflict",
                "This operation key was already used for different reviewed changes",
            )
        return previous, digest

    def record(
        self, key: uuid.UUID, operation: str, digest: str, response: dict[str, Any]
    ) -> dict[str, Any]:
        encoded: dict[str, Any] = jsonable_encoder(response)
        if len(json.dumps(encoded, ensure_ascii=False).encode()) > 64 * 1024:
            raise APIError(422, "validation_error", "Hardware operation response exceeds its limit")
        now = utcnow()
        self.session.add(
            HardwareOperation(
                project_id=self.project_id,
                user_id=self.user_id,
                idempotency_key=key,
                operation=operation,
                payload_digest=digest,
                response=encoded,
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )
        )
        return encoded

    async def create(
        self, key: uuid.UUID, body: HardwareEntityCreate
    ) -> tuple[dict[str, Any], bool]:
        previous, digest = await self.replay(key, "entity.create", body.model_dump(mode="json"))
        if previous is not None:
            return dict(previous.response), True
        if body.kind == "robot":
            entity = await PhysicalRobotService(self.session).create(self.project_id, body.name)
        else:
            entity = GraphEntity(
                id=uuid7(),
                project_id=self.project_id,
                kind="part",
                name=body.name,
                domain=Domain.PROJECT,
                origin="manual",
                attrs={"category": body.category} if body.category else {},
            )
            self.session.add(entity)
            await self.session.flush()
        parent_id = None
        if body.parent_id is not None:
            entity, parent_id = await assign_parent(
                self.session,
                self.project_id,
                entity.id,
                parent_id=body.parent_id,
                expected_parent_id=None,
                version=entity.version,
                category=body.category,
            )
        entry = None
        if body.config is not None:
            config = EntityHardwareConfig.model_validate(
                {**body.config.model_dump(mode="json"), "entity_id": entity.id}
            )
            entry = await put_entity_config(
                self.session,
                self.project_id,
                entity,
                config,
                expected_version=0,
                created_by=self.user_id,
            )
        response = {
            "entity": serialize_entity(entity),
            "config_entry_id": entry.id if entry else None,
            "config_version": entry.config_version if entry else 0,
            "parent_id": parent_id,
            "ownership_version": entity.version,
        }
        return self.record(key, "entity.create", digest, response), False
