"""SOLUSDEV-326: `tool_confirmations.card` — the Solus-authored card a parked call shows.

Revision ID: a32600000002
Revises: a32600000001
Create Date: 2026-11-16

docs/contracts/action-gate.md §Cards: the tool computes the card once when the call parks, from
its stored arguments; presentation only, never part of the consent or the stale check. Nullable:
a row parked before this revision, or by a tool that authors no card, has none. The downgrade
drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a32600000002"
down_revision: str | None = "a32600000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "tool_confirmations"
COLUMN = "card"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
