"""decisions_cde per-user subscription

SOLUSDEV-72 Decisions C-E: reshape `subscriptions` from per-TEAM to per-USER (ADR-032 billing
model). Drops `team_id`/`current_period_end`, adds `user_id` + `expires_at`, makes
`stripe_customer_id` nullable (a trial has no Stripe customer yet), and enforces one live
subscription per user. The table is unwired (no rows/readers), so this is a clean reshape.

Revision ID: 1257e0b34736
Revises: 62682120a0a7
Create Date: 2026-07-08 22:18:00.092737
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1257e0b34736"
down_revision: str | None = "62682120a0a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("user_id", sa.Uuid(), nullable=False))
    op.add_column(
        "subscriptions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column(
        "subscriptions", "stripe_customer_id", existing_type=sa.String(length=255), nullable=True
    )
    op.drop_column("subscriptions", "current_period_end")
    op.drop_index(op.f("ix_subscriptions_team_id"), table_name="subscriptions")
    op.drop_column("subscriptions", "team_id")  # drops its FK constraint too
    op.create_foreign_key(
        "subscriptions_user_id_fkey",
        "subscriptions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=False)
    op.create_index(
        "uq_subscription_user",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_subscription_user", table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_constraint("subscriptions_user_id_fkey", "subscriptions", type_="foreignkey")
    op.add_column("subscriptions", sa.Column("team_id", sa.Uuid(), nullable=False))
    op.create_foreign_key(
        "subscriptions_team_id_fkey",
        "subscriptions",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_subscriptions_team_id"), "subscriptions", ["team_id"], unique=False)
    op.add_column(
        "subscriptions",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "subscriptions", "stripe_customer_id", existing_type=sa.String(length=255), nullable=False
    )
    op.drop_column("subscriptions", "expires_at")
    op.drop_column("subscriptions", "user_id")
