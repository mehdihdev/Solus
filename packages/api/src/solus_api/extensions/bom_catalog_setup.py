"""Ship and provision the official BOM release through the existing registry."""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from importlib.resources import files

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.core.config import Settings
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.extensions.first_party_catalog import check_bom_catalog, ensure_bom_catalog
from solus_api.storage import ArtifactStore, build_artifact_store

logger = logging.getLogger("solus.extensions.bom_catalog_setup")
_BUNDLE_FILES = ("OVERVIEW.md", "extension.toml", "icon.svg", "page.css", "page.html")


def bom_bundle() -> bytes:
    """Deterministic release bytes from the installed API package.

    Only fixed reviewed files are included; no user path or directory traversal.
    ZIP_STORED avoids compression-library-dependent immutable release hashes.
    """
    root = files("solus_api.extensions").joinpath("bundled", "bom")
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in _BUNDLE_FILES:
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.external_attr = 0o100644 << 16
            archive.writestr(member, root.joinpath(name).read_bytes())
    return result.getvalue()


async def prepare_catalog(
    sessionmaker: async_sessionmaker[AsyncSession], store: ArtifactStore, settings: Settings
) -> None:
    """Reconcile when explicitly configured; otherwise check existing publication."""
    if settings.first_party_publisher_id is not None:
        async with asyncio.timeout(60):
            await ensure_bom_catalog(
                sessionmaker, store, settings, settings.first_party_publisher_id, bom_bundle()
            )
            await check_bom_catalog(sessionmaker, store)
        logger.info("Official BOM release is available in the Store")
        return
    try:
        async with asyncio.timeout(60):
            await check_bom_catalog(sessionmaker, store)
    except Exception:
        if settings.app_env != "dev":
            raise
        logger.warning(
            "BOM Store listing unavailable: configure SOLUS_FIRST_PARTY_PUBLISHER_ID "
            "and authorize that existing account in SOLUS_STAFF_USER_IDS, then run "
            "python -m solus_api.extensions.bom_catalog_setup with persistent artifact storage"
        )


async def _run() -> None:
    settings = Settings()  # type: ignore[call-arg]  # runtime environment
    engine = build_engine(settings.database_url)
    try:
        # The explicit operator command fails even in dev if publication is absent.
        sessions = build_sessionmaker(engine, settings=settings)
        store = build_artifact_store(settings)
        await prepare_catalog(sessions, store, settings)
        await check_bom_catalog(sessions, store)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
