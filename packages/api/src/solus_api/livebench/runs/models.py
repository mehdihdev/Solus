"""Strict portable recording format. Imported origins are claims, never live proof."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from solus_api.graph.packet import TelemetryPacket

MAX_BYTES = 8 * 1024 * 1024
MAX_PACKETS = 10000
Text = Annotated[str, Field(min_length=1, max_length=512)]
Signal = Annotated[str, Field(min_length=1, max_length=128)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PartEvidence(StrictModel):
    entity_id: UUID
    name: Text
    device_id: Text
    current_signal: Signal | None = None
    position_signal: Signal | None = None
    command_signal: Signal | None = None
    stall_current_a: Annotated[FiniteFloat, Field(gt=0)] | None = None
    position_min: FiniteFloat | None = None
    position_max: FiniteFloat | None = None
    position_unit: Annotated[str, Field(max_length=32)] | None = None
    code_site: Text | None = None
    cad_revision: Text | None = None


class SensorReference(StrictModel):
    artifact_id: UUID
    timestamp: AwareDatetime
    kind: Literal["camera", "lidar"]
    device_id: Text


class RevisionSnapshot(StrictModel):
    entity_id: UUID
    kind: Text
    name: Text
    source_id: UUID | None = None
    revision: Text | None = None
    # JSON serialized CONFIG/graph data, individually bounded and inert.
    data: Annotated[str, Field(max_length=65536)] | None = None


class RunManifest(StrictModel):
    schema_version: Literal[1] = 1
    robot_id: UUID
    started_at: AwareDatetime
    packets: list[TelemetryPacket] = Field(default_factory=list, max_length=MAX_PACKETS)
    sensors: list[SensorReference] = Field(default_factory=list, max_length=10000)
    parts: list[PartEvidence] = Field(default_factory=list, max_length=256)
    snapshots: list[RevisionSnapshot] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def unique_parts(self) -> Self:
        if len({part.entity_id for part in self.parts}) != len(self.parts):
            raise ValueError("duplicate part identity")
        if len({part.device_id for part in self.parts}) != len(self.parts):
            raise ValueError("ambiguous part device identity")
        signals: set[tuple[str, str]] = set()
        for packet in self.packets:
            signals.update((packet.device_id, name) for name in packet.values)
            if len(signals) > 4096:
                raise ValueError("at most 4096 distinct device signals per run")
        return self


def parse_manifest(data: bytes) -> RunManifest:
    if len(data) > MAX_BYTES:
        raise ValueError("run exceeds 8 MiB")
    return RunManifest.model_validate_json(data)


def encode_manifest(manifest: RunManifest) -> bytes:
    data = manifest.model_dump_json().encode()
    if len(data) > MAX_BYTES:
        raise ValueError("run exceeds 8 MiB")
    return data


class RunSummary(StrictModel):
    id: UUID
    robot_id: UUID
    session_id: UUID | None = None
    name: Annotated[str, Field(min_length=1, max_length=120)]
    origin: Literal["live", "recorded", "synthetic"]
    status: Literal["running", "completed", "truncated", "interrupted"]
    started_at: datetime
    ended_at: datetime | None = None
    packet_count: int = Field(default=0, ge=0)
    drop_count: int = Field(default=0, ge=0)
    artifact_id: UUID | None = None
