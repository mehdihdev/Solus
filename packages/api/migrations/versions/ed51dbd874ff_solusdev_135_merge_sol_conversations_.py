"""solusdev_135 merge sol conversations and billing heads

Revision ID: ed51dbd874ff
Revises: b3d9c1a4e7f2, bfcba5cde984
Create Date: 2026-07-17 09:21:40.982115
"""

from collections.abc import Sequence

revision: str = "ed51dbd874ff"
down_revision: str | Sequence[str] | None = ("b3d9c1a4e7f2", "bfcba5cde984")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
