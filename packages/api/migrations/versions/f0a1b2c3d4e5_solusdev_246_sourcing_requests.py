"""SOLUSDEV-246 (STORE ST5): sourcing requests — one engine for two doors.

`sourcing_requests`: the requirement, the derived torque, the job, the
candidates / exclusions (the model's answer stored as data) and the selection.
`jobs.kind` gains `sourcing` (the CHECK is recreated with the union).

Revision ID: f0a1b2c3d4e5
Revises: a9c0d1e2f3b4
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f0a1b2c3d4e5"
down_revision = "a9c0d1e2f3b4"
branch_labels = None
depends_on = None

TABLE = "sourcing_requests"
JOB_KINDS_BEFORE = (
    "sync",
    "check_run",
    "proving",
    "fingerprint_scan",
    "sim_rebuild",
    "extension_review",
)
JOB_KINDS_AFTER = (*JOB_KINDS_BEFORE, "sourcing")
STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


def _job_kind_check(values: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint("jobkind", "jobs", type_="check")
    op.create_check_constraint("jobkind", "jobs", _job_kind_check(JOB_KINDS_AFTER))
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "status",
            sa.Enum(
                *STATUSES, name="jobstatus", native_enum=False, create_constraint=True, length=32
            ),
            nullable=False,
        ),
        sa.Column("door", sa.String(16), nullable=False, server_default="bom"),
        sa.Column(
            "spec", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("torque", postgresql.JSONB(), nullable=True),
        sa.Column("assembly_entity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "candidates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "excluded", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "rules", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("selected_candidate_id", sa.String(32), nullable=True),
        sa.Column("selected_entity_id", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sourcing_requests_project_id", TABLE, ["project_id"])
    op.create_index("ix_sourcing_requests_created_by", TABLE, ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_sourcing_requests_created_by", table_name=TABLE)
    op.drop_index("ix_sourcing_requests_project_id", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_constraint("jobkind", "jobs", type_="check")
    op.create_check_constraint("jobkind", "jobs", _job_kind_check(JOB_KINDS_BEFORE))
