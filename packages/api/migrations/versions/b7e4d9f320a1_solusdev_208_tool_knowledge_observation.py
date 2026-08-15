"""solusdev-208 tool_knowledge_observation (SOLUS-TU-05, LANE D)

A SERVER-ONLY table recording one voter's verdict on one tool-knowledge entry,
so sharing/compounding can count DISTINCT voters without ever putting a
tenant-linkable reference on the cross-tenant entry. `voter_hash` is a salted
one-way hash (no user/team/project FK); the UNIQUE (knowledge_id, voter_hash)
is the anti-ballot-stuffing primitive. §7.3 design human-approved 2026-08-08.

Revision ID: b7e4d9f320a1
Revises: f2a9c4d15e07
Create Date: 2026-08-08 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4d9f320a1"
down_revision: str | None = "f2a9c4d15e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_knowledge_observation",
        sa.Column("knowledge_id", sa.Uuid(), nullable=False),
        sa.Column("voter_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                "confirm",
                "reject",
                name="verdict",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_id"], ["tool_knowledge.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_id", "voter_hash", name="uq_tk_observation_voter"),
    )
    op.create_index(
        op.f("ix_tool_knowledge_observation_knowledge_id"),
        "tool_knowledge_observation",
        ["knowledge_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tool_knowledge_observation")
