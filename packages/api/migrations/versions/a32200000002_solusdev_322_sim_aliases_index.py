"""SOLUSDEV-322 P5-T2: index the `sim_aliases` rows a sim session's packets resolve by.

Revision ID: a32200000002
Revises: a32200000001
Create Date: 2026-11-09

`DbEntityResolver.resolve(..., source=<provider>)` asks, once per unresolved packet,
`attrs -> 'sim_aliases' @> '[{"provider": ..., "device_id": ...}]'`. A GIN `jsonb_path_ops`
index on exactly that expression serves the containment; it is partial on the rows that carry
aliases at all (`attrs ? 'sim_aliases'`), so parts nobody mapped cost it nothing. The downgrade
drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a32200000002"
down_revision: str | None = "a32200000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "graph_entity"
INDEX = "ix_graph_entity_sim_aliases"


def upgrade() -> None:
    op.create_index(
        INDEX,
        TABLE,
        [sa.text("(attrs -> 'sim_aliases') jsonb_path_ops")],
        postgresql_using="gin",
        postgresql_where=sa.text("attrs ? 'sim_aliases'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
