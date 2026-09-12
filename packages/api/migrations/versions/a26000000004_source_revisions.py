"""Personal source revision snapshots and per-user selections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a26000000004"
down_revision: str | None = "a26000000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("revision_base_source_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_source_revision_base",
        "sources",
        "sources",
        ["revision_base_source_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_sources_revision_base_source_id", "sources", ["revision_base_source_id"])
    op.create_table(
        "source_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "base_source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "materialized_source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("commit_id", sa.String(64), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("base_source_id", "commit_id"),
    )
    op.create_table(
        "source_view_selections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "base_source_id",
            sa.Uuid(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "active_revision_id",
            sa.Uuid(),
            sa.ForeignKey("source_revisions.id", ondelete="SET NULL"),
        ),
        sa.Column("active_branch", sa.String(255)),
        sa.Column("requested_branch", sa.String(255)),
        sa.Column("request_generation", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "base_source_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name="ck_source_view_status"
        ),
    )
    for table, columns in [
        ("source_revisions", ["project_id", "base_source_id"]),
        ("source_view_selections", ["project_id", "user_id", "base_source_id"]),
    ]:
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("source_view_selections")
    op.drop_table("source_revisions")
    op.execute(sa.text("DELETE FROM sources WHERE revision_base_source_id IS NOT NULL"))
    op.drop_index("ix_sources_revision_base_source_id", table_name="sources")
    op.drop_constraint("fk_source_revision_base", "sources", type_="foreignkey")
    op.drop_column("sources", "revision_base_source_id")
