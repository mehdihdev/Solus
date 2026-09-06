"""solusdev-240 merge connections + solus heads

Revision ID: 2cd33377eeb0
Revises: 9a1c4e7d2b30, b7e2d4a9c1f0
Create Date: 2026-09-05 16:32:21.528057
"""

from collections.abc import Sequence

# Merge node only — rejoins main's SOLUSDEV-241 chain (`9a1c4e7d2b30`, account
# connections + the integration cache) with SOLUSDEV-240's (`b7e2d4a9c1f0`, the
# `project` domain, retained artifacts, `solus_entries`). Both branch off
# `c88cbf6c3388` and touch disjoint tables. No schema change here; `conftest.py`
# upgrades to a singular "head", so leaving both tips fails the entire suite.

revision: str = "2cd33377eeb0"
down_revision: str | tuple[str, ...] | None = ("9a1c4e7d2b30", "b7e2d4a9c1f0")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
