"""Shared helpers for the EXT-09 project-install route suites (SOLUSDEV-235).

A plain module, not a conftest: the install / permissions / isolation /
settings-values / widget-layout suites all seed the same catalog rows, mount the
same router and call the same routes, and previously imported these from one
sibling test module (Phase 4 REV-MEDIUM). Nothing here is a pytest fixture —
each suite keeps its own `app` fixture built from :func:`installs_app`.
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conftest import API_DIR, create_project, create_team
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.runtime import ScaffoldRunner
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.models import (
    ArtifactStorage,
    DataEvent,
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    TeamExtensionPolicy,
    User,
    utcnow,
)
from solus_api.routers.extensions import installs as installs_router
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

FIXTURE = API_DIR.parent / "shared-types" / "fixtures" / "extension-manifest" / "manifest-full.json"
MANIFEST: dict[str, Any] = json.loads(Path(FIXTURE).read_text())
SHA256_HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
FULL_GRANTS = {"scopes": ["graph.read", "sources.read"], "network": ["https://api.octopart.com"]}


# ------------------------------------------------------------------ fixtures
def installs_app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    """The EXT-09 router mounted directly — the aggregator include lands at
    integration (test_extension_router_wiring pins that seam). Sibling suites
    override their own `app` fixture with this; conftest's `client` follows."""
    application = create_app(settings=settings, engine=engine)
    application.state.agent_runner = ScaffoldRunner()
    application.include_router(installs_router.router)
    return application


# ------------------------------------------------------------------- helpers
def manifest_with(
    version: str = "1.2.0",
    *,
    slug: str = "bom",
    scopes: list[str] | None = None,
    network: list[str] | None = None,
    settings_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The full fixture manifest with the bits a test varies swapped in."""
    manifest = deepcopy(MANIFEST)
    manifest["extension"]["id"] = slug
    manifest["extension"]["version"] = version
    if scopes is not None:
        manifest["permissions"]["scopes"] = scopes
    if network is not None:
        manifest["permissions"]["network"] = network
    if settings_fields is not None:
        manifest["settings"]["fields"] = settings_fields
    return manifest


@dataclass(frozen=True)
class Catalog:
    extension_id: uuid.UUID
    slug: str
    versions: dict[str, uuid.UUID]


async def seed_extension(
    db: AsyncSession,
    slug: str = "bom",
    versions: dict[str, dict[str, Any]] | None = None,
    *,
    pending: tuple[str, ...] = (),
) -> Catalog:
    """A published extension with approved `versions` (semver → manifest); the
    LAST approved one becomes `latest_approved_version_id`. `pending` semvers
    are added unapproved (never installable)."""
    versions = versions or {"1.2.0": manifest_with("1.2.0", slug=slug)}
    publisher = ExtensionPublisher(display_name="Solus")
    db.add(publisher)
    await db.flush()
    extension = Extension(slug=slug, publisher_id=publisher.id, name="BOM", summary="Bill.")
    db.add(extension)
    await db.flush()
    ids: dict[str, uuid.UUID] = {}
    for semver, manifest in versions.items():
        row = ExtensionVersion(
            extension_id=extension.id,
            version=semver,
            manifest=manifest,
            bundle_storage=ArtifactStorage.LOCAL,
            content_hash=SHA256_HEX,
            bundle_size_bytes=1024,
            review_status=ExtensionReviewStatus.APPROVED,
            published_at=utcnow(),
        )
        db.add(row)
        await db.flush()
        ids[semver] = row.id
    for semver in pending:
        db.add(
            ExtensionVersion(
                extension_id=extension.id,
                version=semver,
                manifest=manifest_with(semver, slug=slug),
                bundle_storage=ArtifactStorage.LOCAL,
                content_hash=SHA256_HEX,
                bundle_size_bytes=1024,
            )
        )
    extension.latest_approved_version_id = ids[list(versions)[-1]]
    await db.commit()
    return Catalog(extension.id, slug, ids)


async def seed_policy(
    db: AsyncSession, team_id: str, extension_id: uuid.UUID, **fields: Any
) -> None:
    db.add(TeamExtensionPolicy(team_id=uuid.UUID(team_id), extension_id=extension_id, **fields))
    await db.commit()


async def consent(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(User).where(User.id == uuid.UUID(user_id)).values(data_collection_consent=True)
    )
    await db.commit()


async def events_of(db: AsyncSession, event_type: str) -> list[DataEvent]:
    rows = await db.scalars(select(DataEvent).where(DataEvent.event_type == event_type))
    return list(rows.all())


async def project_for(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    """`(team_id, project_id)` owned by the caller."""
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return team["id"], project["id"]


def ext_url(project_id: str, slug: str = "") -> str:
    base = f"/api/v1/projects/{project_id}/extensions"
    return f"{base}/{slug}" if slug else base


async def install(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    slug: str = "bom",
    grants: dict[str, list[str]] | None = None,
    version: str | None = None,
) -> Any:
    body: dict[str, Any] = {"grants": grants if grants is not None else FULL_GRANTS}
    if version:
        body["version"] = version
    return await client.put(ext_url(project_id, slug), json=body, headers=headers)


__all__ = [
    "FULL_GRANTS",
    "MANIFEST",
    "SHA256_HEX",
    "Catalog",
    "consent",
    "events_of",
    "ext_url",
    "install",
    "installs_app",
    "manifest_with",
    "project_for",
    "seed_extension",
    "seed_policy",
]
