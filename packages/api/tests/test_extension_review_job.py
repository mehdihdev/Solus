"""The automated extension review job (SOLUSDEV-235 / ADR-035 §5, EXT-08).

`run_review` is the pure core (session + store + version id in, final status out);
`extension_review` is the ARQ entrypoint that never raises. Pins the state machine
of docs/schemas/extensions.md §5: `pending → checking → approved | rejected`, the
store-facing asset extraction of §4.4 (icon stored SANITIZED), the highest-semver
recompute of `latest_approved_version_id`, idempotency, and the internal-error →
`rejected` posture.
"""

from __future__ import annotations

import hashlib
import tomllib
import uuid
from typing import Any

import pytest
from fixtures.extensions import (
    FULL_MANIFEST_TOML,
    MINIMAL_MANIFEST_TOML,
    build_zip,
    full_files,
    minimal_files,
    with_manifest,
)
from solus_api.connectors.worker import build_worker_settings
from solus_api.core.config import Settings
from solus_api.extensions import review as review_module
from solus_api.extensions.bundle import BundleReport
from solus_api.extensions.review import (
    INTERNAL_ERROR_PROBLEM,
    MAX_PROBLEM_CHARS,
    MAX_PROBLEMS,
    extension_review,
    run_review,
    semver_key,
)
from solus_api.models import (
    ArtifactStorage,
    DataEvent,
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
)
from solus_api.storage import ArtifactNotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.usefixtures("_schema")


# ------------------------------------------------------------------ fakes
class FakeStore:
    """In-memory `ArtifactStore`: the review job reads the bundle and writes assets here."""

    backend = ArtifactStorage.LOCAL

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        try:
            return self.blobs[key]
        except KeyError as exc:
            raise ArtifactNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)


class ExplodingStore(FakeStore):
    async def get(self, key: str) -> bytes:
        raise RuntimeError("storage backend on fire")


# ---------------------------------------------------------------- seeding
async def _seed(
    db: AsyncSession, *, with_user: bool = True, consent: bool = True
) -> tuple[Extension, ExtensionPublisher]:
    user_id: uuid.UUID | None = None
    if with_user:
        user = User(
            supabase_user_id="sub-publisher",
            email="ada@example.com",
            data_collection_consent=consent,
        )
        db.add(user)
        await db.flush()
        user_id = user.id
    publisher = ExtensionPublisher(user_id=user_id, display_name="Ada")
    db.add(publisher)
    await db.flush()
    extension = Extension(slug="bom", publisher_id=publisher.id, name="old", summary="old.")
    db.add(extension)
    await db.commit()
    return extension, publisher


def _manifest_of(files: dict[str, bytes]) -> dict[str, Any]:
    return tomllib.loads(files["extension.toml"].decode())


async def _publish(
    db: AsyncSession,
    store: FakeStore,
    extension: Extension,
    files: dict[str, bytes],
    *,
    semver: str | None = None,
    status: ExtensionReviewStatus = ExtensionReviewStatus.PENDING,
    store_bytes: bool = True,
) -> ExtensionVersion:
    data = build_zip(files)
    manifest = _manifest_of(files)
    version = ExtensionVersion(
        extension_id=extension.id,
        version=semver or manifest["extension"]["version"],
        manifest=manifest,
        bundle_storage=store.backend,
        content_hash=hashlib.sha256(data).hexdigest(),
        bundle_size_bytes=len(data),
        review_status=status,
    )
    db.add(version)
    await db.commit()
    if store_bytes:
        await store.put(str(version.id), data)
    return version


def _ctx(engine: AsyncEngine, store: FakeStore) -> dict[str, Any]:
    return {
        "sessionmaker": async_sessionmaker(engine, expire_on_commit=False),
        "artifact_store": store,
    }


async def _reload(db: AsyncSession, version: ExtensionVersion) -> ExtensionVersion:
    await db.refresh(version)
    return version


