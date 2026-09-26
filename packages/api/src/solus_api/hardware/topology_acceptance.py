"""Reviewed source evidence, deliberately separate from operational hardware CONFIG."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import resolve_scope
from solus_api.hardware.config import is_private_source
from solus_api.hardware.operations import ReviewedHardwareOperations
from solus_api.hardware.topology import EVIDENCE_MARKER as MARKER
from solus_api.hardware.topology import EVIDENCE_RELATION as RELATION
from solus_api.hardware.topology import read_topology
from solus_api.hardware.topology_proposals import (
    ExtractionKind,
    ExtractionRequest,
    TopologyProposalService,
)
from solus_api.models import Domain, GraphEdge, GraphEntity


class ExtractionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_index: Annotated[int, Field(strict=True, ge=0, le=255)]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    entity_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def portable_name(cls, value: str) -> str:
        value = value.strip()
        if not value or is_private_source(value) or any(ord(c) < 32 for c in value):
            raise APIError(422, "validation_error", "Choose a short display name.")
        return value


class ExtractionConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brain_id: uuid.UUID
    source_ref: str
    source_kind: ExtractionKind
    proposal_digest: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    operation_id: uuid.UUID
    selections: Annotated[list[ExtractionSelection], Field(min_length=1, max_length=256)]

    @model_validator(mode="before")
    @classmethod
    def portable_input(cls, value: Any) -> Any:
        allowed = {
            "brain_id",
            "source_ref",
            "source_kind",
            "proposal_digest",
            "operation_id",
            "selections",
        }
        if not isinstance(value, dict) or set(value) != allowed:
            raise APIError(422, "validation_error", "Choose reviewed evidence selections.")
        source = ExtractionRequest.model_validate(
            {k: value[k] for k in ("brain_id", "source_ref", "source_kind")}
        )
        try:
            uuid.UUID(str(value["operation_id"]))
            if (
                not isinstance(value["proposal_digest"], str)
                or len(value["proposal_digest"]) != 64
                or any(c not in "0123456789abcdef" for c in value["proposal_digest"])
            ):
                raise ValueError
            if (
                not isinstance(value["selections"], list)
                or not 1 <= len(value["selections"]) <= 256
            ):
                raise ValueError
            selections = [ExtractionSelection.model_validate(item) for item in value["selections"]]
        except (ValueError, TypeError, ValidationError):
            raise APIError(
                422, "validation_error", "Choose valid reviewed evidence selections."
            ) from None
        return {**value, **source.model_dump(), "selections": selections}

    @model_validator(mode="after")
    def unique_rows(self) -> ExtractionConfirm:
        if len({s.row_index for s in self.selections}) != len(self.selections):
            raise ValueError("Each evidence row may be selected once")
        self.selections.sort(key=lambda s: s.row_index)
        return self


class ExtractionAcceptance(BaseModel):
    robot_id: uuid.UUID
    brain_id: uuid.UUID
    proposal_digest: str
    entity_ids: list[uuid.UUID]
    created: int


class ExtractionAcceptanceEnvelope(BaseModel):
    data: ExtractionAcceptance


class TopologyAcceptanceService(TopologyProposalService):
    async def confirm(
        self, robot_id: uuid.UUID, body: ExtractionConfirm
    ) -> tuple[ExtractionAcceptance, bool]:
        ledger = ReviewedHardwareOperations(self.session, self.project_id, self.user_id)
        previous, digest = await ledger.replay(
            body.operation_id,
            "topology.extraction",
            {"robot_id": str(robot_id), **body.model_dump(mode="json")},
        )
        if previous is not None:
            return ExtractionAcceptance.model_validate(previous.response), True
        proposal = await self.propose(
            robot_id,
            ExtractionRequest.model_validate(
                body.model_dump(include={"brain_id", "source_ref", "source_kind"}, mode="json")
            ),
        )
        if not hmac.compare_digest(proposal.proposal_digest, body.proposal_digest):
            raise APIError(409, "proposal_changed", "Source evidence changed; review again.")
        topology = await read_topology(self.session, self.project_id, robot_id)
        scope = await resolve_scope(self.session, self.project_id, self.user_id)
        retained = set(
            await self.session.scalars(
                select(GraphEntity.id).where(
                    scope.entity_predicate(),
                    GraphEntity.id.in_([node.id for node in topology.nodes]),
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
        for selection in body.selections:
            if selection.row_index >= len(proposal.extraction.rows):
                raise APIError(422, "validation_error", "Select an existing evidence row.")
            if selection.entity_id is not None and selection.entity_id not in retained:
                raise APIError(404, "not_found", "Retained entity not found in this robot.")
        ids: list[uuid.UUID] = []
        created = 0
        for selection in body.selections:
            row = proposal.extraction.rows[selection.row_index]
            entity_id = selection.entity_id or uuid.uuid4()
            if selection.entity_id is None:
                self.session.add(
                    GraphEntity(
                        id=entity_id,
                        project_id=self.project_id,
                        name=selection.name,
                        kind="hardware_evidence",
                        domain=Domain.ELECTRICAL,
                        origin="manual",
                        attrs={
                            "managed_by": MARKER,
                            "nonoperational": True,
                            "robot_id": str(robot_id),
                        },
                    )
                )
                await self.session.flush()
                created += 1
            ids.append(entity_id)
            self.session.add(
                GraphEdge(
                    id=uuid.uuid4(),
                    project_id=self.project_id,
                    src_id=body.brain_id,
                    dst_id=entity_id,
                    relation_type=RELATION,
                    domain_pair="electrical<->electrical",
                    origin="manual",
                    attrs={
                        "managed_by": MARKER,
                        "nonoperational": True,
                        "robot_id": str(robot_id),
                        "reviewed_by": str(self.user_id),
                        "is_placement": selection.entity_id is None,
                        "reviewed_name": selection.name,
                        "proposal_digest": proposal.proposal_digest,
                        "row": row.model_dump(mode="json"),
                    },
                )
            )
        await self.session.flush()
        result = ExtractionAcceptance(
            robot_id=robot_id,
            brain_id=body.brain_id,
            proposal_digest=proposal.proposal_digest,
            entity_ids=ids,
            created=created,
        )
        ledger.record(
            body.operation_id, "topology.extraction", digest, result.model_dump(mode="json")
        )
        return result, False
