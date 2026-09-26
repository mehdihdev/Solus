"""Durable BOM provisioning uses the normal immutable publishing/review lifecycle."""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
from pathlib import Path

import pytest
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.extensions.first_party_catalog import ensure_bom_catalog
from solus_api.models import Extension, ExtensionReviewStatus, ExtensionVersion, User, utcnow
from solus_api.storage.artifact_store import LocalArtifactStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.usefixtures("_schema")


@pytest.fixture
def bundle() -> bytes:
    root = Path(__file__).resolve().parents[1] / "src/solus_api/extensions/bundled/bom"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.writestr(path.relative_to(root).as_posix(), path.read_bytes())
    return output.getvalue()


@pytest.fixture
async def publisher(db: AsyncSession) -> uuid.UUID:
    user = User(supabase_user_id=uuid.uuid4().hex, email="publisher@example.test")
    db.add(user)
    await db.commit()
    return user.id


async def provision(
    engine: AsyncEngine, tmp_path: Path, settings: Settings, publisher: uuid.UUID, bundle: bytes
) -> uuid.UUID:
    return await ensure_bom_catalog(
        async_sessionmaker(engine, expire_on_commit=False),
        LocalArtifactStore(str(tmp_path)),
        settings.model_copy(update={"staff_user_ids": str(publisher)}),
        publisher,
        bundle,
    )


async def test_publishes_once_under_concurrent_startup(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
) -> None:
    ids = await asyncio.gather(
        *(provision(engine, tmp_path, settings, publisher, bundle) for _ in range(3))
    )
    assert len(set(ids)) == 1
    version = await db.get(ExtensionVersion, ids[0])
    assert version is not None and version.review_status == ExtensionReviewStatus.APPROVED
    extension = await db.get(Extension, version.extension_id)
    assert extension is not None and extension.latest_approved_version_id == version.id
    assert await db.scalar(select(func.count()).select_from(ExtensionVersion)) == 1
    assert await LocalArtifactStore(str(tmp_path)).get(str(version.id)) == bundle


@pytest.mark.parametrize("kind", ["nonstaff", "missing", "deleted"])
async def test_requires_existing_staff(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
    kind: str,
) -> None:
    if kind == "missing":
        publisher = uuid.uuid4()
    if kind == "deleted":
        user = await db.get(User, publisher)
        assert user is not None
        user.deleted_at = utcnow()
        await db.commit()
    configured = settings.model_copy(
        update={"staff_user_ids": "" if kind == "nonstaff" else str(publisher)}
    )
    with pytest.raises(APIError):
        await ensure_bom_catalog(
            async_sessionmaker(engine),
            LocalArtifactStore(str(tmp_path)),
            configured,
            publisher,
            bundle,
        )
    assert await db.scalar(select(func.count()).select_from(Extension)) == 0


@pytest.mark.parametrize("kind", ["withdrawn", "rejected", "hash", "missing_bytes", "foreign"])
async def test_existing_conflicts_never_resurrect_or_overwrite(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
    kind: str,
) -> None:
    version_id = await provision(engine, tmp_path, settings, publisher, bundle)
    version = await db.get(ExtensionVersion, version_id)
    assert version is not None
    if kind == "withdrawn":
        version.deleted_at = utcnow()
    elif kind == "rejected":
        version.review_status = ExtensionReviewStatus.REJECTED
    elif kind == "hash":
        version.content_hash = "a" * 64
    elif kind == "missing_bytes":
        await LocalArtifactStore(str(tmp_path)).delete(str(version_id))
    else:
        other = User(supabase_user_id=uuid.uuid4().hex, email="other@example.test")
        db.add(other)
        await db.flush()
        publisher = other.id
    await db.commit()
    with pytest.raises(APIError):
        await provision(engine, tmp_path, settings, publisher, bundle)
    assert await db.scalar(select(func.count()).select_from(ExtensionVersion)) == 1


@pytest.mark.parametrize("status", [ExtensionReviewStatus.PENDING, ExtensionReviewStatus.CHECKING])
async def test_resumes_interrupted_review(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
    status: ExtensionReviewStatus,
) -> None:
    version_id = await provision(engine, tmp_path, settings, publisher, bundle)
    version = await db.get(ExtensionVersion, version_id)
    assert version is not None
    version.review_status = status
    await db.commit()
    assert await provision(engine, tmp_path, settings, publisher, bundle) == version_id
    await db.refresh(version)
    assert version.review_status == ExtensionReviewStatus.APPROVED


