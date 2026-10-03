"""ADR-038 §1: durable CAD purge requests (delete-on-revocation that cannot be lost).

Revision ID: a38000000001
Revises: a26200000001
Create Date: 2026-10-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a38000000001"
down_revision: str | None = "a26200000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cad_purge_requests",
        sa.Column("account_hash", sa.String(length=64), nullable=False),
        sa.Column("passes_remaining", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cad_purge_requests_account_hash", "cad_purge_requests", ["account_hash"], unique=True
    )
    op.create_index(
        "ix_cad_purge_requests_next_attempt_at", "cad_purge_requests", ["next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_cad_purge_requests_next_attempt_at", table_name="cad_purge_requests")
    op.drop_index("ix_cad_purge_requests_account_hash", table_name="cad_purge_requests")
    op.drop_table("cad_purge_requests")
