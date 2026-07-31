"""solusdev_153 byo_paid_tools limits backfill (MCP-05)

`_limit()` treats an ABSENT key as unlimited, so without this backfill every
existing BASIC subscription would get bring-your-own-license (paid) tools for
free — fail-open on a paid feature. Basic rows gain `byo_paid_tools: 0`
(blocked) when absent; pro rows gain an explicit `byo_paid_tools: null`
(unlimited) so absent-vs-null ambiguity dies; enterprise rows (custom per deal)
are untouched. The downgrade removes the key from basic/pro rows.

The SQL lives in module constants so the test suite executes the SAME
statements against seeded rows — one source of truth, no copied SQL.

Revision ID: a7c5d2e91f04
Revises: 20af242f48a0
Create Date: 2026-07-24 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c5d2e91f04"
down_revision: str | None = "20af242f48a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL: tuple[str, ...] = (
    """
    UPDATE subscriptions
    SET limits = jsonb_set(limits, '{byo_paid_tools}', '0'::jsonb)
    WHERE plan = 'basic' AND NOT limits ? 'byo_paid_tools'
    """,
    """
    UPDATE subscriptions
    SET limits = jsonb_set(limits, '{byo_paid_tools}', 'null'::jsonb)
    WHERE plan = 'pro' AND NOT limits ? 'byo_paid_tools'
    """,
)

DOWNGRADE_SQL: tuple[str, ...] = (
    """
    UPDATE subscriptions
    SET limits = limits - 'byo_paid_tools'
    WHERE plan IN ('basic', 'pro')
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
