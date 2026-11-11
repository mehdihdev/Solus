"""SOLUSDEV-322 P5-T4 review: `sim_session.scene_name` — the name a simulator addresses the
scene by, recorded API-side when the session starts.

Revision ID: a32200000003
Revises: a32200000002
Create Date: 2026-11-09

`scene_ref` names the user's file (or the world the person attached to); `scene_name` is the
name the running simulator addresses that scene by, fixed once when the session is recorded so
a routine's readback is keyed from the ledger, never from the companion's result. Nullable: an
attached session carries its world name, an owned one the name resolved at start, a provider
without scene names nothing. The downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a32200000003"
down_revision: str | None = "a32200000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sim_session"
COLUMN = "scene_name"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
