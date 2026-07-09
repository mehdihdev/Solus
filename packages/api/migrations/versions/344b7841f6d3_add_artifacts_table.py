"""add artifacts table

The registry for large-data references (SOLUS-W0-04). Bytes live in S3/on a
client; only metadata lives here. A follow-on to the W0-01 schema — it does not
edit the original migration.

Revision ID: 344b7841f6d3
Revises: 7ea820a98068
Create Date: 2026-07-05 02:40:57.236914
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "344b7841f6d3"
down_revision: str | None = "7ea820a98068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "project",
                "private",
                name="artifactscope",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("uri", sa.String(length=2048), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "storage_location",
            sa.Enum(
                "s3",
                "local",
                "client",
                name="artifactstorage",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("source_tool", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_created_by"), "artifacts", ["created_by"], unique=False)
    op.create_index(op.f("ix_artifacts_deleted_at"), "artifacts", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_artifacts_project_id"), "artifacts", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_project_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_deleted_at"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_created_by"), table_name="artifacts")
    op.drop_table("artifacts")
