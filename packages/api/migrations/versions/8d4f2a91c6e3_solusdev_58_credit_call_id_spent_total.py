"""solusdev_58 credit call_id + spent_total

SOLUS-MO-03 billing groundwork: `credit_ledger.call_id` with a UNIQUE index makes the
gateway debit idempotent per model call at the database level (a retried/concurrent
track_cost with the same call_id hits the constraint instead of double-debiting —
constraint-based, never check-then-write). Nullable: only gateway USAGE rows carry a
call_id; grants/purchases/adjustments keep it NULL (Postgres unique indexes ignore NULLs).
`credit_balance.spent_total` is a rolling all-time USAGE total maintained in the same
transaction as each debit, so the trial-cap pre-flight reads O(1) instead of summing the
ledger per call.

Revision ID: 8d4f2a91c6e3
Revises: 5c2c022b4d39
Create Date: 2026-07-11 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d4f2a91c6e3"
down_revision: str | None = "5c2c022b4d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_ledger", sa.Column("call_id", sa.String(length=64), nullable=True))
    op.create_index("uq_credit_ledger_call_id", "credit_ledger", ["call_id"], unique=True)
    op.add_column(
        "credit_balance",
        sa.Column("spent_total", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("credit_balance", "spent_total")
    op.drop_index("uq_credit_ledger_call_id", table_name="credit_ledger")
    op.drop_column("credit_ledger", "call_id")
