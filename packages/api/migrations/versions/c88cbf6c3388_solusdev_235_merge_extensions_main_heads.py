"""solusdev-235 merge extensions + main heads

Revision ID: c88cbf6c3388
Revises: c4e8a2d6f931, fd8483a75eab
Create Date: 2026-09-03 22:12:35.742893
"""

from collections.abc import Sequence

# Merge node only — rejoins the SOLUSDEV-235 (widget store / extensions) branch with
# main. Both sides branch off `a7d3f9c41e88` and touch disjoint tables: this branch
# added the extension tables, `credit_ledger.extension_id` and the widened `jobs.kind`
# CHECK; main's `fd8483a75eab` chain added `oauth_states.code_verifier` (SOLUSDEV-168).
# No schema change here. `conftest.py` upgrades to a singular "head", so leaving both
# tips fails the entire API suite, not just a deploy.

revision: str = "c88cbf6c3388"
down_revision: str | tuple[str, ...] | None = ("c4e8a2d6f931", "fd8483a75eab")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
