"""Merge point: SOLUSDEV-246 (e6f7a8b9c0d1) and SOLUSDEV-242's workspace/solus-graph
chain (c7f242e9a842).

Nothing to reconcile by hand: the `domain` CHECK was last rewritten to the full
seven-value vocabulary by e6f7a8b9c0d1 (an ancestor here), and the 242 chain only
inserts `project`-domain rows, which every path already permits.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1, c7f242e9a842
Create Date: 2026-09-06
"""

revision = "f7a8b9c0d1e2"
down_revision = ("e6f7a8b9c0d1", "c7f242e9a842")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
