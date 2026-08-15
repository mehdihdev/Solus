"""SOLUSDEV-96 confirmation STALE status

Adds the `stale` member to the confirmationstatus CHECK constraint: an approval
whose described effect had changed since the user was shown it, so nothing ran.
Distinct from `expired` — time did not run out, the world moved.

The enum is portable VARCHAR + CHECK (native_enum=False), so widening it means
dropping and recreating the constraint rather than ALTER TYPE.

Revision ID: a7c41b9d2e05
Revises: 59530f556236
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c41b9d2e05"
down_revision: str | None = "59530f556236"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "confirmationstatus"
_TABLE = "tool_confirmations"
_WITH_STALE = "'pending', 'approved', 'rejected', 'expired', 'stale'"
_WITHOUT_STALE = "'pending', 'approved', 'rejected', 'expired'"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, f"status IN ({_WITH_STALE})")


def downgrade() -> None:
    # Any row already recorded as stale would violate the narrower constraint.
    # Nothing was executed for those rows, so collapsing them into `expired`
    # keeps the same meaning to a reader: decided, and nothing applied.
    op.execute("UPDATE tool_confirmations SET status = 'expired' WHERE status = 'stale'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, f"status IN ({_WITHOUT_STALE})")
