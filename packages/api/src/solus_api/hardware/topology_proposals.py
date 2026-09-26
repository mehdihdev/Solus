"""Read-only extraction from one private account/project file capability."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import bind_scope, resolve_scope
from solus_api.hardware.config import is_private_source
from solus_api.hardware.local_sources import (
    LocalHardwareSources,
    LocalSourceError,
    VerifiedHardwareSource,
)
from solus_api.hardware.topology import read_topology
from solus_api.hardware.topology_evidence import TopologyExtraction
from solus_api.livebench.bench_router import get_bench_local
from solus_api.models import GraphEntity, SolusEntry

ExtractionKind = Literal["firmware", "host_config"]


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brain_id: uuid.UUID
    source_ref: Annotated[str, Field(pattern=r"^source:[0-9a-f-]{36}$", max_length=43)]
    source_kind: ExtractionKind

    @model_validator(mode="before")
    @classmethod
    def portable_input(cls, value: Any) -> Any:
        # The shared validation handler echoes short scalar inputs. Reject invalid
        # references/extra fields here so a supplied native path is never echoed.
        try:
            if not isinstance(value, dict) or set(value) != {
                "brain_id",
                "source_ref",
                "source_kind",
            }:
                raise ValueError
            if value["source_kind"] not in ("firmware", "host_config"):
                raise ValueError
            if not isinstance(value["source_ref"], str) or not value["source_ref"].startswith(
                "source:"
            ):
                raise ValueError
            brain = uuid.UUID(value["brain_id"])
            reference = uuid.UUID(value["source_ref"][7:])
        except (ValueError, TypeError, AttributeError):
            raise APIError(
                422, "validation_error", "Choose a brain and an authorized source reference."
            ) from None
        return {**value, "brain_id": brain, "source_ref": f"source:{reference}"}


class ExtractionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: uuid.UUID
    brain_id: uuid.UUID
    source_ref: str
    proposal_digest: str
    extraction: TopologyExtraction


class ExtractionProposalEnvelope(BaseModel):
    data: ExtractionProposal


def _source_error(error: LocalSourceError) -> APIError:
    if error.code == "source_unavailable":
        return APIError(503, error.code, "The local hardware runner is unavailable.")
    if error.code == "not_found":
        return APIError(404, error.code, "Authorized source not found.")
    if error.code == "source_changed":
        return APIError(409, error.code, "The source changed. Select it again before reviewing.")
    return APIError(422, "relink_required", "Select this source again in the current account.")


def proposal_sources(request: Request) -> LocalHardwareSources:
    try:
        return LocalHardwareSources.for_local_runner(get_bench_local(request))
    except LocalSourceError as error:
        raise _source_error(error) from None


def _portable_evidence(value: object) -> bool:
    if isinstance(value, dict):
        return all(_portable_evidence(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_portable_evidence(item) for item in value)
    if isinstance(value, str):
        if is_private_source(value.strip()):
            return False
        # Adapter details are JSON strings. Check their scalar values as well.
        if value.startswith(("{", "[")):
            try:
                return _portable_evidence(json.loads(value))
            except (ValueError, RecursionError):
                return False
    return True


def _parse(
    source: VerifiedHardwareSource, kind: ExtractionKind, namespace: str
) -> TopologyExtraction:
    try:
        from livebench.hardware.repo_config import extract_repo_config_bytes
        from livebench.hardware.topology_extractors import firmware_topology, repo_config_topology
        from livebench.recognition.firmware import extract_firmware_bytes

        if kind == "firmware":
            result = firmware_topology(
                extract_firmware_bytes(
                    source.content, suffix=source.suffix, source_ref=source.source_ref
                ),
                source_namespace=namespace,
                source_ref=source.source_ref,
            )
        else:
            result = repo_config_topology(
                extract_repo_config_bytes(
                    source.content, suffix=source.suffix, source_ref=source.source_ref
                ),
                source_namespace=namespace,
                source_ref=source.source_ref,
            )
    except ImportError:
        raise APIError(
            503, "source_unavailable", "The local extraction parser is unavailable."
        ) from None
    except ValueError:
        raise APIError(
            422,
            "validation_error",
            "The selected file is invalid or unsupported for this extraction.",
        ) from None
    if result.status != "success" or not _portable_evidence(result.model_dump(mode="json")):
        raise APIError(
            422,
            "validation_error",
            "The selected source exceeds extraction limits or contains invalid evidence.",
        )
    return result


async def parse_source(
    source: VerifiedHardwareSource, kind: ExtractionKind, namespace: str
) -> TopologyExtraction:
    return await asyncio.to_thread(_parse, source, kind, namespace)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class TopologyProposalService:
    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        sources: LocalHardwareSources,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.user_id = user_id
        self.sources = sources

    async def _snapshot(self, robot_id: uuid.UUID, brain_id: uuid.UUID) -> str:
        # Queries must observe changes made while parsing, not ORM identity-map
        # snapshots. Column reads below also bind versions and CONFIG evidence.
        self.session.expire_all()
        scope = await resolve_scope(self.session, self.project_id, self.user_id)
        with bind_scope(scope):
            topology = await read_topology(self.session, self.project_id, robot_id)
            if not any(node.id == brain_id and node.role == "brain" for node in topology.nodes):
                raise APIError(404, "not_found", "Brain not found in this robot.")
            ids = [robot_id, *(node.id for node in topology.nodes)]
            entities = (
                await self.session.execute(
                    select(
                        GraphEntity.id,
                        GraphEntity.version,
                        GraphEntity.updated_at,
                        GraphEntity.attrs,
                    )
                    .where(
                        scope.entity_predicate(),
                        GraphEntity.id.in_(ids),
                        GraphEntity.deleted_at.is_(None),
                    )
                    .order_by(GraphEntity.id)
                )
            ).all()
            if brain_id not in {row.id for row in entities}:
                raise APIError(404, "not_found", "Brain not found in this graph view.")
            configs = (
                await self.session.execute(
                    select(
                        SolusEntry.id,
                        SolusEntry.config_version,
                        SolusEntry.payload,
                    )
                    .where(
                        SolusEntry.project_id == self.project_id,
                        SolusEntry.deleted_at.is_(None),
                        or_(
                            SolusEntry.configured_entity_id.in_(ids),
                            SolusEntry.entity_id.in_(ids),
                            SolusEntry.payload["robot_entity_id"].astext == str(robot_id),
                        ),
                    )
                    .order_by(SolusEntry.id)
                )
            ).all()
        return _digest(
            {
                "scope": {
                    "replacements": sorted(scope.replacements),
                    "roots": sorted(scope.root_replacements),
                    "branches": sorted(scope.source_branches),
                },
                "topology": topology.model_dump(mode="json"),
                "entities": [tuple(row) for row in entities],
                "configs": [tuple(row) for row in configs],
            }
        )

    async def _read(self, reference: str) -> VerifiedHardwareSource:
        try:
            return await asyncio.to_thread(
                self.sources.read_source, self.project_id, self.user_id, reference
            )
        except LocalSourceError as error:
            raise _source_error(error) from None

    async def propose(self, robot_id: uuid.UUID, body: ExtractionRequest) -> ExtractionProposal:
        before = await self._snapshot(robot_id, body.brain_id)
        source = await self._read(body.source_ref)
        namespace = f"extraction:{uuid.uuid5(self.project_id, f'{self.user_id}:{body.source_ref}')}"
        extraction = await parse_source(source, body.source_kind, namespace)
        checked = await self._read(body.source_ref)
        if checked != source:
            raise APIError(409, "source_changed", "The source changed during extraction.")
        if await self._snapshot(robot_id, body.brain_id) != before:
            raise APIError(
                409, "proposal_changed", "The robot changed during extraction. Review again."
            )
        digest = _digest(
            {
                "project": self.project_id,
                "account": self.user_id,
                "robot": robot_id,
                "brain": body.brain_id,
                "source": body.source_ref,
                "suffix": source.suffix,
                "kind": body.source_kind,
                "content": hashlib.sha256(source.content).hexdigest(),
                "snapshot": before,
                "extraction": extraction.model_dump(mode="json"),
            }
        )
        return ExtractionProposal(
            robot_id=robot_id,
            brain_id=body.brain_id,
            source_ref=body.source_ref,
            proposal_digest=digest,
            extraction=extraction,
        )
