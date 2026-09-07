"""solusdev-248 R5: structured Hardware-configs entries and link suggestions.

Revision ID: 8f1c2a7d4e90
Revises: c7f242e9a842

`solus_entries` gains `kind = 'config'` and a nullable JSONB `payload` (the HardwareConfig
document, validated by its Pydantic model on every write — ADR-034 amendment 2026-09-06).
`hardware_suggestions` holds the link-suggestion engine's durable rows (docs/api/hardware.md §3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8f1c2a7d4e90"
down_revision: str | None = "c7f242e9a842"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = ("text", "artifact", "sol")
_NEW_KINDS = (*_OLD_KINDS, "config")
_STATUSES = ("pending", "accepted", "rejected", "superseded")


def _values_sql(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column(
        "solus_entries",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_constraint("solusentrykind", "solus_entries", type_="check")
    op.create_check_constraint(
        "solusentrykind", "solus_entries", sa.text(f"kind IN ({_values_sql(_NEW_KINDS)})")
    )
    op.create_table(
        "hardware_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("candidate_robot_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("tier", sa.String(length=8), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *_STATUSES,
                name="suggestionstatus",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_robot_id"], ["graph_entity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hardware_suggestions_project_id", "hardware_suggestions", ["project_id"])
    op.create_index(
        "ix_hardware_suggestions_candidate_robot_id",
        "hardware_suggestions",
        ["candidate_robot_id"],
    )
    op.create_index(
        "ix_hardware_suggestions_project_status",
        "hardware_suggestions",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_hardware_suggestions_project_status", table_name="hardware_suggestions")
    op.drop_index("ix_hardware_suggestions_candidate_robot_id", table_name="hardware_suggestions")
    op.drop_index("ix_hardware_suggestions_project_id", table_name="hardware_suggestions")
    op.drop_table("hardware_suggestions")
    op.execute("DELETE FROM solus_entries WHERE kind = 'config'")
    op.drop_constraint("solusentrykind", "solus_entries", type_="check")
    op.create_check_constraint(
        "solusentrykind", "solus_entries", sa.text(f"kind IN ({_values_sql(_OLD_KINDS)})")
    )
    op.drop_column("solus_entries", "payload")
