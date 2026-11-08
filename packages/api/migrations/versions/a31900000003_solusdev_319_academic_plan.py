"""SOLUSDEV-319 (ADR-042): the Academic plan.

- The `plantype` CHECK (`subscriptions.plan`) and `subscription_comp_plan` CHECK admit
  `academic`.
- The `credittxntype` CHECK admits `academic_grant`.
- New tables `academic_verifications` (one row per user) and `academic_code_sends` (the
  append-only send log behind the per-address cap); see docs/schemas/subscriptions.md.

Downgrade moves academic subscriptions back to `basic` (same limits), reclassifies
academic grants as `adjustment` (the ledger is append-only, ADR-024), and drops the table.

Revision ID: a31900000003
Revises: a31900000002
Create Date: 2026-11-08 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a31900000003"
down_revision: str | None = "a31900000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PLANS = ("basic", "pro", "enterprise")
_NEW_PLANS = (*_OLD_PLANS, "academic")
_OLD_TXNS = ("purchase", "usage", "trial_grant", "plan_grant", "refund", "adjustment")
_NEW_TXNS = (*_OLD_TXNS, "academic_grant")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _checks(plans: tuple[str, ...], txns: tuple[str, ...]) -> None:
    op.drop_constraint("plantype", "subscriptions", type_="check")
    op.create_check_constraint("plantype", "subscriptions", sa.text(_in("plan", plans)))
    op.drop_constraint("subscription_comp_plan", "subscriptions", type_="check")
    # A NULL comp_plan passes the CHECK (SQL three-valued logic), as in a31300000001.
    op.create_check_constraint(
        "subscription_comp_plan", "subscriptions", sa.text(_in("comp_plan", plans))
    )
    op.drop_constraint("credittxntype", "credit_ledger", type_="check")
    op.create_check_constraint("credittxntype", "credit_ledger", sa.text(_in("type", txns)))


def upgrade() -> None:
    _checks(_NEW_PLANS, _NEW_TXNS)
    op.create_table(
        "academic_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("pending_email", sa.String(length=320), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("verified_email", sa.String(length=320), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_academic_verifications_user_id", "academic_verifications", ["user_id"], unique=True
    )
    op.create_index(
        "ix_academic_verifications_pending_email", "academic_verifications", ["pending_email"]
    )
    op.create_table(
        "academic_code_sends",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_academic_code_sends_address_created",
        "academic_code_sends",
        ["address", "created_at"],
    )
    op.create_index(
        "uq_academic_verifications_verified_email",
        "academic_verifications",
        ["verified_email"],
        unique=True,
        postgresql_where=sa.text("verified_email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("academic_code_sends")
    op.drop_table("academic_verifications")
    op.execute("UPDATE subscriptions SET plan = 'basic' WHERE plan = 'academic'")
    op.execute("UPDATE subscriptions SET comp_plan = NULL WHERE comp_plan = 'academic'")
    op.execute("UPDATE credit_ledger SET type = 'adjustment' WHERE type = 'academic_grant'")
    _checks(_OLD_PLANS, _OLD_TXNS)
