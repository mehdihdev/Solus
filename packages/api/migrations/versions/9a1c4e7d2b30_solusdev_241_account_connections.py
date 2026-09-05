"""SOLUSDEV-241 (I1): account-scoped connections

OAuth binds at ACCOUNT scope. One `account_connections` row per provider grant
per user; a project attaches through `sources.connection_id` and mirrors the
connection's secret ref. `oauth_states.source_id` becomes nullable — a
Home-started handshake has no project and no source — and the state row now
names the connection (and the project, when there is one) it completes.

Revision ID: 9a1c4e7d2b30
Revises: c88cbf6c3388
Create Date: 2026-09-05

"""

import sqlalchemy as sa
from alembic import op

revision = "9a1c4e7d2b30"
down_revision = "c88cbf6c3388"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> sa.Enum:
    # Portable VARCHAR + CHECK, the convention every enum column here follows.
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    op.create_table(
        "account_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "provider",
            _enum("sourcetype", "github", "gitlab", "kicad", "onshape", "ros", "altium"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("connectionstatus", "pending", "connected", "error", "revoked"),
            nullable=False,
        ),
        sa.Column("account_login", sa.String(length=255), nullable=True),
        sa.Column("account_external_id", sa.String(length=255), nullable=True),
        sa.Column("secret_ref", sa.String(length=512), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_connections_user_id", "account_connections", ["user_id"])

    op.add_column(
        "sources",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("account_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_sources_connection_id", "sources", ["connection_id"])

    op.alter_column("oauth_states", "source_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column(
        "oauth_states",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("account_connections.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_oauth_states_connection_id", "oauth_states", ["connection_id"])
    op.add_column(
        "oauth_states",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("oauth_states", "project_id")
    op.drop_index("ix_oauth_states_connection_id", table_name="oauth_states")
    op.drop_column("oauth_states", "connection_id")
    # Rows minted by a Home-started handshake have no source; they are short
    # lived (10 minutes) and safe to drop before the NOT NULL comes back.
    op.execute("DELETE FROM oauth_states WHERE source_id IS NULL")
    op.alter_column("oauth_states", "source_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_sources_connection_id", table_name="sources")
    op.drop_column("sources", "connection_id")
    op.drop_index("ix_account_connections_user_id", table_name="account_connections")
    op.drop_table("account_connections")
