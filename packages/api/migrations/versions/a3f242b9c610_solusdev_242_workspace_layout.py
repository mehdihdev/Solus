"""solusdev-242 project-shared workspace coordinates

Revision ID: a3f242b9c610
Revises: 2cd33377eeb0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f242b9c610"
down_revision: str | None = "2cd33377eeb0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_layouts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("positions", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
        sa.CheckConstraint("version >= 0", name="ck_workspace_layouts_version_nonnegative"),
        sa.CheckConstraint(
            "jsonb_typeof(positions) = 'object'", name="ck_workspace_layouts_positions_object"
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_layouts")
