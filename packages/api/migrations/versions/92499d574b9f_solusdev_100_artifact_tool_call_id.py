"""solusdev_100 add artifacts.tool_call_id

Anti-forgery anchor for the bridge acquirer's §4.3 one-shot consumption check
(docs/api/artifacts.md): which W0-04 ToolCall this upload fulfils. Nullable —
pre-existing/non-tool-fulfilling artifacts have none. Indexed for the
acquirer's per-call lookup.

Revision ID: 92499d574b9f
Revises: a7c5d2e91f04
Create Date: 2026-08-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "92499d574b9f"
down_revision: str | None = "a7c5d2e91f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("tool_call_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_artifacts_tool_call_id"), "artifacts", ["tool_call_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_tool_call_id"), table_name="artifacts")
    op.drop_column("artifacts", "tool_call_id")
