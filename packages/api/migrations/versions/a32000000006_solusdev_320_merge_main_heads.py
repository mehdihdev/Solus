"""SOLUSDEV-320: merge the main heads (a23600000001, SOLUSDEV-236 subscription interval)
and the SOLUSDEV-320 chain (a32000000005) back into one head. No schema change.

Revision ID: a32000000006
Revises: a23600000001, a32000000005
Create Date: 2026-10-24
"""

from collections.abc import Sequence

revision: str = "a32000000006"
down_revision: str | Sequence[str] | None = ("a23600000001", "a32000000005")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
