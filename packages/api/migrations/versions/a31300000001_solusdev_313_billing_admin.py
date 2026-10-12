"""SOLUSDEV-313: subscription staff override/comp columns + Stripe cancel tombstones.

Schema only, no backfill: every new subscriptions column is NULLable (a metadata-only
change in PostgreSQL, no table rewrite), and `stripe_cancel_requests` is a new table.

Revision ID: a31300000001
Revises: a38000000001
Create Date: 2026-10-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a31300000001"
down_revision: str | None = "a38000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN_CHECK = "subscription_comp_plan"
_DUE_INDEX = "ix_stripe_cancel_requests_pending_next_attempt"


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("limits_override", postgresql.JSONB(), nullable=True))
    op.add_column("subscriptions", sa.Column("comp_plan", sa.String(length=32), nullable=True))
    # NOT VALID then VALIDATE: the ADD takes only a brief lock; the full-table check runs
    # under the weaker SHARE UPDATE EXCLUSIVE lock (every comp_plan is NULL here anyway).
    op.create_check_constraint(
        _PLAN_CHECK,
        "subscriptions",
        "comp_plan IN ('basic', 'pro', 'enterprise')",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE subscriptions VALIDATE CONSTRAINT {_PLAN_CHECK}")
    op.add_column(
        "subscriptions", sa.Column("comp_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "stripe_cancel_requests",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stripe_cancel_requests_stripe_customer_id",
        "stripe_cancel_requests",
        ["stripe_customer_id"],
        unique=True,
    )
    # Partial: the runner only scans pending rows, and completed tombstones are never purged.
    op.create_index(
        _DUE_INDEX,
        "stripe_cancel_requests",
        ["next_attempt_at"],
        postgresql_where=sa.text("completed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(_DUE_INDEX, table_name="stripe_cancel_requests")
    op.drop_index(
        "ix_stripe_cancel_requests_stripe_customer_id", table_name="stripe_cancel_requests"
    )
    op.drop_table("stripe_cancel_requests")
    op.drop_column("subscriptions", "comp_expires_at")
    op.drop_constraint(_PLAN_CHECK, "subscriptions", type_="check")
    op.drop_column("subscriptions", "comp_plan")
    op.drop_column("subscriptions", "limits_override")
