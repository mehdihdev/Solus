"""solusdev-215 merge toolkb + main heads

Revision ID: 07c4da2feccf
Revises: adb381b78d60, b7e4d9f320a1
Create Date: 2026-08-10 21:58:01.980672
"""

from collections.abc import Sequence

# Merge node only — rejoins the toolkb (TU-04/05) branch with the rest of the
# tree. The branches touch disjoint tables, so there is no schema change here.
#
# Originally joined toolkb to the billing tip `a91b3c7e2d48`. The
# SOLUSDEV-69 integration merge repointed it at `adb381b78d60`, because that node
# ALSO joins billing (it is merge(SOLUSDEV-96 chain, a91b3c7e2d48)) — leaving both
# as tips would give alembic two heads, and `conftest.py` upgrades to a singular
# "head", so a second tip fails the entire API suite rather than just a deploy.
# `a91b3c7e2d48` remains in this node's ancestry through `adb381b78d60`, so
# ordering is unchanged; this is a re-parent of a no-op join, not a schema edit.

revision: str = "07c4da2feccf"
down_revision: str | tuple[str, ...] | None = ("adb381b78d60", "b7e4d9f320a1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
