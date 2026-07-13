"""solusdev 59 merge billing heads drop call_id

Merges the forked migration heads from the main→SOLUSDEV-59 merge:
- 8d4f2a91c6e3→9b0d77b7acd2 (MO-03 `credit_ledger.call_id` + FP-02 canonical_key)
- c3d9e1f2a4b6 (SOLUSDEV-83 billing hardening: `credit_ledger.idempotency_key`,
  pending_credit_debits, processed_stripe_events)

`idempotency_key` (partial-unique, SOLUSDEV-83) supersedes MO-03's `call_id` as
the ledger dedupe key — all debit paths now write it via `billing.credits`, so
the `call_id` column and its unique index are dropped here. Dev-only data: the
SOLUSDEV-59 branch (the only carrier of `call_id`) was never pushed or deployed.

Revision ID: bfcba5cde984
Revises: 9b0d77b7acd2, c3d9e1f2a4b6
Create Date: 2026-07-13 13:00:45.336018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bfcba5cde984"
down_revision: str | Sequence[str] | None = ("9b0d77b7acd2", "c3d9e1f2a4b6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_credit_ledger_call_id", table_name="credit_ledger")
    op.drop_column("credit_ledger", "call_id")


def downgrade() -> None:
    op.add_column("credit_ledger", sa.Column("call_id", sa.String(length=64), nullable=True))
    op.create_index("uq_credit_ledger_call_id", "credit_ledger", ["call_id"], unique=True)
