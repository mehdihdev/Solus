"""SOLUSDEV-322 P2-T1: `sim_session` — the simulator session ownership ledger.

Revision ID: a32200000001
Revises: a32100000001
Create Date: 2026-11-09

One row per simulator session the API knows about: `owner = 'sol'` when Solus started it (the
proof the per-call gate reads), `'user'` when Solus only attached to one the person started.
`provider` is a string discriminator and `scene_ref` one vendor-free column for the world or
stage. The partial unique index keeps one live row per `(project, provider, session_id)`; the
`(project_id, provider, ended_at)` index serves `is_owned`, `running` and
`owned_running_count`. `created_by` is SET NULL when the account goes. The downgrade drops all
of it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a32200000001"
down_revision: str | None = "a32100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sim_session"
LIVE_INDEX = "uq_sim_session_live"
LOOKUP_INDEX = "ix_sim_session_project_provider_ended"
OWNERS = "('sol', 'user')"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("started_by_call_id", sa.String(128), nullable=True),
        sa.Column("scene_ref", sa.String(512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"owner IN {OWNERS}", name="sim_session_owner"),
    )
    op.create_index(
        LIVE_INDEX,
        TABLE,
        ["project_id", "provider", "session_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(LOOKUP_INDEX, TABLE, ["project_id", "provider", "ended_at"])


def downgrade() -> None:
    op.drop_index(LOOKUP_INDEX, table_name=TABLE)
    op.drop_index(LIVE_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
