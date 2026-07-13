"""solusdev-83 billing hardening

Money-path hardening tables/columns (SOLUSDEV-83 / SOLUS-FND-03):

1. `credit_ledger.idempotency_key` (+ partial-unique index) makes a debit/credit
   once-only, so retries and webhook replays never double-apply.
2. `processed_stripe_events` dedupes Stripe webhook deliveries by event id.
3. `pending_credit_debits` is the dead-letter for debits that could not be
   applied inline (ADR-024 W0-03) — an ARQ worker reconciles them.

Revision ID: c3d9e1f2a4b6
Revises: 5c2c022b4d39
Create Date: 2026-07-12 15:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d9e1f2a4b6"
down_revision: str | None = "5c2c022b4d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _reconcile_status() -> sa.Enum:
    return sa.Enum(
        "pending",
        "reconciled",
        "failed",
        name="debitreconcilestatus",
        native_enum=False,
        length=32,
        create_constraint=True,
    )


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("stripe_event_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "credit_ledger",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_credit_ledger_idempotency_key",
        "credit_ledger",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "processed_stripe_events",
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_processed_stripe_events_stripe_event_id"),
        "processed_stripe_events",
        ["stripe_event_id"],
        unique=True,
    )

    op.create_table(
        "pending_credit_debits",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", _reconcile_status(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_credit_debits_user_id"), "pending_credit_debits", ["user_id"])
    op.create_index(
        op.f("ix_pending_credit_debits_idempotency_key"),
        "pending_credit_debits",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pending_credit_debits_idempotency_key"), table_name="pending_credit_debits"
    )
    op.drop_index(op.f("ix_pending_credit_debits_user_id"), table_name="pending_credit_debits")
    op.drop_table("pending_credit_debits")

    op.drop_index(
        op.f("ix_processed_stripe_events_stripe_event_id"), table_name="processed_stripe_events"
    )
    op.drop_table("processed_stripe_events")

    op.drop_index("uq_credit_ledger_idempotency_key", table_name="credit_ledger")
    op.drop_column("credit_ledger", "idempotency_key")
    op.drop_column("subscriptions", "stripe_event_at")
