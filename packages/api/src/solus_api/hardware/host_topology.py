"""Reviewed local host attachment using scoped source, bridge and physical evidence."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
import uuid
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.bridge.registry import BridgeSessionRegistry
from solus_api.core.errors import APIError
from solus_api.hardware.operations import ReviewedHardwareOperations
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import read_entity_config, robot_root
from solus_api.hardware.topology import (
    HOST_MARKER,
    MEMBERSHIP,
    RELATION,
    Evidence,
    RobotTopology,
    TopologyEdge,
    TopologyNode,
    read_topology,
)
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Source,
    SourceStatus,
    SourceType,
    utcnow,
)


class HostAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_id: uuid.UUID
    machine_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    local_source_id: uuid.UUID
    software_entity_id: uuid.UUID | None = None
    endpoint_brain_kind: Literal["mcu"] | None = None


class HostConfirm(HostAttachment):
    proposal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class HostProposal(HostAttachment):
    proposal_digest: str
    host_name: str
    topology: RobotTopology
    notes: list[str] = Field(max_length=8)


class HostProposalEnvelope(BaseModel):
    data: HostProposal


class LocalHostProvider:
    def __init__(self, local: Any) -> None:
        self.local = local

    async def identity(self) -> str | None:
        if self.local is None:
            return None
        try:
            module = importlib.import_module("livebench.hardware.host_identity")
        except ImportError:
            return None
        value: str | None = await asyncio.to_thread(module.read_host_identity)
        return value

    async def devices(self) -> list[dict[str, Any]]:
        from solus_api.hardware.detect import detected_devices_wire

        if self.local is None:
            return []
        return detected_devices_wire(await asyncio.to_thread(self.local.detect_devices))


def host_provider(request: Request) -> LocalHostProvider:
    return LocalHostProvider(request.app.state.bench_local)


class HostTopologyService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        sessions: BridgeSessionRegistry,
        provider: LocalHostProvider,
    ) -> None:
        self.session, self.project_id, self.team_id, self.user_id = (
            session,
            project_id,
            team_id,
            user_id,
        )
        self.sessions, self.provider = sessions, provider

    async def _source(
        self, body: HostAttachment, *, lock: bool = False
    ) -> tuple[Source, GraphEntity, GraphEntity | None]:
        source_query = (
            select(Source)
            .where(
                Source.id == body.local_source_id,
                Source.project_id == self.project_id,
                Source.team_id == self.team_id,
                Source.type == SourceType.LOCAL,
                Source.created_by == self.user_id,
                Source.status == SourceStatus.CONNECTED,
            )
            .execution_options(populate_existing=True)
        )
        source = await self.session.scalar(source_query.with_for_update() if lock else source_query)
        if (
            source is None
            or source.config.get("machine_id") != body.machine_id
            or source.config.get("user_id") != str(self.user_id)
        ):
            raise APIError(404, "not_found", "Authorized local source was not found")
        clone_query = (
            select(GraphEntity)
            .where(
                GraphEntity.project_id == self.project_id,
                GraphEntity.source_id == source.id,
                GraphEntity.external_ref == "clone:",
                GraphEntity.kind.in_(("local_clone", "local_folder")),
                GraphEntity.origin == "connector",
                GraphEntity.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        clone = await self.session.scalar(clone_query.with_for_update() if lock else clone_query)
        if clone is None:
            raise APIError(409, "proposal_changed", "The local folder graph is unavailable")
        software = None
        if body.software_entity_id is not None:
            software_query = (
                select(GraphEntity)
                .where(
                    GraphEntity.id == body.software_entity_id,
                    GraphEntity.project_id == self.project_id,
                    GraphEntity.source_id == source.id,
                    GraphEntity.domain == Domain.CODE,
                    GraphEntity.origin == "connector",
                    GraphEntity.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
            software = await self.session.scalar(
                software_query.with_for_update() if lock else software_query
            )
            if software is None:
                raise APIError(404, "not_found", "Control software must be in this local folder")
        return source, clone, software

    async def propose(self, robot_id: uuid.UUID, body: HostAttachment) -> HostProposal:
        robot = await robot_root(self.session, self.project_id, robot_id)
        await self._source(body)
        bridge = self.sessions.get(self.user_id, self.team_id, self.project_id)
        if (
            bridge is None
            or bridge.companion_instance_id != body.machine_id
            or bridge.token_exp <= utcnow()
        ):
            raise APIError(409, "proposal_changed", "A matching live companion is required")
        if await self.provider.identity() != body.machine_id:
            raise APIError(
                503, "source_unavailable", "This hardware provider is on another or unknown machine"
            )
        entry, config = await read_entity_config(self.session, self.project_id, robot_id)
        runtime = await resolve_runtime_config(self.session, self.project_id, robot_id)
        if (
            entry is None
            or runtime.identity is None
            or runtime.identity.kind.value not in ("usb_serial", "usb_can")
        ):
            raise APIError(409, "proposal_changed", "The robot has no accepted USB endpoint")
        topology = await read_topology(self.session, self.project_id, robot_id)
        endpoint = next(
            (n for n in topology.nodes if n.id == body.endpoint_id and n.role == "brain"), None
        )
        from solus_api.hardware.topology import MARKER

        expected = uuid.uuid5(self.project_id, f"{MARKER}:endpoint:{runtime.identity.device_ref}")
        if endpoint is None or body.endpoint_id != expected:
            raise APIError(409, "proposal_changed", "The accepted controller endpoint changed")
        devices = await self.provider.devices()
        if not any(item.get("device_ref") == runtime.identity.device_ref for item in devices):
            raise APIError(
                404, "device_not_found", "The accepted USB endpoint is not currently present"
            )
        # Local-folder writers do not share the hardware project lock. Read fresh
        # source/code rows only after provider I/O and keep them stable through commit.
        source, clone, software = await self._source(body, lock=True)
        preview = await self._preview(robot_id, body, topology, source.name, software)
        evidence = {
            "inputs": body.model_dump(mode="json"),
            "robot_version": robot.version,
            "config_id": str(entry.id),
            "config_version": entry.config_version,
            "config": config.model_dump(mode="json") if config else None,
            "source": [str(source.id), source.config, source.cursor, source.updated_at.isoformat()],
            "clone": [str(clone.id), clone.version, clone.attrs],
            "software": [str(software.id), software.version, software.attrs] if software else None,
            "bridge": bridge.session_id,
            "topology": topology.model_dump(mode="json"),
        }
        encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str).encode()
        if len(encoded) > 256 * 1024:
            raise APIError(422, "validation_error", "Host proposal evidence exceeds its limit")
        if (
            self.sessions.get(self.user_id, self.team_id, self.project_id) is not bridge
            or bridge.token_exp <= utcnow()
        ):
            raise APIError(409, "proposal_changed", "The companion connection changed or expired")
        return HostProposal(
            **body.model_dump(),
            host_name=source.name,
            topology=preview,
            proposal_digest=hashlib.sha256(encoded).hexdigest(),
            notes=[
                "Control software names local files; running code is not verified.",
                "The companion matches this machine; no control-loop shim is verified.",
            ],
        )

    async def _rows(self, robot_id: uuid.UUID) -> list[GraphEdge]:
        return list(
            await self.session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == self.project_id,
                    GraphEdge.attrs["robot_id"].astext == str(robot_id),
                    GraphEdge.attrs["managed_by"].astext == HOST_MARKER,
                    GraphEdge.origin == "manual",
                    GraphEdge.source_id.is_(None),
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )

    async def _preview(
        self,
        robot_id: uuid.UUID,
        body: HostAttachment,
        topology: RobotTopology,
        name: str,
        software: GraphEntity | None,
    ) -> RobotTopology:
        old = await self._rows(robot_id)
        old_ids = {e.src_id for e in old} | {e.dst_id for e in old}
        old_ids.discard(body.endpoint_id)
        host_id = uuid.uuid5(self.project_id, f"{HOST_MARKER}:host:{body.machine_id}")
        bus_id = uuid.uuid5(host_id, "usb")
        evidence = [Evidence(by="user", source=f"source:{body.local_source_id}")]
        if software is not None:
            evidence.append(Evidence(by="user", source=f"entity:{software.id}"))
        nodes = [n for n in topology.nodes if n.id not in old_ids]
        nodes = [
            n.model_copy(update={"brain_kind": body.endpoint_brain_kind})
            if n.id == body.endpoint_id and body.endpoint_brain_kind
            else n
            for n in nodes
        ]
        nodes.extend(
            [
                TopologyNode(
                    id=host_id,
                    name=name,
                    role="brain",
                    brain_kind="host",
                    channel="local",
                    software=software.name if software else None,
                    evidence=evidence,
                ),
                TopologyNode(id=bus_id, name="USB", role="bus", channel="usb", evidence=evidence),
            ]
        )
        edges = [e for e in topology.edges if e.id not in {row.id for row in old}]
        for src, dst in ((host_id, bus_id), (bus_id, body.endpoint_id)):
            edges.append(
                TopologyEdge(
                    id=uuid.uuid5(robot_id, f"{HOST_MARKER}:{src}:{dst}"),
                    source=src,
                    target=dst,
                    protocol="usb",
                )
            )
        targets = {edge.target for edge in edges}
        return RobotTopology(
            robot_id=robot_id,
            nodes=sorted(nodes, key=lambda n: str(n.id)),
            edges=sorted(edges, key=lambda e: str(e.id)),
            roots=sorted((n.id for n in nodes if n.id not in targets), key=str),
        )

    async def confirm(
        self, robot_id: uuid.UUID, body: HostConfirm, key: uuid.UUID
    ) -> tuple[RobotTopology, bool]:
        ledger = ReviewedHardwareOperations(self.session, self.project_id, self.user_id)
        previous, digest = await ledger.replay(
            key, "topology.host", {"robot_id": str(robot_id), **body.model_dump(mode="json")}
        )
        if previous is not None:
            return RobotTopology.model_validate(previous.response), True
        proposal = await self.propose(
            robot_id, HostAttachment.model_validate(body.model_dump(exclude={"proposal_digest"}))
        )
        if not hmac.compare_digest(proposal.proposal_digest, body.proposal_digest):
            raise APIError(
                409, "proposal_changed", "Host topology evidence changed; review a fresh proposal"
            )
        await self._persist(robot_id, body, proposal.topology)
        result = await read_topology(self.session, self.project_id, robot_id)
        ledger.record(key, "topology.host", digest, result.model_dump(mode="json"))
        return result, False

    async def _persist(
        self, robot_id: uuid.UUID, body: HostAttachment, topology: RobotTopology
    ) -> None:
        for previous_edge in await self._rows(robot_id):
            previous_edge.deleted_at = utcnow()
        host = next(n for n in topology.nodes if n.brain_kind == "host")
        bus_id = uuid.uuid5(host.id, "usb")
        for node in (host, next(n for n in topology.nodes if n.id == bus_id)):
            entity = await self.session.get(GraphEntity, node.id)
            if entity is None:
                entity = GraphEntity(
                    id=node.id,
                    project_id=self.project_id,
                    kind="hardware_brain" if node.role == "brain" else "hardware_bus",
                    domain=Domain.ELECTRICAL,
                    name=node.name,
                    origin="manual",
                    attrs={
                        "managed_by": HOST_MARKER,
                        "brain_kind": node.brain_kind,
                        "channel": node.channel,
                    },
                )
                self.session.add(entity)
            elif (
                entity.project_id != self.project_id
                or entity.attrs.get("managed_by") != HOST_MARKER
            ):
                raise APIError(
                    409, "topology_conflict", "Host identity conflicts with existing graph"
                )
            entity.deleted_at = None
        await self.session.flush()
        relationships = [
            (robot_id, host.id, MEMBERSHIP),
            (host.id, bus_id, RELATION),
            (bus_id, body.endpoint_id, RELATION),
        ]
        for src, dst, relation in relationships:
            edge_id = uuid.uuid5(robot_id, f"{HOST_MARKER}:{src}:{dst}")
            attrs = {
                "managed_by": HOST_MARKER,
                "robot_id": str(robot_id),
                "endpoint_id": str(body.endpoint_id),
                "protocol": "usb" if relation == RELATION else None,
                "address": None,
                "evidence": [e.model_dump() for e in host.evidence],
            }
            if dst == host.id:
                attrs["software"] = host.software
                attrs["software_entity_id"] = (
                    str(body.software_entity_id) if body.software_entity_id else None
                )
            if dst == body.endpoint_id:
                attrs["brain_kind"] = next(n.brain_kind for n in topology.nodes if n.id == dst)
            edge = await self.session.get(GraphEdge, edge_id)
            if edge is None:
                self.session.add(
                    GraphEdge(
                        id=edge_id,
                        project_id=self.project_id,
                        src_id=src,
                        dst_id=dst,
                        relation_type=relation,
                        domain_pair="electrical<->electrical",
                        origin="manual",
                        attrs=attrs,
                    )
                )
            else:
                if (
                    edge.project_id != self.project_id
                    or edge.attrs.get("managed_by") != HOST_MARKER
                ):
                    raise APIError(409, "topology_conflict", "Host relation identity conflicts")
                edge.attrs, edge.deleted_at = attrs, None
        await self.session.flush()
