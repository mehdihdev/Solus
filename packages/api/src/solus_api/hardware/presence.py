"""Retained presence plans: preparation never opens hardware; execution is gated."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.topology import MARKER, read_topology
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, SolusSection, User
from solus_api.services.artifacts import create_artifact, fetch_artifact_bytes
from solus_api.services.events import emit_event
from solus_api.services.solus_config import add_artifact_entry
from solus_api.services.solus_graph import lock_project
from solus_api.storage import ArtifactStore

KIND = "hardware_presence_plan"


class PresenceRefusalError(ValueError):
    """Provider explicitly guarantees that upload has not started."""


class PreparePresence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: Literal["uno_avr", "nano_avr"]
    kind: Literal["heartbeat", "probe", "topology"]
    channel: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    wiring_proposal_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def topology_requires_review(self) -> PreparePresence:
        if (self.kind == "topology") != (self.wiring_proposal_id is not None):
            raise ValueError("Topology firmware requires an accepted wiring proposal")
        return self


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class PresenceService:
    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        store: ArtifactStore,
        provider: Any,
    ):
        self.session, self.project_id, self.user_id = session, project_id, user_id
        self.store, self.provider = store, provider

    def profiles(self) -> list[dict[str, Any]]:
        return self.provider.profiles() if self.provider else []

    async def binding(self, robot_id: uuid.UUID, brain_id: uuid.UUID) -> tuple[str, str]:
        topology = await read_topology(self.session, self.project_id, robot_id)
        config = await resolve_runtime_config(self.session, self.project_id, robot_id)
        if config.identity is None or config.identity.kind.value != "usb_serial":
            raise APIError(409, "presence_ineligible", "Select an accepted USB connection first")
        expected = uuid.uuid5(self.project_id, f"{MARKER}:endpoint:{config.identity.device_ref}")
        if brain_id != expected or not any(
            n.id == brain_id and n.role == "brain" for n in topology.nodes
        ):
            raise APIError(404, "not_found", "Presence target not found")
        if (
            config.bus_map
            or config.parts
            or (
                config.protocol
                and getattr(self.provider, "accepts_protocol", lambda _: False)(
                    config.protocol.driver_id
                )
                is not True
            )
        ):
            raise APIError(
                409,
                "presence_ineligible",
                "Configured driver boards cannot receive presence firmware",
            )
        return config.identity.binding, digest(config.model_dump(mode="json"))

    async def _wiring(
        self, robot_id: uuid.UUID, brain_id: uuid.UUID, body: PreparePresence
    ) -> tuple[list[dict[str, str]] | None, str | None]:
        if body.wiring_proposal_id is None:
            return None, None
        from solus_api.hardware.presence_topology import WiringService

        proposal = await WiringService(self).checked(
            robot_id, brain_id, body.wiring_proposal_id, accepted=True
        )
        if proposal.attrs["request"]["profile_id"] != body.profile_id:
            raise APIError(409, "wiring_changed", "Board profile changed; review wiring again")
        rows = proposal.attrs["request"]["wiring"]
        inputs = [{key: row[key] for key in ("channel", "pin", "kind")} for row in rows]
        return inputs, proposal.attrs["digest"]

    async def prepare(
        self, robot_id: uuid.UUID, brain_id: uuid.UUID, body: PreparePresence
    ) -> dict[str, Any]:
        if not self.provider:
            raise APIError(503, "presence_unavailable", "Local firmware compiler unavailable")
        binding, config_digest = await self.binding(robot_id, brain_id)
        wiring, wiring_digest = await self._wiring(robot_id, brain_id, body)
        try:
            args = (binding, body.profile_id, body.kind, body.channel)
            prepared = (
                await self.provider.prepare(*args, wiring)
                if wiring is not None
                else await self.provider.prepare(*args)
            )
        except (ValueError, RuntimeError):
            raise APIError(
                503,
                "presence_unavailable",
                "Firmware preparation unavailable; check the selected board and compiler",
            ) from None
        await lock_project(self.session, self.project_id)
        if await self.binding(robot_id, brain_id) != (binding, config_digest):
            raise APIError(409, "presence_changed", "Connection changed; prepare again")
        if await self._wiring(robot_id, brain_id, body) != (wiring, wiring_digest):
            raise APIError(409, "wiring_changed", "Wiring changed while compiling; prepare again")
        attrs: dict[str, Any] = {
            "created_by": str(self.user_id),
            "robot_id": str(robot_id),
            "brain_id": str(brain_id),
            "profile": body.profile_id,
            "kind": body.kind,
            "target": prepared["target"],
            "config_digest": config_digest,
            "status": "prepared",
            "wiring_proposal_id": str(body.wiring_proposal_id) if body.wiring_proposal_id else None,
            "wiring_digest": wiring_digest,
        }
        for key, media in [("source", "text/plain"), ("binary", "application/octet-stream")]:
            data = prepared[key]
            if not isinstance(data, bytes) or not 0 < len(data) <= 100000:
                raise APIError(503, "presence_unavailable", "Invalid compiler artifact")
            actual = hashlib.sha256(data).hexdigest()
            if actual != prepared[key + "_sha256"]:
                raise APIError(503, "presence_unavailable", "Compiler artifact digest mismatch")
            artifact = await create_artifact(
                self.session,
                self.store,
                project_id=self.project_id,
                created_by=self.user_id,
                data=data,
                media_type=media,
                source_tool="hardware.presence.prepare",
                tool_call_id=None,
            )
            await add_artifact_entry(
                self.session,
                self.project_id,
                SolusSection.DOCS,
                artifact_id=artifact.id,
                name=f"Presence {key}",
                created_by=self.user_id,
            )
            attrs[key + "_artifact_id"], attrs[key + "_sha256"] = str(artifact.id), actual
        entity = GraphEntity(
            project_id=self.project_id,
            kind=KIND,
            origin="system",
            domain=Domain.RUNTIME,
            name="Prepared presence firmware",
            attrs=attrs,
        )
        self.session.add(entity)
        await self.session.flush()
        for target in (robot_id, brain_id):
            self.session.add(
                GraphEdge(
                    project_id=self.project_id,
                    src_id=entity.id,
                    dst_id=target,
                    relation_type="presence_prepared_for",
                    domain_pair="runtime:runtime",
                    origin="system",
                    attrs={},
                )
            )
        await self.session.flush()
        return {
            "plan_id": str(entity.id),
            "source": prepared["source"].decode("utf-8"),
            **{
                k: attrs[k]
                for k in ("source_sha256", "binary_sha256", "target", "profile", "status")
            },
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
            raise APIError(404, "not_found", "Presence plan not found")
        return entity

    async def checked(self, plan_id: uuid.UUID) -> tuple[GraphEntity, bytes, bytes]:
        if not self.provider:
            raise APIError(503, "presence_unavailable", "Local firmware provider unavailable")
        entity = await self.plan(plan_id)
        attrs = entity.attrs
        if attrs["status"] != "prepared":
            raise APIError(
                409, "presence_changed", "This plan has already been attempted; prepare a new plan"
            )
        binding, current = await self.binding(
            uuid.UUID(attrs["robot_id"]), uuid.UUID(attrs["brain_id"])
        )
        if current != attrs["config_digest"] or binding != attrs["target"]["binding"]:
            raise APIError(
                409, "presence_changed", "Connection configuration changed; prepare again"
            )
        await self._check_plan_wiring(attrs)
        try:
            await asyncio.to_thread(self.provider.validate, attrs["target"], attrs["profile"])
        except ValueError:
            raise APIError(409, "presence_changed", "USB identity changed; prepare again") from None
        content = []
        for key in ("source", "binary"):
            _, data = await fetch_artifact_bytes(
                self.session,
                self.store,
                project_id=self.project_id,
                artifact_id=uuid.UUID(attrs[key + "_artifact_id"]),
                requester_id=self.user_id,
                ttl_seconds=3600,
                max_bytes=100000,
            )
            if hashlib.sha256(data).hexdigest() != attrs[key + "_sha256"]:
                raise APIError(409, "presence_changed", "Firmware artifact changed; prepare again")
            content.append(data)
        return entity, content[0], content[1]

    async def _check_plan_wiring(self, attrs: dict[str, Any]) -> None:
        if attrs.get("wiring_proposal_id"):
            from solus_api.hardware.presence_topology import WiringService

            proposal = await WiringService(self).checked(
                uuid.UUID(attrs["robot_id"]),
                uuid.UUID(attrs["brain_id"]),
                uuid.UUID(attrs["wiring_proposal_id"]),
                accepted=True,
            )
            if proposal.attrs["digest"] != attrs["wiring_digest"]:
                raise APIError(409, "wiring_changed", "Accepted wiring changed; prepare again")

    async def preview(self, plan_id: uuid.UUID) -> list[dict[str, Any]]:
        entity, source, _ = await self.checked(plan_id)
        a = entity.attrs
        text = source.decode("utf-8")
        chunks = [text[index : index + 500] for index in range(0, len(text), 500)]
        if len(chunks) > 46:
            raise APIError(
                409, "presence_preview_too_large", "Firmware exceeds complete preview limits"
            )
        return [
            {
                "label": "Erase warning",
                "before": "Existing firmware",
                "after": (
                    "Existing firmware will be erased and replaced. "
                    "A linked repository may contain the existing sketch. "
                    "Driver boards are forbidden."
                ),
            },
            {"label": "Target", "before": None, "after": json.dumps(a["target"], sort_keys=True)},
            {"label": "Profile", "before": None, "after": a["profile"]},
            {"label": "Firmware SHA256", "before": None, "after": a["binary_sha256"]},
            *[
                {
                    "label": f"Complete firmware source {index + 1}/{len(chunks)}",
                    "before": None,
                    "after": chunk,
                }
                for index, chunk in enumerate(chunks)
            ],
        ]

    async def record_outcome(
        self,
        plan_id: uuid.UUID,
        attrs: dict[str, Any],
        status: str,
        *,
        event_type: str = "hardware.presence_outcome",
    ) -> None:
        user = await self.session.scalar(
            select(User).where(User.id == self.user_id).execution_options(populate_existing=True)
        )
        team_id = await self.session.scalar(
            select(Project.team_id).where(Project.id == self.project_id)
        )
        if user is None or team_id is None:
            raise APIError(404, "not_found", "Presence scope not found")
        emit_event(
            self.session,
            user=user,
            event_type=event_type,
            team_id=team_id,
            project_id=self.project_id,
            payload={
                "plan_id": str(plan_id),
                "status": status,
                **{
                    key: attrs[key]
                    for key in ("robot_id", "brain_id", "source_sha256", "binary_sha256")
                },
            },
        )

    async def execute(self, plan_id: uuid.UUID) -> dict[str, Any]:
        await lock_project(self.session, self.project_id)
        entity, _, binary = await self.checked(plan_id)
        attrs = dict(entity.attrs)
        # Persist uncertainty BEFORE entering an irreversible operation. A process
        # crash or cancellation can never leave an automatically retryable plan.
        entity.attrs = {**attrs, "status": "unknown"}
        await self.record_outcome(plan_id, attrs, "unknown", event_type="hardware.presence_attempt")
        await self.session.commit()
        try:
            # Reacquire the project lock after the durable uncertainty checkpoint.
            # CONFIG edits cannot race the irreversible upload after this recheck.
            await lock_project(self.session, self.project_id)
            binding, current = await self.binding(
                uuid.UUID(attrs["robot_id"]), uuid.UUID(attrs["brain_id"])
            )
            if current != attrs["config_digest"] or binding != attrs["target"]["binding"]:
                raise PresenceRefusalError("Connection changed before upload")
            try:
                await self._check_plan_wiring(attrs)
            except APIError as exc:
                raise PresenceRefusalError("Wiring changed before upload") from exc
            await self.provider.upload(attrs["target"], attrs["profile"], binary)
        except PresenceRefusalError:
            entity.attrs = {**attrs, "status": "prepared"}
            await self.record_outcome(plan_id, attrs, "unchanged")
            await self.session.commit()
            raise APIError(
                409,
                "presence_in_use",
                "Upload refused before writing; verify identity and stop existing sessions",
            ) from None
        except (Exception, asyncio.CancelledError):
            # Unknown was durably committed; never claim success or resume.
            await self.record_outcome(plan_id, attrs, "unknown")
            await self.session.commit()
            raise APIError(
                409,
                "presence_unknown",
                (
                    "Upload interrupted; firmware state unknown. "
                    "Inspect the board before preparing again"
                ),
            ) from None
        entity.attrs = {**attrs, "status": "flashed"}
        await self.record_outcome(plan_id, attrs, "flashed")
        await self.session.commit()
        return {
            "plan_id": str(plan_id),
            "status": "flashed",
            "binary_sha256": attrs["binary_sha256"],
        }
