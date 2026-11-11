"""Member and machine nodes (SOLUSDEV-320 resolution 9).

A `member` node per (project, user) and a `machine` node per (project, companion id), joined
by `contains`. A machine belongs to the member who first registered it (`attrs.owner_user_id`);
a teammate sending the same companion id gets a 404, never a takeover. `recent_commands` is
created empty and never written here: the bridge's command log owns it. Flushes, never commits.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from solus_contracts.relations import EdgeOrigin, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.models import Domain, GraphEntity, SolusSection, User
from solus_api.services.machine_simulators import derive_simulators
from solus_api.services.solus_graph import SolusGraph, lock_project

logger = logging.getLogger("solus.services.machines")

ORIGIN = EdgeOrigin.SYSTEM.value


class MachineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str = Field(min_length=1, max_length=128)
    os: str = Field(min_length=1, max_length=32)
    arch: str = Field(min_length=1, max_length=32)


async def _system_node(
    session: AsyncSession, project_id: uuid.UUID, kind: str, canonical_key: str
) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kind,
            GraphEntity.canonical_key == canonical_key,
            GraphEntity.deleted_at.is_(None),
        )
    )
    return row


async def find_machine(
    session: AsyncSession, project_id: uuid.UUID, companion_id: str
) -> GraphEntity | None:
    return await _system_node(session, project_id, kinds.MACHINE, f"machine:{companion_id}")


async def ensure_member(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> GraphEntity:
    """The (project, user) `member` node, created on first use; its display name follows
    the user's. Flushes, never commits."""
    await lock_project(session, project_id)
    user = await session.get(User, user_id)
    if user is None:
        raise APIError(404, "not_found", "User not found")
    display_name = user.display_name or user.email.split("@", 1)[0]
    member = await _system_node(session, project_id, kinds.MEMBER, f"member:{user_id}")
    if member is None:
        member = GraphEntity(
            project_id=project_id,
            kind=kinds.MEMBER,
            domain=Domain.PROJECT,
            name=display_name,
            origin=ORIGIN,
            canonical_key=f"member:{user_id}",
            attrs={"display_name": display_name},
        )
        session.add(member)
    elif member.attrs.get("display_name") != display_name:
        member.attrs = {**member.attrs, "display_name": display_name}
        member.name = display_name
    await session.flush()
    # The person lives under `.solus` → Members on the canvas, not at the root:
    # `members/<uid>` is their subsection, and this is the parent edge that puts
    # the member (and so their machines) inside the tree.
    tree = await SolusGraph.ensure(session, project_id)
    await write_edge(
        session,
        project_id=project_id,
        src_id=tree.sections[SolusSection.MEMBERS].id,
        dst_id=member.id,
        relation_type=RelationType.CONTAINS.value,
        origin=ORIGIN,
        confidence=1.0,
        evidence=[],
        created_by=None,
    )
    return member


async def upsert_machine(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    companion_id: str,
    payload: MachineIn,
    *,
    tool_versions: Mapping[str, str] | None = None,
) -> GraphEntity:
    """Idempotent: a second call updates the machine's attrs in place and bumps `version`
    only when something changed. `tool_versions` REPLACES the stored dict when the
    companion answered (an uninstalled tool disappears); None keeps the last report. The
    derived `simulators` facts (SOLUSDEV-322) follow the same rule, from the same answer."""
    await lock_project(session, project_id)
    machine = await find_machine(session, project_id, companion_id)
    if machine is not None and machine.attrs.get("owner_user_id") != str(user_id):
        logger.warning(
            "machine takeover refused project=%s user=%s companion=%s",
            project_id,
            user_id,
            companion_id,
        )
        raise APIError(404, "not_found", "Machine not found")
    member = await ensure_member(session, project_id, user_id)

    prior: dict[str, Any] = machine.attrs if machine is not None else {}
    versions: dict[str, str] = (
        dict(tool_versions) if tool_versions is not None else prior.get("tool_versions", {})
    )
    attrs = {
        **payload.model_dump(),
        "owner_user_id": str(user_id),
        "tool_versions": versions,
        "simulators": derive_simulators(versions),
        "devices": prior.get("devices", []),
        "flash_history": prior.get("flash_history", []),
        "recent_commands": prior.get("recent_commands", []),
    }
    if machine is None:
        machine = GraphEntity(
            project_id=project_id,
            kind=kinds.MACHINE,
            domain=Domain.RUNTIME,
            name=payload.hostname,
            origin=ORIGIN,
            canonical_key=f"machine:{companion_id}",
            attrs=attrs,
        )
        session.add(machine)
    elif attrs != machine.attrs or machine.name != payload.hostname:
        machine.attrs = attrs
        machine.name = payload.hostname
        machine.version += 1
    await session.flush()
    await write_edge(
        session,
        project_id=project_id,
        src_id=member.id,
        dst_id=machine.id,
        relation_type=RelationType.CONTAINS.value,
        origin=ORIGIN,
        confidence=1.0,
        evidence=[],
        created_by=user_id,
    )
    logger.info(
        "machine upserted project=%s user=%s companion=%s", project_id, user_id, companion_id
    )
    return machine
