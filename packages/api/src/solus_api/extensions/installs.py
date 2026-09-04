"""Query and policy helpers behind the project install routes (SOLUSDEV-235 /
ADR-035, docs/api/extensions.md §6–§8; docs/schemas/extensions.md §4.5–§4.8).

Every reader here takes the ids of an ALREADY-RESOLVED `ProjectContext` — the
project id and the team id come from the context, never from a body — so a
cross-project or cross-extension read is structurally impossible (§7 storage).
Team policy is READ here only; the policy WRITE routes live in `policy.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.core.pagination import cursor_filter
from solus_api.extensions.schemas import manifest_permissions
from solus_api.models import (
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionStorage,
    ExtensionVersion,
    TeamExtensionPolicy,
    WidgetLayout,
)

#: Route plan §7 — `{key}` syntax; a miss is `422` before any lookup.
STORAGE_KEY_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"
#: One value's canonical JSON encoding (§7).
STORAGE_VALUE_MAX_BYTES = 64 * 1024
#: Per-(project, extension) total — the `storage.own` contract cap (§7, schema §4.6).
STORAGE_TOTAL_MAX_BYTES = 256 * 1024
#: The scope the storage routes back (docs/contracts/extension-manifest.md).
STORAGE_SCOPE = "storage.own"

INSTALLS_DEFAULT_LIMIT = 50
INSTALLS_MAX_LIMIT = 200


async def _first[T](session: AsyncSession, stmt: Select[tuple[T]]) -> T | None:
    """Typed `scalar()` — `AsyncSession.scalar` is `Any` to mypy."""
    return (await session.execute(stmt)).scalar_one_or_none()


@dataclass(frozen=True)
class Grants:
    """A `(scopes, network)` pair as sets — declared by a manifest, requested by
    a body, or stored on an install."""

    scopes: frozenset[str] = frozenset()
    network: frozenset[str] = frozenset()

    @classmethod
    def of(cls, scopes: Iterable[str], network: Iterable[str]) -> Grants:
        return cls(frozenset(scopes), frozenset(network))

    @classmethod
    def declared_by(cls, manifest: dict[str, Any]) -> Grants:
        scopes, network = manifest_permissions(manifest)
        return cls(frozenset(scopes), frozenset(network))

    @classmethod
    def stored_on(cls, install: ExtensionInstall) -> Grants:
        return cls.of(install.granted_scopes, install.granted_network)

    def __sub__(self, other: Grants) -> Grants:
        return Grants(self.scopes - other.scopes, self.network - other.network)

    def __bool__(self) -> bool:
        return bool(self.scopes or self.network)

    def sorted_lists(self) -> dict[str, list[str]]:
        return {"scopes": sorted(self.scopes), "network": sorted(self.network)}


def widening(declared: Grants, current: Grants, requested: Grants) -> Grants:
    """§6.2 update semantics: what the target version declares beyond the
    CURRENT grants that the body still does not grant → `409 grants_required`."""
    return (declared - current) - requested


@dataclass(frozen=True)
class InstallJoin:
    """One §6.1 item's rows: install, catalog entry, publisher, pinned version,
    latest approved version (None when unset) and the team policy (None when
    absent)."""

    install: ExtensionInstall
    extension: Extension
    publisher: ExtensionPublisher
    pinned: ExtensionVersion
    latest: ExtensionVersion | None
    policy: TeamExtensionPolicy | None


# ------------------------------------------------------------------ readers
async def find_live_extension(session: AsyncSession, slug: str) -> Extension | None:
    """The catalog entry for a slug, matched case-insensitively (§3), live only."""
    return await _first(
        session,
        select(Extension).where(
            func.lower(Extension.slug) == slug.lower(), Extension.deleted_at.is_(None)
        ),
    )


def _approved(stmt: Select[tuple[ExtensionVersion]]) -> Select[tuple[ExtensionVersion]]:
    return stmt.where(
        ExtensionVersion.review_status == ExtensionReviewStatus.APPROVED,
        ExtensionVersion.deleted_at.is_(None),
    )


async def latest_approved_version(
    session: AsyncSession, extension: Extension
) -> ExtensionVersion | None:
    """The version `extensions.latest_approved_version_id` points at, if it is
    still approved and live."""
    if extension.latest_approved_version_id is None:
        return None
    return await _first(
        session,
        _approved(
            select(ExtensionVersion).where(
                ExtensionVersion.id == extension.latest_approved_version_id
            )
        ),
    )


async def approved_version(
    session: AsyncSession, extension_id: uuid.UUID, semver: str
) -> ExtensionVersion | None:
    """A specific approved, live version OF THIS extension — anything else is a
    404 to the installer (§6.2: pending versions are never installable)."""
    return await _first(
        session,
        _approved(
            select(ExtensionVersion).where(
                ExtensionVersion.extension_id == extension_id, ExtensionVersion.version == semver
            )
        ),
    )


async def get_install(
    session: AsyncSession,
    project_id: uuid.UUID,
    extension_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> ExtensionInstall | None:
    stmt = select(ExtensionInstall).where(
        ExtensionInstall.project_id == project_id, ExtensionInstall.extension_id == extension_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await _first(session, stmt)


async def get_policy(
    session: AsyncSession, team_id: uuid.UUID, extension_id: uuid.UUID
) -> TeamExtensionPolicy | None:
    return await _first(
        session,
        select(TeamExtensionPolicy).where(
            TeamExtensionPolicy.team_id == team_id,
            TeamExtensionPolicy.extension_id == extension_id,
        ),
    )


async def is_blocked(session: AsyncSession, team_id: uuid.UUID, extension_id: uuid.UUID) -> bool:
    """Schema invariant #8 — a team block wins over every install/enable path."""
    policy = await get_policy(session, team_id, extension_id)
    return policy is not None and policy.blocked


