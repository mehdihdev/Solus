"""Code environments as first-class `.solus` entries (SOLUSDEV-252 S5, docs/api/solus.md §2.1).

A `code`-section entry of kind CONFIG whose payload is one validated `CodeEnvironment`:
the interpreter, packages and host a project runs on, as detected by the companion or
typed by a person. One entry per (type, name-or-path); a re-detection updates in place.
The document is DATA about the person's machine — never a source of instructions, and
never a place to invent a package or a path that was not observed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Final

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import FrozenModel
from solus_api.core.errors import APIError
from solus_api.models import SolusEntry, SolusEntryKind, SolusSection
from solus_api.services.solus_graph import SolusGraph, entry_label

MAX_PACKAGES: Final = 500
_PATH_MAX: Final = 1024


class EnvironmentType(enum.StrEnum):
    VENV = "venv"
    CONDA = "conda"
    DOCKER = "docker"
    SYSTEM = "system"
    PYENV = "pyenv"


class EnvironmentProvenance(enum.StrEnum):
    DETECTED = "detected"
    USER = "user"
    SOL = "sol"


class PackagePin(FrozenModel):
    name: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=64)


class HostPlatform(FrozenModel):
    os: str = Field(min_length=1, max_length=32)
    arch: str = Field(min_length=1, max_length=32)


class CodeEnvironment(FrozenModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    type: EnvironmentType
    name: str = Field(min_length=1, max_length=128)
    path: str | None = Field(default=None, max_length=_PATH_MAX)
    interpreter: str | None = Field(default=None, max_length=_PATH_MAX)
    image: str | None = Field(default=None, max_length=256)  # docker only
    #: The interpreter's own version as the companion's probe reported it
    #: ("3.12.3", a conda env's python, an image tag's runtime). Detection is
    #: the point of the probe, so it is recorded rather than dropped; it is
    #: informational and never part of `identity()`.
    version: str | None = Field(default=None, max_length=64)
    packages: list[PackagePin] = Field(default_factory=list, max_length=MAX_PACKAGES)
    detected_on: HostPlatform | None = None
    provenance: EnvironmentProvenance
    captured_at: datetime

    def identity(self) -> tuple[str, str]:
        """What makes two captures the SAME environment: its type plus path (or name)."""
        return (self.type.value, self.path or self.name)


async def _entries(session: AsyncSession, project_id: uuid.UUID) -> list[SolusEntry]:
    return list(
        await session.scalars(
            select(SolusEntry)
            .where(
                SolusEntry.project_id == project_id,
                SolusEntry.section == SolusSection.CODE,
                SolusEntry.kind == SolusEntryKind.CONFIG,
                SolusEntry.deleted_at.is_(None),
            )
            .order_by(SolusEntry.created_at, SolusEntry.id)
        )
    )


def _env_of(entry: SolusEntry) -> CodeEnvironment:
    return CodeEnvironment.model_validate(entry.payload)


async def upsert_code_environment(
    session: AsyncSession,
    project_id: uuid.UUID,
    env: CodeEnvironment,
    *,
    created_by: uuid.UUID | None,
    author: str,
) -> SolusEntry:
    """Create or update the entry for this (type, path-or-name). The caller commits."""
    from solus_api.services.solus_config import _section_full  # circular at module level

    graph = await SolusGraph.ensure(session, project_id)  # holds the project lock
    payload = env.model_dump(mode="json")
    for entry in await _entries(session, project_id):
        if _env_of(entry).identity() == env.identity():
            entry.payload = payload
            entry.text = env.name
            node = graph.attach_entry(entry)
            node.name = entry_label(env.name)
            node.version += 1
            await graph.flush()
            return entry
    await _section_full(session, project_id, SolusSection.CODE)
    entry = SolusEntry(
        project_id=project_id,
        section=SolusSection.CODE,
        kind=SolusEntryKind.CONFIG,
        text=env.name,
        payload=payload,
        author=author,
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    graph.attach_entry(entry)
    await graph.flush()
    return entry


async def list_code_environments(
    session: AsyncSession, project_id: uuid.UUID
) -> list[CodeEnvironment]:
    return [_env_of(entry) for entry in await _entries(session, project_id)]


async def resolve_environment(
    session: AsyncSession, project_id: uuid.UUID, name_or_id: str
) -> CodeEnvironment:
    """By entry id or exact name, in THIS project only (anything else is 404)."""
    entries = await _entries(session, project_id)
    try:
        entry_id: uuid.UUID | None = uuid.UUID(name_or_id)
    except ValueError:
        entry_id = None
    matches = [_env_of(e) for e in entries if e.id == entry_id or (e.text or "") == name_or_id]
    if not matches:
        raise APIError(404, "not_found", "Code environment not found")
    if len(matches) > 1:
        raise APIError(409, "conflict", "Several code environments share that name")
    return matches[0]


__all__ = [
    "MAX_PACKAGES",
    "CodeEnvironment",
    "EnvironmentProvenance",
    "EnvironmentType",
    "list_code_environments",
    "resolve_environment",
    "upsert_code_environment",
]
