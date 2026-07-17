"""solusdev-135 add sol conversations

The SOL chat backend's persistence (SOLUS-SYS-01): a project-scoped, owner-private
`conversations` session table and its append-only `conversation_turns` log. A
follow-on to the W0-01 schema — it does not edit earlier migrations.

Revision ID: b3d9c1a4e7f2
Revises: 5c2c022b4d39
Create Date: 2026-07-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3d9c1a4e7f2"
down_revision: str | None = "5c2c022b4d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_created_by"), "conversations", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_conversations_deleted_at"), "conversations", ["deleted_at"], unique=False
    )
    op.create_index(
        op.f("ix_conversations_project_id"), "conversations", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_conversations_team_id"), "conversations", ["team_id"], unique=False)
    op.create_index(
        "ix_conversations_project_owner",
        "conversations",
        ["project_id", "created_by"],
        unique=False,
    )

    op.create_table(
        "conversation_turns",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                "tool",
                name="turnrole",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_turns_conversation_id"),
        "conversation_turns",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_turns_project_id"),
        "conversation_turns",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_turns_conversation_created",
        "conversation_turns",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_conversation_created", table_name="conversation_turns")
    op.drop_index(op.f("ix_conversation_turns_project_id"), table_name="conversation_turns")
    op.drop_index(op.f("ix_conversation_turns_conversation_id"), table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index("ix_conversations_project_owner", table_name="conversations")
    op.drop_index(op.f("ix_conversations_team_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_project_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_deleted_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_created_by"), table_name="conversations")
    op.drop_table("conversations")
