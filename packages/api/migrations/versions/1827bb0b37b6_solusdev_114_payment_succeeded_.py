"""solusdev-114 payment succeeded notification type

Widen the `notificationtype` CHECK on notifications to admit
'payment.succeeded' — the in-app confirmation emitted when a Stripe
checkout/plan change takes effect (models.NotificationType.PAYMENT_SUCCEEDED).
The enum is stored as a portable VARCHAR with a CHECK (models._enum_column),
so adding a Python enum member requires this DDL to keep inserts legal.

Revision ID: 1827bb0b37b6
Revises: e3a1c8f27b54
Create Date: 2026-08-07 13:52:24.620875
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Re-parented onto SOLUSDEV-136's HNSW migration when this branch rebased onto
# main — both originally revised 92499d574b9f, which would split the head.
revision: str = "1827bb0b37b6"
down_revision: str | None = "e3a1c8f27b54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VALUES = (
    "team.invite",
    "invite.accepted",
    "project.created",
    "payment.failed",
    "project.shared",
    "credit.low",
    "member.left",
)
_NEW_VALUES = (*_OLD_VALUES, "payment.succeeded")


def _values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint("notificationtype", "notifications", type_="check")
    op.create_check_constraint(
        "notificationtype",
        "notifications",
        sa.text(f"type IN ({_values_sql(_NEW_VALUES)})"),
    )


def downgrade() -> None:
    # Remove rows the narrower constraint would reject, then restore it.
    op.execute("DELETE FROM notifications WHERE type = 'payment.succeeded'")
    op.drop_constraint("notificationtype", "notifications", type_="check")
    op.create_check_constraint(
        "notificationtype",
        "notifications",
        sa.text(f"type IN ({_values_sql(_OLD_VALUES)})"),
    )
