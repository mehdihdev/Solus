"""solusdev 82 merge account lifecycle head

Revision ID: 20af242f48a0
Revises: b2f1a7c9d3e4, ed51dbd874ff
Create Date: 2026-07-18 16:58:08.294016
"""

from collections.abc import Sequence

revision: str = "20af242f48a0"
down_revision: str | None = ("b2f1a7c9d3e4", "ed51dbd874ff")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
