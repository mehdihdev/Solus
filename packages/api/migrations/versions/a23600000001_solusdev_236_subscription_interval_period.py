"""SOLUSDEV-236: subscriptions.billing_interval + current_period_end.

Schema only, no backfill: both columns are NULLable (metadata-only in PostgreSQL, no
rewrite) and reconciliation fills Stripe-linked rows. The CHECK is added NOT VALID then
validated, like a31300000001 (every billing_interval is NULL here anyway).

Revision ID: a23600000001
Revises: a21600000001
Create Date: 2026-10-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a23600000001"
down_revision: str | None = "a21600000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_subscriptions_billing_interval"


def upgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("billing_interval", sa.String(length=8), nullable=True)
    )
    op.add_column(
        "subscriptions", sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        _CHECK,
        "subscriptions",
        "billing_interval IS NULL OR billing_interval IN ('month', 'year')",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE subscriptions VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    op.drop_constraint(_CHECK, "subscriptions", type_="check")
    op.drop_column("subscriptions", "current_period_end")
    op.drop_column("subscriptions", "billing_interval")
