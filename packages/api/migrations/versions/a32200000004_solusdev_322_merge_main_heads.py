"""SOLUSDEV-322: merge the main heads (a31900000003, SOLUSDEV-319 academic plan)
and the SOLUSDEV-322 chain (a32200000003) back into one head. No schema change.

Revision ID: a32200000004
Revises: a31900000003, a32200000003
Create Date: 2026-11-10
"""

from collections.abc import Sequence

revision: str = "a32200000004"
down_revision: str | Sequence[str] | None = ("a31900000003", "a32200000003")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
