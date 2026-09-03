"""solusdev-235 extensions registry (ADR-035, task EXT-03)

The eight extension tables of docs/schemas/extensions.md plus the two
amendments: `credit_ledger.extension_id` (nullable attribution) and the
`jobs.kind` CHECK widened with `extension_review`. Upgrade order is §7 of the
schema doc (dependencies first; the `extensions → extension_versions` FK is
added AFTER both tables exist), downgrade reverses it exactly.

Enums stay portable VARCHAR + CHECK (`native_enum=False`) — no CREATE TYPE.
`text[]`, `char(64)` and `bigint` are used here for the first time in the
extension tables; the round-trip test covers them.

Revision ID: c4e8a2d6f931
Revises: a7d3f9c41e88
Create Date: 2026-09-03 12:00:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8a2d6f931"
down_revision: str | None = "a7d3f9c41e88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUNDLE_MAX_BYTES = 26_214_400  # 25 MiB — MANIFEST_LIMITS.bundle
LAYOUT_MAX_SLOTS = 24

_JOBKIND = "jobkind"
_JOB_KINDS = "'sync', 'check_run', 'proving', 'fingerprint_scan', 'sim_rebuild'"
_JOB_KINDS_WITH_REVIEW = _JOB_KINDS + ", 'extension_review'"
_LATEST_FK = "fk_extensions_latest_approved_version_id"


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def _artifact_storage() -> sa.Enum:
    return _enum("artifactstorage", "s3", "local", "client")


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _fk(name: str, target: str, ondelete: str, *, nullable: bool = False) -> sa.Column[Any]:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _jsonb(name: str, *, server_default: str | None = None) -> sa.Column[Any]:
    default = sa.text(f"'{server_default}'::jsonb") if server_default is not None else None
    return sa.Column(name, postgresql.JSONB(), nullable=False, server_default=default)


def _text_array(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
    )


def _bool(name: str, default: str) -> sa.Column[Any]:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text(default))


# ------------------------------------------------------------------ upgrade
def _create_publishers() -> None:
    op.create_table(
        "extension_publishers",
        _uuid_pk(),
        _fk("user_id", "users.id", "SET NULL", nullable=True),
        sa.Column("display_name", sa.String(length=60), nullable=False),
        _timestamp("created_at"),
        _timestamp("deleted_at", nullable=True),
    )
    op.create_index("ix_extension_publishers_deleted_at", "extension_publishers", ["deleted_at"])
    op.create_index(
        "uq_extension_publishers_user_id",
        "extension_publishers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL AND deleted_at IS NULL"),
    )


def _create_extensions() -> None:
    op.create_table(
        "extensions",
        _uuid_pk(),
        sa.Column("slug", sa.String(length=64), nullable=False),
        _fk("publisher_id", "extension_publishers.id", "RESTRICT"),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("summary", sa.String(length=160), nullable=False),
        _bool("verified", "false"),
        sa.Column("install_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # FK added in step 4, once extension_versions exists.
        sa.Column("latest_approved_version_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("deleted_at", nullable=True),
    )
    op.create_index("ix_extensions_deleted_at", "extensions", ["deleted_at"])
    op.create_index("ix_extensions_publisher_id", "extensions", ["publisher_id"])
    op.create_index(
        "ix_extensions_latest_approved_version_id", "extensions", ["latest_approved_version_id"]
    )
    op.create_index("uq_extensions_slug_lower", "extensions", [sa.text("lower(slug)")], unique=True)


def _create_versions() -> None:
    op.create_table(
        "extension_versions",
        _uuid_pk(),
        _fk("extension_id", "extensions.id", "CASCADE"),
        sa.Column("version", sa.Text(), nullable=False),
        _jsonb("manifest"),
        sa.Column("bundle_storage", _artifact_storage(), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("bundle_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "review_status",
            _enum("extensionreviewstatus", "pending", "checking", "approved", "rejected"),
            nullable=False,
            server_default="pending",
        ),
        _jsonb("review_problems", server_default="[]"),
        _timestamp("published_at", nullable=True),
        _timestamp("created_at"),
        _timestamp("deleted_at", nullable=True),
        sa.UniqueConstraint(
            "extension_id", "version", name="uq_extension_versions_extension_version"
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_extension_versions_content_hash_hex"
        ),
        sa.CheckConstraint(
            f"bundle_size_bytes > 0 AND bundle_size_bytes <= {BUNDLE_MAX_BYTES}",
            name="ck_extension_versions_bundle_size_range",
        ),
    )
    op.create_index("ix_extension_versions_deleted_at", "extension_versions", ["deleted_at"])
    op.create_index("ix_extension_versions_extension_id", "extension_versions", ["extension_id"])
    op.create_index("ix_extension_versions_review_status", "extension_versions", ["review_status"])


def _create_assets() -> None:
    op.create_table(
        "extension_version_assets",
        _uuid_pk(),
        _fk("version_id", "extension_versions.id", "CASCADE"),
        sa.Column("path", sa.String(length=200), nullable=False),
        sa.Column("storage_key", sa.Uuid(), nullable=False),
        sa.Column("storage", _artifact_storage(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.UniqueConstraint("version_id", "path", name="uq_extension_version_assets_version_path"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_extension_version_assets_size_nonneg"),
    )


def _create_installs() -> None:
    op.create_table(
        "extension_installs",
        _uuid_pk(),
        _fk("project_id", "projects.id", "CASCADE"),
        _fk("extension_id", "extensions.id", "RESTRICT"),
        _fk("version_id", "extension_versions.id", "RESTRICT"),
        _bool("enabled", "true"),
        _jsonb("settings", server_default="{}"),
        _text_array("granted_scopes"),
        _text_array("granted_network"),
        _fk("installed_by", "users.id", "SET NULL", nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint(
            "project_id", "extension_id", name="uq_extension_installs_project_extension"
        ),
    )
    for column in ("project_id", "extension_id", "version_id", "installed_by"):
        op.create_index(f"ix_extension_installs_{column}", "extension_installs", [column])


def _create_storage() -> None:
    op.create_table(
        "extension_storage",
        _uuid_pk(),
        _fk("project_id", "projects.id", "CASCADE"),
        _fk("extension_id", "extensions.id", "CASCADE"),
        sa.Column("key", sa.String(length=64), nullable=False),
        _jsonb("value"),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint(
            "project_id", "extension_id", "key", name="uq_extension_storage_project_extension_key"
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_extension_storage_size_nonneg"),
    )
    op.create_index("ix_extension_storage_extension_id", "extension_storage", ["extension_id"])


def _create_policies() -> None:
    op.create_table(
        "team_extension_policies",
        _uuid_pk(),
        _fk("team_id", "teams.id", "CASCADE"),
        _fk("extension_id", "extensions.id", "RESTRICT"),
        _bool("blocked", "false"),
        _bool("default_installed", "false"),
        _jsonb("default_settings", server_default="{}"),
        _fk("set_by", "users.id", "SET NULL", nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint(
            "team_id", "extension_id", name="uq_team_extension_policies_team_extension"
        ),
        sa.CheckConstraint(
            "NOT (blocked AND default_installed)",
            name="ck_team_extension_policies_blocked_not_default",
        ),
    )
    for column in ("extension_id", "set_by"):
        op.create_index(f"ix_team_extension_policies_{column}", "team_extension_policies", [column])


def _create_layouts() -> None:
    op.create_table(
        "widget_layouts",
        _uuid_pk(),
        _fk("project_id", "projects.id", "CASCADE"),
        _fk("user_id", "users.id", "CASCADE"),
        _jsonb("layout"),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_widget_layouts_project_user"),
        sa.CheckConstraint(
            f"jsonb_typeof(layout) = 'array' AND jsonb_array_length(layout) <= {LAYOUT_MAX_SLOTS}",
            name="ck_widget_layouts_layout_bounded",
        ),
    )
    op.create_index("ix_widget_layouts_user_id", "widget_layouts", ["user_id"])


def upgrade() -> None:
    _create_publishers()  # 1
    _create_extensions()  # 2
    _create_versions()  # 3
    op.create_foreign_key(  # 4
        _LATEST_FK,
        "extensions",
        "extension_versions",
        ["latest_approved_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _create_assets()  # 5
    _create_installs()  # 6
    _create_storage()  # 7
    _create_policies()  # 8
    _create_layouts()  # 9
    op.add_column(  # 10
        "credit_ledger",
        sa.Column(
            "extension_id",
            sa.Uuid(),
            sa.ForeignKey("extensions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_credit_ledger_extension_id", "credit_ledger", ["extension_id"])
    op.drop_constraint(_JOBKIND, "jobs", type_="check")  # 11
    op.create_check_constraint(_JOBKIND, "jobs", f"kind IN ({_JOB_KINDS_WITH_REVIEW})")


# ---------------------------------------------------------------- downgrade
def downgrade() -> None:
    # Review jobs only ever touched catalog rows, which this downgrade removes;
    # collapsing them into `check_run` keeps every row inside the narrower CHECK.
    op.execute("UPDATE jobs SET kind = 'check_run' WHERE kind = 'extension_review'")
    op.drop_constraint(_JOBKIND, "jobs", type_="check")
    op.create_check_constraint(_JOBKIND, "jobs", f"kind IN ({_JOB_KINDS})")
    op.drop_index("ix_credit_ledger_extension_id", table_name="credit_ledger")
    op.drop_column("credit_ledger", "extension_id")
    op.drop_table("widget_layouts")
    op.drop_table("team_extension_policies")
    op.drop_table("extension_storage")
    op.drop_table("extension_installs")
    op.drop_table("extension_version_assets")
    op.drop_constraint(_LATEST_FK, "extensions", type_="foreignkey")
    op.drop_table("extension_versions")
    op.drop_table("extensions")
    op.drop_table("extension_publishers")