async def load_install_join(
    session: AsyncSession, install: ExtensionInstall, team_id: uuid.UUID
) -> InstallJoin:
    """The §6.1 item rows for ONE install (the single-item responses)."""
    extension = await session.get(Extension, install.extension_id)
    pinned = await session.get(ExtensionVersion, install.version_id)
    if extension is None or pinned is None:  # RESTRICT FKs make this unreachable
        raise LookupError("install references a missing extension or version")
    publisher = await session.get(ExtensionPublisher, extension.publisher_id)
    if publisher is None:
        raise LookupError("extension references a missing publisher")
    return InstallJoin(
        install=install,
        extension=extension,
        publisher=publisher,
        pinned=pinned,
        latest=await latest_approved_version(session, extension),
        policy=await get_policy(session, team_id, install.extension_id),
    )


async def list_install_joins(
    session: AsyncSession,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
) -> list[InstallJoin]:
    """`limit + 1` §6.1 items in one joined query, newest install first."""
    pinned = aliased(ExtensionVersion, name="pinned")
    latest = aliased(ExtensionVersion, name="latest")
    stmt = (
        select(ExtensionInstall, Extension, ExtensionPublisher, pinned, latest, TeamExtensionPolicy)
        .join(Extension, Extension.id == ExtensionInstall.extension_id)
        .join(ExtensionPublisher, ExtensionPublisher.id == Extension.publisher_id)
        .join(pinned, pinned.id == ExtensionInstall.version_id)
        .outerjoin(
            latest,
            (latest.id == Extension.latest_approved_version_id)
            & (latest.review_status == ExtensionReviewStatus.APPROVED)
            & latest.deleted_at.is_(None),
        )
        .outerjoin(
            TeamExtensionPolicy,
            (TeamExtensionPolicy.extension_id == Extension.id)
            & (TeamExtensionPolicy.team_id == team_id),
        )
        .where(ExtensionInstall.project_id == project_id)
        .order_by(ExtensionInstall.created_at.desc(), ExtensionInstall.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(ExtensionInstall.created_at, ExtensionInstall.id, cursor))
    rows = (await session.execute(stmt)).all()
    return [InstallJoin(*row) for row in rows]


# ------------------------------------------------------------------ storage
async def get_storage_row(
    session: AsyncSession, project_id: uuid.UUID, extension_id: uuid.UUID, key: str
) -> ExtensionStorage | None:
    return await _first(
        session,
        select(ExtensionStorage).where(
            ExtensionStorage.project_id == project_id,
            ExtensionStorage.extension_id == extension_id,
            ExtensionStorage.key == key,
        ),
    )


async def storage_used_bytes(
    session: AsyncSession, project_id: uuid.UUID, extension_id: uuid.UUID, *, excluding_key: str
) -> int:
    """Bytes held by every OTHER key of this (project, extension) — the base the
    projected total is computed from before a PUT of `excluding_key`."""
    total = await session.scalar(
        select(func.coalesce(func.sum(ExtensionStorage.size_bytes), 0)).where(
            ExtensionStorage.project_id == project_id,
            ExtensionStorage.extension_id == extension_id,
            ExtensionStorage.key != excluding_key,
        )
    )
    return int(total or 0)


async def delete_storage(
    session: AsyncSession, project_id: uuid.UUID, extension_id: uuid.UUID
) -> int:
    """§6.4 — clear the extension's store for this project; returns rows deleted."""
    scope = (
        ExtensionStorage.project_id == project_id,
        ExtensionStorage.extension_id == extension_id,
    )
    count = await session.scalar(select(func.count()).select_from(ExtensionStorage).where(*scope))
    await session.execute(delete(ExtensionStorage).where(*scope))
    return int(count or 0)


# ------------------------------------------------------------------- layout
async def get_layout(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> WidgetLayout | None:
    """Always BOTH filters (schema §4.8): a layout is personal."""
    return await _first(
        session,
        select(WidgetLayout).where(
            WidgetLayout.project_id == project_id, WidgetLayout.user_id == user_id
        ),
    )
