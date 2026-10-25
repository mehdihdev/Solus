"""SOLUSDEV-320 P5-T7: history rows name the entities they touch (docs/api/solus.md §9).

Revision ID: a32000000005
Revises: a32000000004

`activities.entity_ids` (JSONB array of graph entity ids, `'[]'` for every existing row and
for writers that predate the column), `activities.why_ref` (a conversation, decision entry or
finding id), a GIN `jsonb_path_ops` index for the `entity_ids @> '["<id>"]'` filter and the
`(project_id, created_at)` index the project history page scans. `domain` already exists
(resolution 19). The downgrade removes all four.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a32000000005"
down_revision: str | None = "a32000000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_INDEX = "ix_activities_entity_ids"
PROJECT_INDEX = "ix_activities_project_created"


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("entity_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("activities", sa.Column("why_ref", sa.String(128), nullable=True))
    op.create_index(
        ENTITY_INDEX,
        "activities",
        ["entity_ids"],
        postgresql_using="gin",
        postgresql_ops={"entity_ids": "jsonb_path_ops"},
    )
    op.create_index(PROJECT_INDEX, "activities", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index(PROJECT_INDEX, table_name="activities")
    op.drop_index(ENTITY_INDEX, table_name="activities")
    op.drop_column("activities", "why_ref")
    op.drop_column("activities", "entity_ids")
