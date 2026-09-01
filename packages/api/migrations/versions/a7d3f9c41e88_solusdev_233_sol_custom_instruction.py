"""solusdev-233 user sol_custom_instruction

Per-user standing preference note for SOL (SOLUSDEV-233). Reaches the prompt
only as a nonce-fenced data block (agent/prompt.py CUSTOM_INSTRUCTION_CAP);
the column cap mirrors the prompt-side cap.

Revision ID: a7d3f9c41e88
Revises: 07c4da2feccf
Create Date: 2026-08-31 20:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d3f9c41e88"
down_revision: str | None = "07c4da2feccf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sol_custom_instruction", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sol_custom_instruction")
