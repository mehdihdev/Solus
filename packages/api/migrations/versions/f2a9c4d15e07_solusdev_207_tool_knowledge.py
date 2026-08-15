"""solusdev-207 tool_knowledge table (SOLUS-TU-04, LANE D)

The shared tool-knowledge store. Mirrors the CTR-05 boundary exactly — typed
columns only, no JSONB, no customer-owned identifier, and deliberately NO
team/project/user column: the store is cross-tenant by design and the absence
of those columns is the tenancy boundary (docs/contracts/tool-knowledge.md).
Storage-side columns are all enum/number/timestamp. Writes go only through the
TU-06 ingestion guard.

Revision ID: f2a9c4d15e07
Revises: e3a1c8f27b54
Create Date: 2026-08-08 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f2a9c4d15e07"
down_revision: str | None = "e3a1c8f27b54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    op.create_table(
        "tool_knowledge",
        # -- CTR-05 mirror -------------------------------------------------
        sa.Column(
            "tool",
            _enum(
                "toolfamily",
                "fusion",
                "onshape",
                "solidworks",
                "autocad",
                "kicad",
                "altium",
                "spice",
            ),
            nullable=False,
        ),
        sa.Column("version_range", sa.String(length=64), nullable=False),
        sa.Column(
            "surface",
            _enum(
                "uisurface",
                "toolbar",
                "menu",
                "context_menu",
                "panel",
                "dialog",
                "keyboard",
                "status_bar",
            ),
            nullable=False,
        ),
        sa.Column("control_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=400), nullable=False),
        sa.Column(
            "effect",
            _enum(
                "controleffect",
                "create_feature",
                "modify_feature",
                "delete_feature",
                "select",
                "navigate",
                "measure",
                "toggle_visibility",
                "import",
                "export",
                "undo",
                "settings",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("menu_path", postgresql.ARRAY(sa.String(length=400)), nullable=True),
        sa.Column("shortcut", sa.String(length=64), nullable=True),
        sa.Column("locator_x", sa.Float(), nullable=True),
        sa.Column("locator_y", sa.Float(), nullable=True),
        sa.Column("locator_w", sa.Float(), nullable=True),
        sa.Column("locator_h", sa.Float(), nullable=True),
        sa.Column(
            "provenance",
            _enum("provenance", "vendor_docs", "observed_ui", "operator_authored"),
            nullable=False,
        ),
        # -- storage-side: enum / number / timestamp only ------------------
        sa.Column("status", _enum("knowledgestatus", "candidate", "published"), nullable=False),
        sa.Column(
            "acquired_via",
            _enum("acquisitionmethod", "api_geometry", "docs", "visual", "operator"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confirm_count", sa.Integer(), nullable=False),
        sa.Column("reject_count", sa.Integer(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version_min_key", sa.String(length=32), nullable=False),
        sa.Column("version_max_key", sa.String(length=32), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_tool_knowledge_confidence_range"
        ),
        sa.CheckConstraint(
            "confirm_count >= 0 AND reject_count >= 0",
            name="ck_tool_knowledge_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "menu_path IS NULL OR cardinality(menu_path) <= 8",
            name="ck_tool_knowledge_menu_path_len",
        ),
        sa.CheckConstraint(
            "num_nonnulls(locator_x, locator_y, locator_w, locator_h) IN (0, 4)",
            name="ck_tool_knowledge_locator_all_or_none",
        ),
        sa.CheckConstraint(
            "(locator_x IS NULL OR (locator_x >= 0 AND locator_x <= 1))"
            " AND (locator_y IS NULL OR (locator_y >= 0 AND locator_y <= 1))"
            " AND (locator_w IS NULL OR (locator_w >= 0 AND locator_w <= 1))"
            " AND (locator_h IS NULL OR (locator_h >= 0 AND locator_h <= 1))",
            name="ck_tool_knowledge_locator_bounds",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_knowledge_deleted_at"), "tool_knowledge", ["deleted_at"], unique=False
    )
    op.create_index(
        "uq_tool_knowledge_identity",
        "tool_knowledge",
        ["tool", "control_id", "surface", "version_range"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_tool_knowledge_lookup",
        "tool_knowledge",
        ["tool", "status", "version_min_key"],
        unique=False,
    )
    # HNSW: correct when built empty, no REINDEX as the corpus grows (ADR-027).
    op.create_index(
        "ix_tool_knowledge_embedding",
        "tool_knowledge",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("tool_knowledge")