async def _assets(db: AsyncSession, version: ExtensionVersion) -> dict[str, ExtensionVersionAsset]:
    rows = await db.scalars(
        select(ExtensionVersionAsset).where(ExtensionVersionAsset.version_id == version.id)
    )
    return {row.path: row for row in rows}


async def _events(db: AsyncSession, event_type: str = "extension.review_completed") -> list[Any]:
    rows = await db.scalars(select(DataEvent).where(DataEvent.event_type == event_type))
    return list(rows)


# ------------------------------------------------------------ rejections
async def test_path_traversal_entry_is_rejected(db: AsyncSession, engine: AsyncEngine) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(db, store, extension, {**minimal_files(), "../escape.js": b"x"})

    result = await extension_review(_ctx(engine, store), str(version.id))

    assert result == "rejected"
    row = await _reload(db, version)
    assert row.review_status is ExtensionReviewStatus.REJECTED
    assert any("escape.js" in p and "traversal" in p for p in row.review_problems)
    assert row.published_at is None
    assert await _assets(db, row) == {}
    await db.refresh(extension)
    ext = extension
    assert ext is not None and ext.latest_approved_version_id is None


async def test_remote_script_in_entry_is_rejected(db: AsyncSession, engine: AsyncEngine) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    evil = b'<html><script src="https://evil.example/x.js"></script></html>'
    version = await _publish(db, store, extension, {**minimal_files(), "widget.html": evil})

    await extension_review(_ctx(engine, store), str(version.id))

    row = await _reload(db, version)
    assert row.review_status is ExtensionReviewStatus.REJECTED
    assert any(p.startswith("widget.html:1: remote script") for p in row.review_problems)


