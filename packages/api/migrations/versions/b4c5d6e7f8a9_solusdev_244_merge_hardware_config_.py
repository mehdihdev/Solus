"""solusdev_244 merge hardware config (7e290e665c1f) and sourcing (f0a1b2c3d4e5) heads

Revision ID: b4c5d6e7f8a9
Revises: 7e290e665c1f, f0a1b2c3d4e5
Create Date: 2026-09-06 19:30:00.618760
"""

from collections.abc import Sequence

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = ("7e290e665c1f", "f0a1b2c3d4e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
