"""SOLUSDEV-319 `bench_views` — one team-shared Live Bench view per project.

Revision ID: a31900000001
Revises: a32100000001
Create Date: 2026-10-31

docs/schemas/bench-view.md: project-owned row (cascade), integer version, JSONB `display` and
`derived` arrays bounded at 512 / 32 entries, `updated_by` SET NULL. No index beyond the primary
key; no backfill. The downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a31900000001"
down_revision: str | None = "a32100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "bench_views"
EMPTY_ARRAY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("display", JSONB(), nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("derived", JSONB(), nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_id"),
        sa.CheckConstraint("version >= 0", name="ck_bench_views_version_nonnegative"),
        sa.CheckConstraint("jsonb_typeof(display) = 'array'", name="ck_bench_views_display_array"),
        sa.CheckConstraint("jsonb_typeof(derived) = 'array'", name="ck_bench_views_derived_array"),
        sa.CheckConstraint(
            "jsonb_array_length(display) <= 512", name="ck_bench_views_display_bound"
        ),
        sa.CheckConstraint(
            "jsonb_array_length(derived) <= 32", name="ck_bench_views_derived_bound"
        ),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
