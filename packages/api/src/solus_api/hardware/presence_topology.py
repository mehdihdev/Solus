"""Reviewed MCU input declarations with scoped schematic or recorded probe evidence."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import resolve_scope
from solus_api.hardware.presence import digest
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.livebench.runs import store as runs
from solus_api.livebench.runs.models import RunManifest
from solus_api.models import Domain, GraphEdge, GraphEntity, Source, SourceType
from solus_api.services.solus_graph import lock_project

if TYPE_CHECKING:
    from solus_api.hardware.presence import PresenceService

KIND = "hardware_wiring_proposal"
Channel = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")]


class WiringInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    channel: Channel
    pin: Annotated[str, Field(pattern=r"^(A[0-7]|D([2-9]|1[0-3]))$")]
    kind: Literal["analog_input", "digital_input"]
    component_entity_id: uuid.UUID | None = None
    connected_entity_id: uuid.UUID | None = None


class WiringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: Literal["uno_avr", "nano_avr"]
    mode: Literal["typed", "schematic", "probe"]
    wiring: list[WiringInput] = Field(default_factory=list, max_length=16)
    source_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        expected = (self.mode == "schematic", self.mode == "probe")
        if (self.source_id is not None, self.run_id is not None) != expected:
            raise ValueError("Select exactly the evidence required for this mode")
        channels, pins = set(), set()
        for row in self.wiring:
            references = (row.component_entity_id, row.connected_entity_id)
            if self.mode == "schematic":
                if None in references or references[0] == references[1]:
                    raise ValueError("Select two distinct schematic components for each input")
            elif any(ref is not None for ref in references):
                raise ValueError("Schematic components require schematic mode")
            if row.channel in channels or row.pin in pins:
                raise ValueError("Duplicate input pin or channel")
            channels.add(row.channel)
            pins.add(row.pin)
            analog = row.kind == "analog_input"
            if analog != row.pin.startswith("A"):
                raise ValueError("Input kind must match its pin")
            if self.profile_id == "uno_avr" and row.pin in {"A6", "A7"}:
                raise ValueError("Pin is unavailable on this profile")
        return self


class AcceptWiring(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _verify_schematic_wiring(
    entities: list[GraphEntity], edges: list[GraphEdge], wiring: list[WiringInput]
) -> None:
    components = {e.id for e in entities if e.kind == "component" and e.origin == "connector"}
    nets = {e.id for e in entities if e.kind == "net" and e.origin == "connector"}
    connections = [
        e
        for e in edges
        if e.origin == "connector"
        and e.relation_type == "connected_to"
        and e.src_id in components
        and e.dst_id in nets
    ]
    for row in wiring:
        matches = {
            edge.dst_id
            for edge in connections
            if edge.src_id == row.component_entity_id and _edge_declares_pin(edge, row.pin)
        }
        peers = {edge.dst_id for edge in connections if edge.src_id == row.connected_entity_id}
        if len(matches) != 1 or not matches.issubset(peers):
            raise APIError(
                409,
                "wiring_unproven",
                "The selected components do not prove this input pin connection",
            )


def _edge_declares_pin(edge: GraphEdge, pin: str) -> bool:
    pins = edge.attrs.get("pins")
    functions = edge.attrs.get("pin_functions", {})
    if not isinstance(pins, list) or not all(isinstance(value, str) for value in pins):
        return False
    if pin in pins:
        return True
    return isinstance(functions, dict) and any(functions.get(number) == pin for number in pins)


def probe_values(manifest: RunManifest, device_ref: str) -> tuple[dict[str, float], set[int]]:
    latest: dict[str, float] = {}
    addresses: set[int] = set()
    for packet in sorted(manifest.packets, key=lambda p: p.timestamp):
        if packet.device_id != device_ref:
            continue
        for key, value in packet.values.items():
            if key.startswith("probe.analog.") or key == "probe.i2c.responding":
                latest[key] = value
            elif key == "probe.i2c.address" and value == int(value) and 8 <= value < 120:
                addresses.add(int(value))
    return latest, addresses


class WiringService:
    def __init__(self, presence: PresenceService):
        self.presence = presence
        self.session = presence.session
        self.project_id = presence.project_id

    async def _schematic(
        self, source_id: uuid.UUID, wiring: list[WiringInput]
    ) -> tuple[Any, list[dict[str, Any]], list[str]]:
        source = await self.session.scalar(
            select(Source).where(
                Source.id == source_id,
                Source.project_id == self.project_id,
                Source.type.in_([SourceType.KICAD, SourceType.ALTIUM]),
                Source.status == "connected",
            )
        )
        if source is None:
            raise APIError(404, "not_found", "Connected schematic source not found")
        scope = await resolve_scope(self.session, self.project_id, self.presence.user_id)
        entities = list(
            await self.session.scalars(
                select(GraphEntity)
                .where(
                    scope.entity_predicate(),
                    GraphEntity.source_id == source_id,
                    GraphEntity.project_id == self.project_id,
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.domain == Domain.ELECTRICAL,
                )
                .order_by(GraphEntity.id)
                .limit(257)
            )
        )
        if not entities:
            raise APIError(409, "evidence_unavailable", "No visible schematic graph evidence")
        ids = [row.id for row in entities]
        edges = list(
            await self.session.scalars(
                select(GraphEdge)
                .where(
                    scope.edge_predicate(),
                    GraphEdge.project_id == self.project_id,
                    GraphEdge.source_id == source_id,
                    GraphEdge.deleted_at.is_(None),
                    GraphEdge.src_id.in_(ids),
                    GraphEdge.dst_id.in_(ids),
                )
                .order_by(GraphEdge.id)
                .limit(513)
            )
        )
        if len(entities) > 256 or len(edges) > 512:
            raise APIError(422, "evidence_too_large", "Select a smaller schematic source")
        _verify_schematic_wiring(entities, edges, wiring)
        snapshot = {
            "entities": [(str(e.id), e.kind, e.name, e.attrs) for e in entities],
            "edges": [
                (str(e.id), str(e.src_id), str(e.dst_id), e.relation_type, e.confidence, e.attrs)
                for e in edges
            ],
        }
        observations = [
            {"detail": f"Schematic {e.kind}: {e.name[:200]}", "confidence": None}
            for e in entities[:64]
        ]
        return (
            snapshot,
            observations,
            [
                "Schematic connections require an explicit supported input mapping; "
                "no device driver is inferred."
            ],
        )

    async def _probe(
        self, robot: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[Any, list[dict[str, Any]], list[str]]:
        record = await runs.record(self.session, self.project_id, run_id)
        info = runs.summary(record)
        if info.robot_id != robot:
            raise APIError(404, "not_found", "Probe run not found for this robot")
        if info.status != "completed":
            raise APIError(409, "evidence_unavailable", "Use a completed probe recording")
        manifest = await runs.load(
            self.session, self.presence.store, record, self.presence.user_id, 3600
        )
        config = await resolve_runtime_config(self.session, self.project_id, robot)
        assert config.identity is not None
        if manifest.robot_id != robot:
            raise APIError(409, "evidence_changed", "Probe recording robot changed")
        latest, addresses = probe_values(manifest, config.identity.device_ref)
        if not latest and not addresses:
            raise APIError(409, "evidence_unavailable", "No probe observations for this device")
        if len(latest) > 16:
            raise APIError(422, "evidence_too_large", "Probe signal set exceeds profile limits")
        observations = [
            {
                "detail": f"{info.origin} recording: {key} = {value}; raw observation only",
                "confidence": None,
            }
            for key, value in sorted(latest.items())
        ]
        observations.extend(
            {"detail": f"I2C address {address} responded; device type unknown", "confidence": None}
            for address in sorted(addresses)
        )
        unresolved = [
            "Analog samples do not establish attached parts; "
            "no I2C responders does not establish empty wiring."
        ]
        unresolved.extend(
            f"I2C device at {address} needs an identified driver" for address in sorted(addresses)
        )
        return (
            {"record": record.attrs, "manifest": digest(manifest.model_dump(mode="json"))},
            observations,
            unresolved,
        )

    async def _evidence(
        self, robot: uuid.UUID, body: WiringRequest
    ) -> tuple[Any, list[dict[str, Any]], list[str]]:
        if body.source_id is not None:
            return await self._schematic(body.source_id, body.wiring)
        if body.run_id is not None:
            return await self._probe(robot, body.run_id)
        return (
            {},
            [
                {
                    "detail": "User-declared input wiring; attachment has not been measured.",
                    "confidence": None,
                }
            ],
            [],
        )

    async def propose(
        self, robot: uuid.UUID, brain: uuid.UUID, body: WiringRequest
    ) -> dict[str, Any]:
        await lock_project(self.session, self.project_id)
        binding, config_digest = await self.presence.binding(robot, brain)
        evidence, observations, unresolved = await self._evidence(robot, body)
        payload = body.model_dump(mode="json", exclude_none=True)
        fingerprint = digest(
            {"request": payload, "binding": binding, "config": config_digest, "evidence": evidence}
        )
        entity = GraphEntity(
            project_id=self.project_id,
            kind=KIND,
            domain=Domain.RUNTIME,
            origin="system",
            name="Reviewed MCU wiring proposal",
            attrs={
                "created_by": str(self.presence.user_id),
                "robot_id": str(robot),
                "brain_id": str(brain),
                "request": payload,
                "digest": fingerprint,
                "status": "proposed",
                "observations": observations,
                "unresolved": unresolved,
            },
        )
        self.session.add(entity)
        await self.session.flush()
        self.session.add(
            GraphEdge(
                project_id=self.project_id,
                src_id=entity.id,
                dst_id=brain,
                relation_type="wiring_proposed_for",
                domain_pair="runtime:runtime",
                origin="system",
                attrs={},
            )
        )
        await self.session.flush()
        return {
            "proposal_id": str(entity.id),
            "digest": fingerprint,
            "profile_id": body.profile_id,
            "mode": body.mode,
            "wiring": payload["wiring"],
            "observations": observations,
            "unresolved": unresolved,
            "status": "proposed",
        }

    async def checked(
        self, robot: uuid.UUID, brain: uuid.UUID, proposal_id: uuid.UUID, *, accepted: bool
    ) -> GraphEntity:
        entity = await self.session.scalar(
            select(GraphEntity)
            .where(
                GraphEntity.id == proposal_id,
                GraphEntity.project_id == self.project_id,
                GraphEntity.kind == KIND,
                GraphEntity.origin == "system",
                GraphEntity.source_id.is_(None),
                GraphEntity.deleted_at.is_(None),
                GraphEntity.attrs["created_by"].astext == str(self.presence.user_id),
                GraphEntity.attrs["robot_id"].astext == str(robot),
                GraphEntity.attrs["brain_id"].astext == str(brain),
            )
            .execution_options(populate_existing=True)
        )
        if entity is None:
            raise APIError(404, "not_found", "Wiring proposal not found")
        if accepted and entity.attrs["status"] != "accepted":
            raise APIError(409, "wiring_unaccepted", "Accept the wiring proposal first")
        body = WiringRequest.model_validate(entity.attrs["request"])
        binding, config_digest = await self.presence.binding(robot, brain)
        evidence, _, _ = await self._evidence(robot, body)
        current = digest(
            {
                "request": body.model_dump(mode="json", exclude_none=True),
                "binding": binding,
                "config": config_digest,
                "evidence": evidence,
            }
        )
        if current != entity.attrs["digest"]:
            raise APIError(409, "wiring_changed", "Wiring evidence changed; review again")
        return entity

    async def accept(
        self, robot: uuid.UUID, brain: uuid.UUID, proposal_id: uuid.UUID, expected: str
    ) -> dict[str, Any]:
        await lock_project(self.session, self.project_id)
        entity = await self.checked(robot, brain, proposal_id, accepted=False)
        if entity.attrs["digest"] != expected:
            raise APIError(409, "wiring_changed", "Wiring proposal changed; review again")
        entity.attrs = {**entity.attrs, "status": "accepted"}
        await self.session.flush()
        return {"proposal_id": str(entity.id), "digest": expected, "status": "accepted"}
