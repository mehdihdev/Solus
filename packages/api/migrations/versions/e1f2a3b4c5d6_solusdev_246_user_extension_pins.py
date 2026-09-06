"""SOLUSDEV-246 (STORE ST3): per-user extension pins — "Pin for all projects".

`user_extension_pins`: one row per (user, extension). Account-scoped (no
team/project column by design — the pin follows the user across projects);
every read filters on the caller's id (docs/schemas/extensions.md §4.9).

Revision ID: e1f2a3b4c5d6
Revises: f7a8b9c0d1e2
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

TABLE = "user_extension_pins"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "extension_id",
            sa.Uuid(),
            sa.ForeignKey("extensions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "extension_id", name="uq_user_extension_pins_user_extension"
        ),
    )
    op.create_index("ix_user_extension_pins_user_id", TABLE, ["user_id"])
    op.create_index("ix_user_extension_pins_extension_id", TABLE, ["extension_id"])


def downgrade() -> None:
    op.drop_index("ix_user_extension_pins_extension_id", table_name=TABLE)
    op.drop_index("ix_user_extension_pins_user_id", table_name=TABLE)
    op.drop_table(TABLE)