async def test_health_requires_retained_approved_bytes(
    engine: AsyncEngine, tmp_path: Path, settings: Settings, publisher: uuid.UUID, bundle: bytes
) -> None:
    from solus_api.extensions.first_party_catalog import check_bom_catalog

    maker = async_sessionmaker(engine)
    store = LocalArtifactStore(str(tmp_path))
    with pytest.raises(APIError):
        await check_bom_catalog(maker, store)
    version_id = await provision(engine, tmp_path, settings, publisher, bundle)
    await check_bom_catalog(maker, store)
    await store.put(str(version_id), b"corrupted")
    with pytest.raises(APIError):
        await check_bom_catalog(maker, store)


async def test_preserves_disabled_install_settings_and_account_pin(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
) -> None:
    from solus_api.models import ExtensionInstall, Project, Team, TeamKind, UserExtensionPin

    version_id = await provision(engine, tmp_path, settings, publisher, bundle)
    version = await db.get(ExtensionVersion, version_id)
    assert version is not None
    team = Team(name="Robot team", kind=TeamKind.COLLABORATIVE)
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="Robot", created_by=publisher)
    db.add(project)
    await db.flush()
    install = ExtensionInstall(
        project_id=project.id,
        extension_id=version.extension_id,
        version_id=version_id,
        enabled=False,
        settings={"currency": "EUR"},
        installed_by=publisher,
    )
    pin = UserExtensionPin(user_id=publisher, extension_id=version.extension_id)
    db.add_all([install, pin])
    await db.commit()
    assert await provision(engine, tmp_path, settings, publisher, bundle) == version_id
    await db.refresh(install)
    assert install.enabled is False and install.settings == {"currency": "EUR"}
    assert install.version_id == version_id
    assert await db.get(UserExtensionPin, pin.id) is not None


async def test_invalid_bundle_does_not_claim_slug(
    engine: AsyncEngine, db: AsyncSession, tmp_path: Path, settings: Settings, publisher: uuid.UUID
) -> None:
    with pytest.raises(APIError, match="validation"):
        await provision(engine, tmp_path, settings, publisher, b"not a zip")
    assert await db.scalar(select(func.count()).select_from(Extension)) == 0


@pytest.mark.parametrize("damage", ["row", "bytes", "corrupt", "media", "size"])
async def test_health_rejects_missing_or_corrupted_store_assets(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
    damage: str,
) -> None:
    from solus_api.extensions.first_party_catalog import check_bom_catalog
    from solus_api.models import ExtensionVersionAsset

    version_id = await provision(engine, tmp_path, settings, publisher, bundle)
    store = LocalArtifactStore(str(tmp_path))
    asset = await db.scalar(
        select(ExtensionVersionAsset).where(
            ExtensionVersionAsset.version_id == version_id, ExtensionVersionAsset.path == "icon.svg"
        )
    )
    assert asset is not None
    if damage == "row":
        await db.delete(asset)
    elif damage == "bytes":
        await store.delete(str(asset.storage_key))
    elif damage == "corrupt":
        await store.put(str(asset.storage_key), b"x" * asset.size_bytes)
    elif damage == "media":
        asset.media_type = "text/html"
    else:
        asset.size_bytes += 1
    await db.commit()
    with pytest.raises(APIError, match="asset"):
        await check_bom_catalog(async_sessionmaker(engine), store)


async def test_health_refuses_null_catalog_pointer(
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    publisher: uuid.UUID,
    bundle: bytes,
) -> None:
    from solus_api.extensions.first_party_catalog import check_bom_catalog

    version_id = await provision(engine, tmp_path, settings, publisher, bundle)
    version = await db.get(ExtensionVersion, version_id)
    assert version is not None
    extension = await db.get(Extension, version.extension_id)
    assert extension is not None
    extension.latest_approved_version_id = None
    await db.commit()
    with pytest.raises(APIError, match="not published"):
        await check_bom_catalog(async_sessionmaker(engine), LocalArtifactStore(str(tmp_path)))
    await db.refresh(extension)
    assert extension.latest_approved_version_id is None