async def test_bad_icon_svg_is_rejected_and_nothing_is_stored(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    bad_icon = b'<svg xmlns="http://www.w3.org/2000/svg" onload="steal()"/>'
    version = await _publish(db, store, extension, {**full_files(), "icon.svg": bad_icon})

    await extension_review(_ctx(engine, store), str(version.id))

    row = await _reload(db, version)
    assert row.review_status is ExtensionReviewStatus.REJECTED
    assert any(p.startswith("icon.svg: ") and "onload" in p for p in row.review_problems)
    assert set(store.blobs) == {str(version.id)}, "only the bundle itself lives in the store"


async def test_rejection_emits_the_event_with_the_problem_count(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(db, store, extension, {**minimal_files(), "../escape.js": b"x"})

    await extension_review(_ctx(engine, store), str(version.id))

    (event,) = await _events(db)
    row = await _reload(db, version)
    assert event.payload["slug"] == "bom"
    assert event.payload["version"] == "1.0.0"
    assert event.payload["review_status"] == "rejected"
    assert event.payload["problem_count"] == len(row.review_problems) > 0
    assert isinstance(event.payload["duration_ms"], int)


# -------------------------------------------------------------- approval
async def test_valid_bundle_is_approved_with_assets_and_latest(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    files = full_files()
    version = await _publish(db, store, extension, files)

    result = await extension_review(_ctx(engine, store), str(version.id))

    assert result == "approved"
    row = await _reload(db, version)
    assert row.review_status is ExtensionReviewStatus.APPROVED
    assert row.review_problems == []
    assert row.published_at is not None

    assets = await _assets(db, row)
    assert set(assets) == {
        "OVERVIEW.md",
        "PRIVACY.md",
        "docs/HOW.md",
        "shots/table.png",
        "shots/finding.webp",
        "icon.svg",
    }
    for path in ("OVERVIEW.md", "PRIVACY.md", "docs/HOW.md", "shots/table.png"):
        asset = assets[path]
        assert asset.storage_key == asset.id
        assert asset.storage is ArtifactStorage.LOCAL
        assert store.blobs[str(asset.id)] == files[path]
        assert asset.size_bytes == len(files[path])
    assert assets["OVERVIEW.md"].media_type == "text/markdown"
    assert assets["shots/table.png"].media_type == "image/png"
    assert assets["shots/finding.webp"].media_type == "image/webp"
    assert assets["icon.svg"].media_type == "image/svg+xml"

    await db.refresh(extension)
    assert extension.latest_approved_version_id == row.id
    assert extension.name == "BOM"
    assert extension.summary == "Bill of materials from your EDA project."

    (event,) = await _events(db)
    assert event.payload["review_status"] == "approved"
    assert event.payload["problem_count"] == 0


async def test_icon_is_stored_sanitized(db: AsyncSession, engine: AsyncEngine) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(db, store, extension, full_files())

    await extension_review(_ctx(engine, store), str(version.id))

    icon = (await _assets(db, version))["icon.svg"]
    stored = store.blobs[str(icon.id)]
    assert b"currentColor" in stored
    assert b"#fff" not in stored
    assert b"<?xml" not in stored
    assert icon.size_bytes == len(stored)


async def test_latest_is_the_highest_semver_even_when_approved_out_of_order(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    newer_toml = FULL_MANIFEST_TOML.replace('name = "BOM"', 'name = "BOM Pro"')
    newer = await _publish(db, store, extension, with_manifest(full_files(), newer_toml))
    older = await _publish(db, store, extension, minimal_files())
    ctx = _ctx(engine, store)

    await extension_review(ctx, str(newer.id))
    await extension_review(ctx, str(older.id))

    await db.refresh(extension)
    ext = extension
    assert ext is not None
    assert (await _reload(db, older)).review_status is ExtensionReviewStatus.APPROVED
    assert ext.latest_approved_version_id == newer.id
    assert ext.name == "BOM Pro"


async def test_a_withdrawn_or_rejected_version_never_becomes_latest(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    live = await _publish(db, store, extension, minimal_files())
    withdrawn = await _publish(
        db,
        store,
        extension,
        full_files(),
        status=ExtensionReviewStatus.APPROVED,
    )
    withdrawn.deleted_at = withdrawn.created_at
    await db.commit()

    await extension_review(_ctx(engine, store), str(live.id))

    await db.refresh(extension)
    ext = extension
    assert ext is not None and ext.latest_approved_version_id == live.id


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.0.0", "1.0.1"),
        ("1.9.0", "1.10.0"),
        ("1.0.0-alpha", "1.0.0"),
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
        ("1.0.0-beta.2", "1.0.0-beta.11"),
        ("1.0.0-rc.1", "1.0.0"),
        ("1.2.0", "2.0.0-beta.1"),
    ],
)
def test_semver_key_orders_like_the_spec(lower: str, higher: str) -> None:
    assert semver_key(lower) < semver_key(higher)


def test_semver_key_ignores_build_metadata() -> None:
    assert semver_key("1.0.0+build.7") == semver_key("1.0.0")


# ----------------------------------------------------------- idempotency
async def test_rerun_on_an_approved_version_is_a_noop(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(db, store, extension, full_files())
    ctx = _ctx(engine, store)

    assert await extension_review(ctx, str(version.id)) == "approved"
    first = await _reload(db, version)
    published_at = first.published_at
    blobs_after_first = dict(store.blobs)

    assert await extension_review(ctx, str(version.id)) == "approved"

    second = await _reload(db, version)
    assert second.published_at == published_at
    assert len(await _assets(db, second)) == 6
    assert store.blobs == blobs_after_first
    assert len(await _events(db)) == 1


async def test_rerun_on_a_rejected_version_is_a_noop(db: AsyncSession, engine: AsyncEngine) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(
        db, store, extension, full_files(), status=ExtensionReviewStatus.REJECTED
    )

    assert await extension_review(_ctx(engine, store), str(version.id)) == "rejected"

    assert (await _reload(db, version)).published_at is None
    assert await _events(db) == []


async def test_a_crashed_checking_run_is_recovered_without_duplicate_assets(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(
        db, store, extension, full_files(), status=ExtensionReviewStatus.CHECKING
    )
    db.add(
        ExtensionVersionAsset(
            version_id=version.id,
            path="OVERVIEW.md",
            storage=ArtifactStorage.LOCAL,
            media_type="text/markdown",
            size_bytes=1,
        )
    )
    await db.commit()

    assert await extension_review(_ctx(engine, store), str(version.id)) == "approved"

    assets = await _assets(db, version)
    assert len(assets) == 6
    assert assets["OVERVIEW.md"].size_bytes == len(full_files()["OVERVIEW.md"])


# ------------------------------------------------------------- failures
@pytest.mark.parametrize("store_factory", [FakeStore, ExplodingStore])
async def test_internal_errors_reject_and_never_raise(
    db: AsyncSession, engine: AsyncEngine, store_factory: type[FakeStore]
) -> None:
    store = store_factory()
    extension, _ = await _seed(db)
    # FakeStore: bytes never stored → ArtifactNotFoundError; ExplodingStore: RuntimeError.
    version = await _publish(db, store, extension, minimal_files(), store_bytes=False)

    result = await extension_review(_ctx(engine, store), str(version.id))

    assert result == "rejected"
    row = await _reload(db, version)
    assert row.review_status is ExtensionReviewStatus.REJECTED
    assert row.review_problems == [INTERNAL_ERROR_PROBLEM]
    assert row.published_at is None


async def test_unknown_version_returns_empty_without_raising(engine: AsyncEngine) -> None:
    assert await extension_review(_ctx(engine, FakeStore()), str(uuid.uuid4())) == ""


async def test_malformed_version_id_returns_empty_without_raising(engine: AsyncEngine) -> None:
    assert await extension_review(_ctx(engine, FakeStore()), "not-a-uuid") == ""


async def test_problems_are_capped_in_count_and_length(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(db, store, extension, minimal_files())
    flood = [f"p{i}: " + "x" * 2000 for i in range(MAX_PROBLEMS + 50)]
    monkeypatch.setattr(
        review_module,
        "inspect_bundle",
        lambda data: BundleReport(False, flood, None, "0" * 64, len(data)),
    )

    async with _ctx(engine, store)["sessionmaker"]() as session:
        await run_review(session, store, version.id)

    row = await _reload(db, version)
    assert row.review_status is ExtensionReviewStatus.REJECTED
    assert len(row.review_problems) == MAX_PROBLEMS
    assert all(len(p) <= MAX_PROBLEM_CHARS for p in row.review_problems)
    assert row.review_problems[0].startswith("p0: ")


# --------------------------------------------------------------- events
async def test_event_is_skipped_when_the_publisher_has_no_user(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db, with_user=False)
    version = await _publish(db, store, extension, minimal_files())

    assert await extension_review(_ctx(engine, store), str(version.id)) == "approved"
    assert await _events(db) == []


async def test_event_respects_consent(db: AsyncSession, engine: AsyncEngine) -> None:
    store = FakeStore()
    extension, _ = await _seed(db, consent=False)
    version = await _publish(db, store, extension, minimal_files())

    assert await extension_review(_ctx(engine, store), str(version.id)) == "approved"
    assert await _events(db) == []


async def test_minimal_manifest_produces_only_the_overview_asset(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = FakeStore()
    extension, _ = await _seed(db)
    version = await _publish(db, store, extension, minimal_files())

    await extension_review(_ctx(engine, store), str(version.id))

    assert set(await _assets(db, version)) == {"OVERVIEW.md"}
    assert _manifest_of(minimal_files()) == tomllib.loads(MINIMAL_MANIFEST_TOML)


# --------------------------------------------------------------- wiring
def test_extension_review_is_registered_with_the_arq_worker(settings: Settings) -> None:
    worker: Any = build_worker_settings(settings)
    assert extension_review in worker.functions
