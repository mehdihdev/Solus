"""Provision the bundled BOM through ordinary staff publishing and automated review.

No installs, grants, pins, settings, verification badges or account roles are changed.
The PostgreSQL session lock spans review commits and serializes concurrent bootstraps.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from solus_contracts.extension_manifest import LIMITS, ExtensionManifest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.extensions.bundle import inspect_bundle, inspect_bundle_structure, read_member
from solus_api.extensions.publishing import claim_extension, create_version, get_or_create_publisher
from solus_api.extensions.review import run_review
from solus_api.extensions.svg import sanitize_svg
from solus_api.models import (
    Extension,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
)
from solus_api.services.events import emit_event
from solus_api.storage.artifact_store import ArtifactNotFoundError, ArtifactStore
from solus_api.storage.extension_bundle_store import ExtensionBundleStore
from solus_api.widgets.publish_gate import first_party_problems
from solus_api.widgets.registry import discover_capabilities

_LOCK = 0x534F4C5553424F4D


def _conflict(message: str) -> APIError:
    return APIError(409, "first_party_catalog_conflict", message)


async def _retained(store: ArtifactStore, version: ExtensionVersion) -> bytes:
    if store.backend != version.bundle_storage:
        raise _conflict("BOM bundle storage backend differs from the retained version")
    try:
        data = await store.get(str(version.id))
    except ArtifactNotFoundError as exc:
        raise _conflict("BOM bundle bytes are missing from storage") from exc
    if (
        hashlib.sha256(data).hexdigest() != version.content_hash
        or len(data) != version.bundle_size_bytes
    ):
        raise _conflict("BOM retained bundle bytes do not match the immutable version")

    return data


async def _assets(
    session: AsyncSession, store: ArtifactStore, version: ExtensionVersion, data: bytes
) -> None:
    report = inspect_bundle(data)
    if not report.ok:
        raise _conflict("BOM retained bundle assets fail validation")
    rows = (
        await session.scalars(
            select(ExtensionVersionAsset).where(ExtensionVersionAsset.version_id == version.id)
        )
    ).all()
    actual = {row.path: row for row in rows}
    expected = {asset.path: asset for asset in report.assets}
    if actual.keys() != expected.keys():
        raise _conflict("BOM catalog asset records are missing or unexpected")
    for path, asset in expected.items():
        row = actual[path]
        payload = read_member(data, path, max_bytes=asset.size_bytes)
        if asset.media_type == "image/svg+xml":
            payload = sanitize_svg(payload, LIMITS.icon_bytes).encode("utf-8")
        if (
            row.storage != store.backend
            or row.media_type != asset.media_type
            or row.size_bytes != len(payload)
        ):
            raise _conflict("BOM catalog asset metadata does not match the bundle")
        try:
            retained = await store.get(str(row.storage_key))
        except ArtifactNotFoundError as exc:
            raise _conflict("BOM catalog asset bytes are missing") from exc
        if retained != payload:
            raise _conflict("BOM catalog asset bytes do not match the bundle")


async def check_bom_catalog(
    sessionmaker: async_sessionmaker[AsyncSession], store: ArtifactStore
) -> None:
    """Read-only readiness check; never requires or promotes a staff identity."""
    async with sessionmaker() as session:
        extension = await session.scalar(select(Extension).where(Extension.slug == "bom"))
        if (
            extension is None
            or extension.deleted_at is not None
            or extension.latest_approved_version_id is None
        ):
            raise _conflict("BOM is not published; configure the first-party catalog publisher")
        version = await session.get(ExtensionVersion, extension.latest_approved_version_id)
        if (
            version is None
            or version.extension_id != extension.id
            or version.deleted_at is not None
            or version.review_status != ExtensionReviewStatus.APPROVED
        ):
            raise _conflict("BOM has no live approved catalog version")
        data = await _retained(store, version)
        await _assets(session, store, version, data)


async def ensure_bom_catalog(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    settings: Settings,
    publisher_id: UUID,
    bundle: bytes,
) -> UUID:
    """Idempotently publish/review trusted packaged bytes, or fail on any conflict."""
    if publisher_id not in settings.staff_user_id_set:
        raise APIError(
            403, "staff_required", "BOM publisher must be explicitly configured as staff"
        )
    report = inspect_bundle_structure(bundle)
    if not report.ok or report.manifest is None:
        raise APIError(
            422, "bundle_invalid", "Bundled BOM failed validation", details=report.problems
        )
    manifest = report.manifest
    if manifest.extension.id != "bom" or manifest.backend is None:
        raise _conflict("Bundled catalog entry must declare the BOM capability")
    if problems := first_party_problems(
        manifest, is_staff=True, capabilities=discover_capabilities()
    ):
        raise APIError(422, "bundle_invalid", "Bundled BOM capability is invalid", details=problems)
    engine = sessionmaker.kw.get("bind")
    if not isinstance(engine, AsyncEngine):
        raise TypeError("BOM provisioning requires a session factory bound to an AsyncEngine")
    async with engine.connect() as connection:
        try:
            await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _LOCK})
            await connection.commit()
            async with AsyncSession(connection, expire_on_commit=False) as session:
                return await _publish(session, store, publisher_id, bundle, manifest)
        finally:
            try:
                await connection.rollback()
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK})
                await connection.commit()
            except BaseException:
                # Never return a connection holding a session lock to the pool.
                await connection.invalidate()
                raise


async def _publish(
    session: AsyncSession,
    store: ArtifactStore,
    publisher_id: UUID,
    bundle: bytes,
    manifest: ExtensionManifest,
) -> UUID:
    user = await session.get(User, publisher_id)
    if user is None or user.deleted_at is not None:
        raise APIError(403, "staff_required", "BOM publisher must be an existing active account")
    publisher = await get_or_create_publisher(
        session, user_id=user.id, display_name=manifest.extension.publisher, is_staff=True
    )
    extension = await claim_extension(session, publisher=publisher, manifest=manifest)
    if extension.deleted_at is not None:
        raise _conflict("BOM was withdrawn; provisioning cannot restore it")
    version = await session.scalar(
        select(ExtensionVersion).where(
            ExtensionVersion.extension_id == extension.id,
            ExtensionVersion.version == manifest.extension.version,
        )
    )
    digest = hashlib.sha256(bundle).hexdigest()
    if version is None:
        version = await create_version(
            session,
            ExtensionBundleStore(store),
            extension=extension,
            manifest=manifest,
            data=bundle,
            content_hash=digest,
        )
        emit_event(
            session,
            user=user,
            event_type="extension.publish",
            payload={
                "slug": extension.slug,
                "version": version.version,
                "bundle_size_bytes": version.bundle_size_bytes,
                "content_hash": digest,
            },
        )
        await session.commit()
    else:
        if (
            version.deleted_at is not None
            or version.review_status == ExtensionReviewStatus.REJECTED
        ):
            raise _conflict(
                "BOM version was withdrawn or rejected; publish a new version explicitly"
            )
        if version.content_hash != digest:
            raise _conflict("BOM version already exists with different immutable bundle bytes")
        data = await _retained(store, version)
        if version.review_status == ExtensionReviewStatus.APPROVED:
            await _assets(session, store, version, data)
    version_id = version.id
    if await run_review(session, store, version_id) != ExtensionReviewStatus.APPROVED:
        raise _conflict("Bundled BOM did not pass automated review")
    await session.commit()
    return version_id
