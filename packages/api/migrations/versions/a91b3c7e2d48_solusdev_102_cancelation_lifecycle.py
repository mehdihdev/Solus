"""solusdev-102 cancellation lifecycle: subscriptions.cancel_at + notification types

Two pieces of the cancel flow (SOLUSDEV-102 follow-up):
- `subscriptions.cancel_at` — the pending cancel-at-period-end moment from
  Stripe; drives the billing-page "your plan ends on X" bar.
- Widen the `notificationtype` CHECK on notifications to admit
  'subscription.canceled' / 'subscription.resumed' / 'subscription.ended'
  (models.NotificationType additions; VARCHAR+CHECK per models._enum_column).

Revision ID: a91b3c7e2d48
Revises: f4a8c21d9e05
Create Date: 2026-08-08 13:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a91b3c7e2d48"
down_revision: str | None = "f4a8c21d9e05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = (
    "team.invite",
    "invite.accepted",
    "project.created",
    "payment.failed",
    "project.shared",
    "credit.low",
    "member.left",
    "payment.succeeded",
)
_NEW_TYPES = (
    *_OLD_TYPES,
    "subscription.canceled",
    "subscription.resumed",
    "subscription.ended",
)


def _values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("notificationtype", "notifications", type_="check")
    op.create_check_constraint(
        "notificationtype",
        "notifications",
        sa.text(f"type IN ({_values_sql(_NEW_TYPES)})"),
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM notifications WHERE type IN "
        "('subscription.canceled', 'subscription.resumed', 'subscription.ended')"
    )
    op.drop_constraint("notificationtype", "notifications", type_="check")
    op.create_check_constraint(
        "notificationtype",
        "notifications",
        sa.text(f"type IN ({_values_sql(_OLD_TYPES)})"),
    )
    op.drop_column("subscriptions", "cancel_at")
