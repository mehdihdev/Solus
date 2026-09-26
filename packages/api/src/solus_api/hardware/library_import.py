"""Standalone library creation through the existing scoped operation ledger."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.library import Library, PartDefinition
from solus_api.hardware.operations import ReviewedHardwareOperations
from solus_api.hardware.store import put_entity_config
from solus_api.models import Domain, GraphEntity
from solus_api.schemas import serialize_entity


async def import_standalone_part(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    key: uuid.UUID,
    part: PartDefinition,
    *,
    name: str,
    category: str,
) -> tuple[dict[str, Any], bool]:
    operations = ReviewedHardwareOperations(session, project_id, user_id)
    previous, digest = await operations.replay(
        key, "library.part.import", {"definition_id": part.id, "name": name, "category": category}
    )
    if previous is not None:
        return dict(previous.response), True
    entity = GraphEntity(
        id=uuid7(),
        project_id=project_id,
        kind="part",
        name=name,
        domain=Domain.PROJECT,
        origin="manual",
        attrs={
            "definition_id": part.id,
            "model": part.name,
            "manufacturer": part.manufacturer,
            "specs": dict(part.specs),
            "category": category,
            "provenance": "library",
        },
    )
    session.add(entity)
    await session.flush()
    source = f"part:{part.id}"
    config = EntityHardwareConfig.model_validate(
        {
            "entity_id": entity.id,
            "component": Library.part_config(part, part.id, source=source),
            "provenance": {"component": {"by": "library", "source": source}},
        }
    )
    entry = await put_entity_config(
        session, project_id, entity, config, expected_version=0, created_by=user_id
    )
    response = {"entity": serialize_entity(entity), "config_entry_id": entry.id}
    return operations.record(key, "library.part.import", digest, response), False
