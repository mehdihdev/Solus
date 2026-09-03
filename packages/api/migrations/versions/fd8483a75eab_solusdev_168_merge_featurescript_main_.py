"""solusdev-168 merge featurescript + main heads

Revision ID: fd8483a75eab
Revises: 3f1c8a6d90e2, a7d3f9c41e88
Create Date: 2026-09-03 05:20:38.641894
"""

from collections.abc import Sequence

# Merge node only — rejoins the SOLUSDEV-168 (FeatureScript MCP) branch with main.
# Both sides branch off `07c4da2feccf` and touch disjoint tables: this branch added
# `oauth_states.code_verifier`, main's `a7d3f9c41e88` added the SOLUSDEV-233 SOL custom
# instruction. No schema change here. `conftest.py` upgrades to a singular "head", so
# leaving both tips fails the entire API suite, not just a deploy.

revision: str = "fd8483a75eab"
down_revision: str | tuple[str, ...] | None = ("3f1c8a6d90e2", "a7d3f9c41e88")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
