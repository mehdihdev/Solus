"""Strict import and explicitly confirmed telemetry binding requests."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MeshArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=512)
    artifact_id: uuid.UUID


class ImportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: uuid.UUID
    artifact_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    format: Literal["urdf", "mjcf"]
    meshes: list[MeshArtifact] = Field(default_factory=list, max_length=64)
    source_entity_id: uuid.UUID | None = None
    source_revision: str | None = Field(default=None, min_length=1, max_length=128)


class ReplaceModel(ImportModel):
    expected_version: int = Field(gt=0, strict=True)


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    joint: str = Field(min_length=1, max_length=128)
    part_entity_id: uuid.UUID
    device_id: str = Field(min_length=1, max_length=256)
    signal: str = Field(min_length=1, max_length=128)
    unit: Literal["rad", "deg", "m"]
    scale: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    offset: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0, strict=True)
    bindings: list[Binding] = Field(max_length=128)


class CadBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mesh_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_entity_id: uuid.UUID


class CadBindings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0, strict=True)
    bindings: list[CadBinding] = Field(max_length=32)


class CadImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: uuid.UUID
    source_entity_id: uuid.UUID
    expected_revision: str = Field(min_length=1, max_length=128)
