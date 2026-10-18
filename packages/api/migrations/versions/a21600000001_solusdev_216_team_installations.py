"""SOLUSDEV-216: team GitHub App installations (ADR-039).

- `team_installations` (live-row partial uniques) and `github_webhook_deliveries`.
- `sources.installation_id` (FK SET NULL) with a CHECK against also carrying a connection.
- `invites.email` becomes nullable; `github_user_id` / `github_login` added with an
  exactly-one-of CHECK and a pending-invite partial index.
- `oauth_states.team_id` (FK CASCADE) carries the install handshake's team.
- The `notificationtype` CHECK admits `github_org.member_removed`.

Revision ID: a21600000001
Revises: a31300000001
Create Date: 2026-10-17 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a21600000001"
down_revision: str | None = "a31300000001"
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
    "subscription.canceled",
    "subscription.resumed",
    "subscription.ended",
)
_NEW_TYPE = "github_org.member_removed"
_LIVE = sa.text("deleted_at IS NULL")


def _values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _set_notification_check(values: tuple[str, ...]) -> None:
    op.drop_constraint("notificationtype", "notifications", type_="check")
    op.create_check_constraint(
        "notificationtype", "notifications", sa.text(f"type IN ({_values_sql(values)})")
    )


def upgrade() -> None:
    op.create_table(
        "team_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=255), nullable=False),
        sa.Column("account_external_id", sa.BigInteger(), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("account_avatar_url", sa.String(length=512), nullable=True),
        sa.Column("repository_selection", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("api_base_url", sa.String(length=255), nullable=False),
        sa.Column("web_base_url", sa.String(length=255), nullable=False),
        sa.Column("linked_by", sa.Uuid(), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'revoked')", name="installationstatus"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_team_installations_team_id", "team_installations", ["team_id"])
    op.create_index("ix_team_installations_deleted_at", "team_installations", ["deleted_at"])
    op.create_index(
        "uq_team_installations_provider_external",
        "team_installations",
        ["provider", "external_installation_id"],
        unique=True,
        postgresql_where=_LIVE,
    )
    op.create_index(
        "uq_team_installations_team_provider",
        "team_installations",
        ["team_id", "provider"],
        unique=True,
        postgresql_where=_LIVE,
    )

    op.create_table(
        "github_webhook_deliveries",
        sa.Column("delivery_id", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("delivery_id"),
    )
    op.create_index(
        "ix_github_webhook_deliveries_received_at", "github_webhook_deliveries", ["received_at"]
    )

    op.add_column("sources", sa.Column("installation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "sources_installation_id_fkey",
        "sources",
        "team_installations",
        ["installation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sources_installation_id", "sources", ["installation_id"])
    op.create_check_constraint(
        "sources_installation_xor_connection",
        "sources",
        "installation_id IS NULL OR connection_id IS NULL",
    )

    op.alter_column("invites", "email", existing_type=sa.String(length=320), nullable=True)
    op.add_column("invites", sa.Column("github_user_id", sa.BigInteger(), nullable=True))
    op.add_column("invites", sa.Column("github_login", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "invites_email_xor_github_user",
        "invites",
        "(email IS NOT NULL) <> (github_user_id IS NOT NULL)",
    )
    op.create_index(
        "ix_invites_team_github_user_pending",
        "invites",
        ["team_id", "github_user_id"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.add_column("oauth_states", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "oauth_states_team_id_fkey",
        "oauth_states",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )

    _set_notification_check((*_OLD_TYPES, _NEW_TYPE))


def downgrade() -> None:
    op.execute(f"DELETE FROM notifications WHERE type = '{_NEW_TYPE}'")
    _set_notification_check(_OLD_TYPES)

    op.drop_constraint("oauth_states_team_id_fkey", "oauth_states", type_="foreignkey")
    op.drop_column("oauth_states", "team_id")

    # GitHub-user invites have no email, so they cannot survive NOT NULL: delete them first.
    op.drop_index("ix_invites_team_github_user_pending", table_name="invites")
    op.drop_constraint("invites_email_xor_github_user", "invites", type_="check")
    op.execute("DELETE FROM invites WHERE email IS NULL")
    op.drop_column("invites", "github_login")
    op.drop_column("invites", "github_user_id")
    op.alter_column("invites", "email", existing_type=sa.String(length=320), nullable=False)

    op.drop_constraint("sources_installation_xor_connection", "sources", type_="check")
    op.drop_index("ix_sources_installation_id", table_name="sources")
    op.drop_constraint("sources_installation_id_fkey", "sources", type_="foreignkey")
    op.drop_column("sources", "installation_id")

    op.drop_index("ix_github_webhook_deliveries_received_at", table_name="github_webhook_deliveries")
    op.drop_table("github_webhook_deliveries")

    op.drop_index("uq_team_installations_team_provider", table_name="team_installations")
    op.drop_index("uq_team_installations_provider_external", table_name="team_installations")
    op.drop_index("ix_team_installations_deleted_at", table_name="team_installations")
    op.drop_index("ix_team_installations_team_id", table_name="team_installations")
    op.drop_table("team_installations")
