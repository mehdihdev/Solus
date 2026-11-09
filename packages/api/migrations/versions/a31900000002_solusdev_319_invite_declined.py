"""SOLUSDEV-319 (multi-team Home): an invitee can decline an invite.

- The `invitestatus` CHECK on `invites.status` admits `declined`.
- The `notificationtype` CHECK admits `invite.declined` (the inviter is told).

Downgrade turns any declined invite back into `revoked` (the closest earlier meaning: the
invite is closed and cannot be used) and drops `invite.declined` notifications before the
CHECKs narrow again.

Revision ID: a31900000002
Revises: a32100000001
Create Date: 2026-11-06 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a31900000002"
down_revision: str | None = "a32100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = ("pending", "accepted", "revoked")
_NEW_STATUS = "declined"
_OLD_TYPES = (
    "team.invite",
    "invite.accepted",
    "project.created",
    "payment.failed",
    "project.shared",
    "credit.low",
    "member.left",
    "payment.succeeded",
    "subscription.canceled",
    "subscription.resumed",
    "subscription.ended",
    "github_org.member_removed",
)
_NEW_TYPE = "invite.declined"


def _values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _set_check(name: str, table: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, sa.text(f"{column} IN ({_values_sql(values)})"))


def upgrade() -> None:
    _set_check("invitestatus", "invites", "status", (*_OLD_STATUSES, _NEW_STATUS))
    _set_check("notificationtype", "notifications", "type", (*_OLD_TYPES, _NEW_TYPE))


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE invites SET status = 'revoked' WHERE status = :status").bindparams(
            status=_NEW_STATUS
        )
    )
    op.execute(sa.text("DELETE FROM notifications WHERE type = :type").bindparams(type=_NEW_TYPE))
    _set_check("invitestatus", "invites", "status", _OLD_STATUSES)
    _set_check("notificationtype", "notifications", "type", _OLD_TYPES)
