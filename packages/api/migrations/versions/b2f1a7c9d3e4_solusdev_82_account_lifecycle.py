"""solusdev-82 account-lifecycle edges

Two schema changes for account deletion (SOLUSDEV-82 / SOLUS-FND-02):

1. `deleted_accounts` — a tombstone keyed by the Supabase `sub`, so a deleted
   identity cannot silently re-provision on a still-valid access token.
2. `credit_ledger.user_id` becomes nullable with an ON DELETE SET NULL foreign
   key. The append-only ledger must survive account deletion (ADR-024); on delete
   the FK is nulled (the record is anonymized, not destroyed) while a forfeiture
   ADJUSTMENT entry retains the user id in `attrs`.

Revision ID: b2f1a7c9d3e4
Revises: 5c2c022b4d39
Create Date: 2026-07-12 14:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2f1a7c9d3e4"
down_revision: str | None = "5c2c022b4d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEDGER_FK = "credit_ledger_user_id_fkey"
_NOTIFICATION_TYPES = [
    "team.invite",
    "invite.accepted",
    "project.created",
    "payment.failed",
    "project.shared",
    "credit.low",
]


def _set_notification_check(values: list[str]) -> None:
    op.drop_constraint("notificationtype", "notifications", type_="check")
    op.create_check_constraint("notificationtype", "notifications", sa.column("type").in_(values))


def upgrade() -> None:
    op.create_table(
        "deleted_accounts",
        sa.Column("supabase_user_id", sa.String(length=255), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_deleted_accounts_supabase_user_id"),
        "deleted_accounts",
        ["supabase_user_id"],
        unique=True,
    )

    # Preserve the append-only ledger past account deletion: nullable + SET NULL.
    op.alter_column("credit_ledger", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.drop_constraint(_LEDGER_FK, "credit_ledger", type_="foreignkey")
    op.create_foreign_key(
        _LEDGER_FK, "credit_ledger", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )

    # Widen the notification CHECK to cover the "member left" notification.
    _set_notification_check([*_NOTIFICATION_TYPES, "member.left"])


def downgrade() -> None:
    _set_notification_check(_NOTIFICATION_TYPES)

    op.drop_constraint(_LEDGER_FK, "credit_ledger", type_="foreignkey")
    op.create_foreign_key(
        _LEDGER_FK, "credit_ledger", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.alter_column("credit_ledger", "user_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_index(op.f("ix_deleted_accounts_supabase_user_id"), table_name="deleted_accounts")
    op.drop_table("deleted_accounts")
