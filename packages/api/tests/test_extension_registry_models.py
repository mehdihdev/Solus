"""Extension registry schema seam (SOLUSDEV-235 / ADR-035, task EXT-03).

Pins `docs/schemas/extensions.md` column for column: the migration round-trips,
the eight tables carry the documented keys, FKs, CHECKs and unique indexes, the
`credit_ledger` / `jobs` amendments hold, and the `RequireStaff` dependency admits
exactly the settings-listed ids.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from conftest import API_DIR, TEST_DATABASE_URL, TEST_JWT_SECRET
from pydantic import ValidationError
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.deps import RequireStaff, require_staff
from solus_api.extensions import schemas as ext_schemas
from solus_api.models import (
    EXTENSION_BUNDLE_MAX_BYTES,
    WIDGET_LAYOUT_MAX_SLOTS,
    ArtifactStorage,
    CreditLedger,
    CreditTxnType,
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionStorage,
    ExtensionVersion,
    ExtensionVersionAsset,
    Job,
    JobKind,
    Membership,
    Project,
    Role,
    Team,
    TeamExtensionPolicy,
    User,
    WidgetLayout,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

PREVIOUS_HEAD = "a7d3f9c41e88"
NEW_TABLES = (
    "extension_publishers",
    "extensions",
    "extension_versions",
    "extension_version_assets",
    "extension_installs",
    "extension_storage",
    "team_extension_policies",
    "widget_layouts",
)
SHA256_HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


# ------------------------------------------------------------------ helpers
@dataclass(frozen=True)
class _Fixture:
    user: User
    team: Team
    project: Project
    publisher: ExtensionPublisher
    extension: Extension
    version: ExtensionVersion


async def _seed(db: AsyncSession, slug: str = "bom") -> _Fixture:
    user = User(supabase_user_id=f"sub-{slug}", email=f"{slug}@example.com")
    team = Team(name="Ext")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    publisher = ExtensionPublisher(user_id=user.id, display_name="Ada")
    db.add_all([project, publisher])
    await db.flush()
    extension = Extension(slug=slug, publisher_id=publisher.id, name="BOM", summary="Bill.")
    db.add(extension)
    await db.flush()
    version = _version(extension.id, "1.0.0")
    db.add(version)
    await db.flush()
    return _Fixture(user, team, project, publisher, extension, version)


def _version(extension_id: uuid.UUID, semver: str, **overrides: Any) -> ExtensionVersion:
    fields: dict[str, Any] = {
        "extension_id": extension_id,
        "version": semver,
        "manifest": {"schema_version": 1, "extension": {"id": "bom"}},
        "bundle_storage": ArtifactStorage.LOCAL,
        "content_hash": SHA256_HEX,
        "bundle_size_bytes": 1024,
    }
    fields.update(overrides)
    return ExtensionVersion(**fields)


async def _rejected(db: AsyncSession, action: Callable[[], Awaitable[Any]]) -> None:
    """Run `action` inside a savepoint and require the database to refuse it."""
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await action()


async def _flush_added(db: AsyncSession, *rows: Any) -> None:
    db.add_all(rows)
    await db.flush()


def _raw_dsn() -> str:
    return str(TEST_DATABASE_URL).replace("+asyncpg", "")


async def _fetch_flag(query: str, *args: str) -> bool:
    conn = await asyncpg.connect(_raw_dsn())
    try:
        return bool(await conn.fetchval(query, *args))
    finally:
        await conn.close()


def _table_exists(name: str) -> bool:
    return asyncio.run(_fetch_flag("SELECT to_regclass($1) IS NOT NULL", name))


def _column_exists(table: str, column: str) -> bool:
    return asyncio.run(
        _fetch_flag(
            "SELECT 1 FROM information_schema.columns WHERE table_name = $1 AND column_name = $2",
            table,
            column,
        )
    )


# ------------------------------------------------------------ migration
def test_migration_downgrade_and_reupgrade() -> None:
    """The EXT-03 revision reverses cleanly (every new table and the two amendments
    disappear) and reapplies. Head is restored in `finally` so a mid-test failure
    cannot poison the rest of the session. Sync on purpose: alembic's env.py runs
    its own `asyncio.run`, which cannot nest inside the pytest-asyncio loop."""
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    try:
        command.downgrade(cfg, PREVIOUS_HEAD)
        for table in NEW_TABLES:
            assert not _table_exists(table), table
        assert not _column_exists("credit_ledger", "extension_id")
    finally:
        command.upgrade(cfg, "head")
    for table in NEW_TABLES:
        assert _table_exists(table), table
    assert _column_exists("credit_ledger", "extension_id")


# ---------------------------------------------------------------- catalog
async def test_rows_get_uuid7_primary_keys(db: AsyncSession) -> None:
    fx = await _seed(db)
    for row in (fx.publisher, fx.extension, fx.version):
        assert row.id.version == 7


async def test_slug_is_unique_case_insensitively_even_for_other_publishers(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)
    other = ExtensionPublisher(user_id=None, display_name="Bob")
    db.add(other)
    await db.flush()

    async def _claim_upper() -> None:
        await _flush_added(
            db, Extension(slug="BOM", publisher_id=other.id, name="Bom", summary="dup")
        )

    await _rejected(db, _claim_upper)
    # An unpublished (soft-deleted) row still holds the slug — never re-claimable.
    fx.extension.deleted_at = fx.extension.created_at
    await db.flush()
    await _rejected(db, _claim_upper)


async def test_version_number_is_unique_per_extension(db: AsyncSession) -> None:
    fx = await _seed(db)

    async def _dup() -> None:
        await _flush_added(db, _version(fx.extension.id, "1.0.0"))

    await _rejected(db, _dup)
    # The same number on a DIFFERENT extension is fine.
    sibling = Extension(slug="cam", publisher_id=fx.publisher.id, name="Cam", summary="s")
    db.add(sibling)
    await db.flush()
    await _flush_added(db, _version(sibling.id, "1.0.0"))


async def test_review_status_defaults_to_pending_and_rejects_unknown_values(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)
    assert fx.version.review_status == ExtensionReviewStatus.PENDING
    assert fx.version.review_problems == []

    async def _bogus() -> None:
        await db.execute(
            text(
                "INSERT INTO extension_versions (id, extension_id, version, manifest, "
                "bundle_storage, content_hash, bundle_size_bytes, review_status, "
                "review_problems, created_at) VALUES (:id, :ext, '2.0.0', '{}', 'local', "
                ":hash, 10, 'bogus', '[]', now())"
            ),
            {"id": uuid.uuid4(), "ext": fx.extension.id, "hash": SHA256_HEX},
        )

    await _rejected(db, _bogus)


@pytest.mark.parametrize(
    "overrides",
    [
        {"content_hash": "ZZ" + SHA256_HEX[2:]},
        {"content_hash": SHA256_HEX.upper()},
        {"bundle_size_bytes": 0},
        {"bundle_size_bytes": EXTENSION_BUNDLE_MAX_BYTES + 1},
    ],
)
async def test_version_checks_reject_bad_hash_and_size(
    db: AsyncSession, overrides: dict[str, Any]
) -> None:
    fx = await _seed(db)

    async def _insert() -> None:
        await _flush_added(db, _version(fx.extension.id, "9.9.9", **overrides))

    await _rejected(db, _insert)


async def test_version_accepts_the_bundle_cap_exactly(db: AsyncSession) -> None:
    fx = await _seed(db)
    await _flush_added(
        db, _version(fx.extension.id, "1.1.0", bundle_size_bytes=EXTENSION_BUNDLE_MAX_BYTES)
    )


async def test_latest_approved_version_is_set_null_when_the_version_goes(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)
    fx.extension.latest_approved_version_id = fx.version.id
    await db.flush()
    await db.delete(fx.version)
    await db.flush()
    await db.refresh(fx.extension)
    assert fx.extension.latest_approved_version_id is None


async def test_assets_are_unique_per_path_and_cascade_from_the_version(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)
    asset = ExtensionVersionAsset(
        version_id=fx.version.id,
        path="OVERVIEW.md",
        storage=ArtifactStorage.LOCAL,
        media_type="text/markdown",
        size_bytes=12,
    )
    await _flush_added(db, asset)
    await db.refresh(asset)
    assert asset.storage_key == asset.id  # §4.4: the ArtifactStore key IS the row id

    async def _dup() -> None:
        await _flush_added(
            db,
            ExtensionVersionAsset(
                version_id=fx.version.id,
                path="OVERVIEW.md",
                storage=ArtifactStorage.S3,
                media_type="text/markdown",
                size_bytes=1,
            ),
        )

    await _rejected(db, _dup)
    await db.delete(fx.version)
    await db.flush()
    remaining = await db.scalar(
        select(ExtensionVersionAsset).where(ExtensionVersionAsset.id == asset.id)
    )
    assert remaining is None


async def test_publisher_user_id_is_partial_unique_and_set_null_on_user_delete(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)

    async def _second_live_publisher() -> None:
        await _flush_added(db, ExtensionPublisher(user_id=fx.user.id, display_name="Twin"))

    await _rejected(db, _second_live_publisher)
    # Two anonymous (user_id NULL) publishers may coexist.
    await _flush_added(
        db,
        ExtensionPublisher(user_id=None, display_name="A"),
        ExtensionPublisher(user_id=None, display_name="B"),
    )
    await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": fx.user.id})
    await db.refresh(fx.publisher)
    assert fx.publisher.user_id is None


# --------------------------------------------------------------- installs
async def test_install_pins_a_real_version_and_the_pin_is_restrict(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)

    async def _dangling() -> None:
        await _flush_added(
            db,
            ExtensionInstall(
                project_id=fx.project.id,
                extension_id=fx.extension.id,
                version_id=uuid.uuid4(),
                installed_by=fx.user.id,
            ),
        )

    await _rejected(db, _dangling)
    install = ExtensionInstall(
        project_id=fx.project.id, extension_id=fx.extension.id, version_id=fx.version.id
    )
    await _flush_added(db, install)
    assert install.enabled is True
    assert install.settings == {}

    async def _delete_pinned_version() -> None:
        await db.execute(
            text("DELETE FROM extension_versions WHERE id = :id"), {"id": fx.version.id}
        )

    await _rejected(db, _delete_pinned_version)

    async def _delete_installed_extension() -> None:
        await db.execute(text("DELETE FROM extensions WHERE id = :id"), {"id": fx.extension.id})

    await _rejected(db, _delete_installed_extension)


async def test_one_install_per_project_and_extension(db: AsyncSession) -> None:
    fx = await _seed(db)
    await _flush_added(
        db,
        ExtensionInstall(
            project_id=fx.project.id, extension_id=fx.extension.id, version_id=fx.version.id
        ),
    )

    async def _dup() -> None:
        await _flush_added(
            db,
            ExtensionInstall(
                project_id=fx.project.id, extension_id=fx.extension.id, version_id=fx.version.id
            ),
        )

    await _rejected(db, _dup)


async def test_granted_arrays_round_trip_as_text_arrays(db: AsyncSession) -> None:
    fx = await _seed(db)
    install = ExtensionInstall(
        project_id=fx.project.id,
        extension_id=fx.extension.id,
        version_id=fx.version.id,
        granted_scopes=["graph.read", "storage.own"],
        granted_network=["https://api.octopart.com"],
    )
    await _flush_added(db, install)
    db.expunge(install)
    loaded = await db.scalar(select(ExtensionInstall).where(ExtensionInstall.id == install.id))
    assert loaded is not None
    assert loaded.granted_scopes == ["graph.read", "storage.own"]
    assert loaded.granted_network == ["https://api.octopart.com"]
    raw_type = await db.scalar(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'extension_installs' AND column_name = 'granted_scopes'"
        )
    )
    assert raw_type == "ARRAY"
    bare = ExtensionInstall(
        project_id=fx.project.id, extension_id=fx.extension.id, version_id=fx.version.id
    )
    db.expunge(loaded)
    await db.execute(text("DELETE FROM extension_installs"))
    await _flush_added(db, bare)
    assert bare.granted_scopes == [] and bare.granted_network == []


async def test_project_delete_cascades_installs_storage_and_layouts(db: AsyncSession) -> None:
    fx = await _seed(db)
    install = ExtensionInstall(
        project_id=fx.project.id, extension_id=fx.extension.id, version_id=fx.version.id
    )
    storage = ExtensionStorage(
        project_id=fx.project.id,
        extension_id=fx.extension.id,
        key="last_run",
        value={"rows": 412},
        size_bytes=12,
    )
    layout = WidgetLayout(
        project_id=fx.project.id,
        user_id=fx.user.id,
        layout=[{"ref": "ext:bom", "size": "standard"}],
    )
    await _flush_added(db, install, storage, layout)
    await db.execute(text("DELETE FROM projects WHERE id = :id"), {"id": fx.project.id})
    for model in (ExtensionInstall, ExtensionStorage, WidgetLayout):
        assert (await db.scalar(select(model))) is None, model.__tablename__
    # The catalog is untouched by a tenant's disappearance.
    assert (await db.scalar(select(Extension))) is not None


async def test_storage_is_keyed_per_project_extension_and_key(db: AsyncSession) -> None:
    fx = await _seed(db)
    row = ExtensionStorage(
        project_id=fx.project.id,
        extension_id=fx.extension.id,
        key="k",
        value=[1, "two", None],
        size_bytes=14,
    )
    await _flush_added(db, row)
    assert row.created_at is not None and row.updated_at is not None

    async def _dup() -> None:
        await _flush_added(
            db,
            ExtensionStorage(
                project_id=fx.project.id,
                extension_id=fx.extension.id,
                key="k",
                value={},
                size_bytes=2,
            ),
        )

    await _rejected(db, _dup)

    async def _negative() -> None:
        await _flush_added(
            db,
            ExtensionStorage(
                project_id=fx.project.id,
                extension_id=fx.extension.id,
                key="neg",
                value={},
                size_bytes=-1,
            ),
        )

    await _rejected(db, _negative)


async def test_widget_layout_is_one_per_user_and_bounded(db: AsyncSession) -> None:
    fx = await _seed(db)
    await _flush_added(db, WidgetLayout(project_id=fx.project.id, user_id=fx.user.id, layout=[]))

    async def _dup() -> None:
        await _flush_added(
            db, WidgetLayout(project_id=fx.project.id, user_id=fx.user.id, layout=[])
        )

    await _rejected(db, _dup)
    other = User(supabase_user_id="sub-other", email="other@example.com")
    db.add(other)
    await db.flush()
    too_many = [
        {"ref": f"builtin:w{i}", "size": "compact"} for i in range(WIDGET_LAYOUT_MAX_SLOTS + 1)
    ]

    async def _overflow() -> None:
        await _flush_added(
            db, WidgetLayout(project_id=fx.project.id, user_id=other.id, layout=too_many)
        )

    await _rejected(db, _overflow)

    async def _not_an_array() -> None:
        await _flush_added(
            db, WidgetLayout(project_id=fx.project.id, user_id=other.id, layout={"ref": "x"})
        )

    await _rejected(db, _not_an_array)
    await _flush_added(
        db, WidgetLayout(project_id=fx.project.id, user_id=other.id, layout=too_many[:-1])
    )


# ----------------------------------------------------------------- policy
async def test_team_policy_is_unique_and_blocked_excludes_default(db: AsyncSession) -> None:
    fx = await _seed(db)
    policy = TeamExtensionPolicy(
        team_id=fx.team.id, extension_id=fx.extension.id, default_installed=True, set_by=fx.user.id
    )
    await _flush_added(db, policy)
    assert policy.blocked is False and policy.default_settings == {}

    async def _dup() -> None:
        await _flush_added(
            db, TeamExtensionPolicy(team_id=fx.team.id, extension_id=fx.extension.id)
        )

    await _rejected(db, _dup)

    async def _contradiction() -> None:
        policy.blocked = True
        await db.flush()

    await _rejected(db, _contradiction)
    await db.refresh(policy)

    async def _delete_governed_extension() -> None:
        await db.execute(text("DELETE FROM extensions WHERE id = :id"), {"id": fx.extension.id})

    await _rejected(db, _delete_governed_extension)
    await db.execute(text("DELETE FROM teams WHERE id = :id"), {"id": fx.team.id})
    assert (await db.scalar(select(TeamExtensionPolicy))) is None


# ------------------------------------------------------------ amendments
async def test_credit_ledger_extension_id_is_nullable_fk_set_null(db: AsyncSession) -> None:
    fx = await _seed(db)
    plain = CreditLedger(user_id=fx.user.id, amount=-1, type=CreditTxnType.USAGE, balance_after=9)
    attributed = CreditLedger(
        user_id=fx.user.id,
        amount=-3,
        type=CreditTxnType.USAGE,
        balance_after=6,
        extension_id=fx.extension.id,
    )
    await _flush_added(db, plain, attributed)
    assert plain.extension_id is None

    async def _dangling() -> None:
        await _flush_added(
            db,
            CreditLedger(
                user_id=fx.user.id,
                amount=-1,
                type=CreditTxnType.USAGE,
                balance_after=5,
                extension_id=uuid.uuid4(),
            ),
        )

    await _rejected(db, _dangling)
    await db.execute(text("DELETE FROM extensions WHERE id = :id"), {"id": fx.extension.id})
    await db.refresh(attributed)
    assert attributed.extension_id is None  # the debit stays; attribution is dropped


async def test_jobs_kind_check_admits_extension_review_only_as_a_known_kind(
    db: AsyncSession,
) -> None:
    fx = await _seed(db)
    job = Job(project_id=fx.project.id, team_id=fx.team.id, kind=JobKind.EXTENSION_REVIEW)
    await _flush_added(db, job)
    assert JobKind("extension_review") is JobKind.EXTENSION_REVIEW

    async def _unknown() -> None:
        await db.execute(
            text(
                "INSERT INTO jobs (id, project_id, team_id, kind, status, progress, created_at, "
                "updated_at) VALUES (:id, :p, :t, 'extension_publish', 'queued', 0, now(), now())"
            ),
            {"id": uuid.uuid4(), "p": fx.project.id, "t": fx.team.id},
        )

    await _rejected(db, _unknown)


# -------------------------------------------------------------- staff gate
def _settings(**overrides: Any) -> Settings:
    fields: dict[str, Any] = {"_env_file": None, "supabase_jwt_secret": TEST_JWT_SECRET}
    fields.update(overrides)
    return Settings(**fields)


def test_staff_user_ids_parse_from_a_comma_separated_setting() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    settings = _settings(staff_user_ids=f" {a}, {b} ,,")
    assert settings.staff_user_id_set == {a, b}
    assert _settings().staff_user_id_set == set()


def test_staff_user_ids_reject_a_non_uuid_entry_at_startup() -> None:
    with pytest.raises(ValidationError):
        _settings(staff_user_ids="not-a-uuid")


def test_require_staff_admits_listed_ids_and_forbids_everyone_else() -> None:
    staff_id = uuid.uuid4()
    settings = _settings(staff_user_ids=str(staff_id))
    staff = User(id=staff_id, supabase_user_id="s", email="s@example.com")
    outsider = User(id=uuid.uuid4(), supabase_user_id="o", email="o@example.com")

    require_staff(staff, settings)  # listed → passes silently
    with pytest.raises(APIError) as excinfo:
        require_staff(outsider, settings)
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "forbidden"
    assert "staff" not in excinfo.value.message.lower()  # never discloses the staff list
    assert RequireStaff is not None


def test_extension_rate_limit_settings_carry_the_route_plan_defaults() -> None:
    settings = _settings()
    assert settings.extension_publishes_per_hour_per_user == 10
    assert settings.extension_bundle_downloads_per_minute_per_user == 30
    assert settings.extension_install_writes_per_minute_per_user == 60
    assert settings.extension_storage_writes_per_minute_per_install == 120
    assert settings.extension_policy_writes_per_minute_per_team == 30


# -------------------------------------------------------- response shapes
def _row(model: type[Any], **fields: Any) -> Any:
    """Detached ORM instance with the columns a serializer reads (no DB)."""
    return model(**fields)


def _shape_fixture() -> dict[str, Any]:
    now = datetime.now(UTC)
    manifest = {
        "extension": {"id": "bom", "requires": [["eda"]]},
        "views": {"page": {"entry": "page.html", "icon": "icon.svg"}, "widget": {"entry": "w"}},
        "permissions": {"scopes": ["graph.read", "sol.ask"], "network": ["https://x.io"]},
        "store": {
            "overview": "OVERVIEW.md",
            "screenshots": ["shots/a.png", "shots/missing.png"],
            "sections": [{"title": "How", "body": "docs/HOW.md"}],
        },
    }
    ext_id, pinned_id, latest_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    extension = _row(
        Extension,
        id=ext_id,
        slug="bom",
        name="BOM",
        summary="Bill.",
        verified=True,
        install_count=3,
        created_at=now,
        updated_at=now,
    )
    pinned = _row(
        ExtensionVersion,
        id=pinned_id,
        extension_id=ext_id,
        version="1.0.0",
        manifest={"permissions": {"scopes": ["graph.read"], "network": []}},
        content_hash=SHA256_HEX,
        bundle_size_bytes=10,
        review_status=ExtensionReviewStatus.APPROVED,
        review_problems=[],
        published_at=now,
        created_at=now,
    )
    latest = _row(
        ExtensionVersion,
        id=latest_id,
        extension_id=ext_id,
        version="1.1.0",
        manifest=manifest,
        content_hash=SHA256_HEX,
        bundle_size_bytes=20,
        review_status=ExtensionReviewStatus.REJECTED,
        review_problems=["bundle: too big"],
        published_at=None,
        created_at=now,
    )
    return {
        "extension": extension,
        "publisher": _row(ExtensionPublisher, display_name="Ada"),
        "pinned": pinned,
        "latest": latest,
        "now": now,
    }


def test_catalog_and_detail_shapes_derive_from_the_approved_manifest() -> None:
    fx = _shape_fixture()
    item = ext_schemas.serialize_catalog_item(fx["extension"], fx["publisher"], fx["latest"])
    assert item.payload()["publisher"] == {"display_name": "Ada"}
    assert item.requires == [["eda"]] and item.views == ["widget", "page"]
    assert item.latest_version.version == "1.1.0"

    detail = ext_schemas.serialize_extension_detail(
        fx["extension"], fx["publisher"], fx["latest"], ["OVERVIEW.md", "shots/a.png", "icon.svg"]
    )
    assert detail.version is not None
    assert detail.version.bundle_url == "/api/v1/extensions/bom/versions/1.1.0/bundle"
    assert detail.assets is not None
    assert detail.assets.overview == "/api/v1/extensions/bom/versions/1.1.0/assets/OVERVIEW.md"
    assert detail.assets.privacy_policy is None  # manifest declares none
    assert detail.assets.icon == "/api/v1/extensions/bom/versions/1.1.0/assets/icon.svg"
    assert detail.assets.screenshots == ["/api/v1/extensions/bom/versions/1.1.0/assets/shots/a.png"]
    assert detail.assets.sections == []  # docs/HOW.md is not a recorded asset
    unreleased = ext_schemas.serialize_extension_detail(fx["extension"], fx["publisher"], None)
    assert (unreleased.version, unreleased.manifest, unreleased.assets) == (None, None, None)


def test_version_summary_discloses_problems_only_to_the_publisher_when_rejected() -> None:
    fx = _shape_fixture()
    public = ext_schemas.serialize_version_summary(fx["latest"], as_publisher=False).payload()
    assert "review_problems" not in public and public["published_at"] is None
    owner = ext_schemas.serialize_version_summary(fx["latest"], as_publisher=True).payload()
    assert owner["review_problems"] == ["bundle: too big"]
    approved = ext_schemas.serialize_version_summary(fx["pinned"], as_publisher=True).payload()
    assert "review_problems" not in approved
    review = ext_schemas.serialize_review_status(fx["extension"], fx["latest"])
    assert review.review_problems == ["bundle: too big"] and review.checked_at is None
    published = ext_schemas.serialize_published_version(fx["extension"], fx["latest"])
    assert published.review_url == "/api/v1/extensions/bom/versions/1.1.0/review"


def test_install_row_reports_policy_block_and_permission_widening() -> None:
    fx = _shape_fixture()
    install = _row(
        ExtensionInstall,
        enabled=True,
        settings={"refresh": "manual"},
        granted_scopes=["graph.read"],
        granted_network=[],
        installed_by=None,
        created_at=fx["now"],
        updated_at=fx["now"],
    )
    row = ext_schemas.serialize_install(
        install, fx["extension"], fx["publisher"], fx["pinned"], fx["latest"], None
    )
    assert row.enabled is True and row.policy == ext_schemas.NO_POLICY
    assert row.version.manifest == fx["pinned"].manifest  # the PINNED manifest
    assert row.update_available == ext_schemas.UpdateAvailable(
        version="1.1.0", widens_permissions=True
    )
    blocked = _row(TeamExtensionPolicy, blocked=True, default_installed=False)
    row = ext_schemas.serialize_install(
        install, fx["extension"], fx["publisher"], fx["pinned"], fx["pinned"], blocked
    )
    assert row.enabled is False and row.policy.blocked is True
    assert row.update_available is None  # pinned IS the latest


def test_policy_storage_and_layout_shapes() -> None:
    fx = _shape_fixture()
    policy = _row(
        TeamExtensionPolicy,
        blocked=False,
        default_installed=True,
        default_settings={"refresh": "hourly"},
        set_by=None,
        updated_at=fx["now"],
    )
    assert ext_schemas.serialize_policy(policy, fx["extension"]).payload()["extension"] == {
        "slug": "bom",
        "name": "BOM",
        "verified": True,
    }
    storage = _row(ExtensionStorage, key="k", value=[1, None], size_bytes=8, updated_at=fx["now"])
    assert ext_schemas.serialize_storage_value(storage).value == [1, None]
    project_id = uuid.uuid4()
    empty = ext_schemas.serialize_widget_layout(project_id, None).payload()
    assert empty == {"project_id": str(project_id), "layout": [], "updated_at": None}
    layout = _row(WidgetLayout, layout=[{"ref": "ext:bom", "size": "wide"}], updated_at=fx["now"])
    assert ext_schemas.serialize_widget_layout(project_id, layout).layout == [
        ext_schemas.LayoutSlot(ref="ext:bom", size="wide")
    ]
