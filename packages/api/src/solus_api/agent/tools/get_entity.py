"""The reference tool: `get_entity` (SOLUS-W0-04).

Proves the contract end to end — registration, arg validation, a real team-scoped
graph read, a model-consumable dict, and a missing/out-of-scope entity → ok=False,
NOT_FOUND with no traceback. The caller's project scope is bound at construction by
Solus code, NEVER supplied by the model (CLAUDE.md §7 — ingested content cannot alter
team scope), so `entity_id` is the only model-supplied argument.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.graph.read_scope import current_scope
from solus_api.models import Domain, GraphEntity

GET_ENTITY_DESCRIPTOR = ToolDescriptor(
    name="get_entity",
    description=(
        "Fetch a graph entity by its ID, returning kind, domain, name, attrs, and "
        "canonical_part_id."
    ),
    params={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "format": "uuid", "description": "The entity's UUID."}
        },
        "required": ["entity_id"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "project_id": {"type": "string", "format": "uuid"},
            "kind": {"type": "string"},
            "domain": {"type": "string"},
            "name": {"type": "string"},
            "canonical_part_id": {"type": ["string", "null"], "format": "uuid"},
            "source_connector": {"type": ["string", "null"]},
            "external_ref": {"type": ["string", "null"]},
            "attrs": {"type": "object"},
            "modality_hints": {"type": "object"},
        },
        "required": ["id", "project_id", "kind", "domain", "name", "attrs", "modality_hints"],
        "additionalProperties": False,
    },
)


def _serialize(entity: GraphEntity) -> dict[str, Any]:
    """A curated, JSON-native view for the model — deliberately omits the embedding
    (a 1536-float vector is noise in the reasoning context, not signal; exactly the
    kind of bulk data the contract keeps off the reasoning path)."""
    canonical = entity.canonical_part_id
    return {
        "id": str(entity.id),
        "project_id": str(entity.project_id),
        "kind": entity.kind,
        "domain": entity.domain.value,
        "name": entity.name,
        "canonical_part_id": str(canonical) if canonical is not None else None,
        "source_connector": entity.source_connector,
        "external_ref": entity.external_ref,
        "attrs": entity.attrs,
        "modality_hints": entity.modality_hints,
    }


def build_get_entity_tool(
    session_factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> Tool:
    """Build the tool bound to ONE project scope. The SOL layer supplies the request's
    `project_id` here (Solus code), so the model can only reach entities in the project
    the invocation is already scoped to."""

    read_scope = current_scope(project_id)

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        entity_id = uuid.UUID(args["entity_id"])  # already validated as a uuid by the registry
        async with session_factory() as session:
            entity = await session.scalar(
                select(GraphEntity).where(
                    GraphEntity.id == entity_id,
                    GraphEntity.project_id == project_id,
                    GraphEntity.deleted_at.is_(None),
                    read_scope.entity_predicate(),
                    # SOLUSDEV-246 ST2: the workspace layer is not the model's
                    # to read — NOT_FOUND, exactly like an out-of-scope id.
                    GraphEntity.domain != Domain.WORKSPACE,
                )
            )
        if entity is None:
            # NOT_FOUND (not UNAUTHORIZED) for out-of-scope ids too, so there is no
            # cross-tenant existence oracle.
            raise ToolException(
                f"No entity {entity_id} in this project", code=ToolErrorCode.NOT_FOUND
            )
        return _serialize(entity)

    return InProcessTool(GET_ENTITY_DESCRIPTOR, handler)
