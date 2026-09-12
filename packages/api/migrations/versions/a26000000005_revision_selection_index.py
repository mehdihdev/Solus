"""Index revision references for bounded cascade cleanup."""

from collections.abc import Sequence

from alembic import op

revision: str = "a26000000005"
down_revision: str | None = "a26000000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_source_view_selections_active_revision_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX, "source_view_selections", ["active_revision_id"], postgresql_concurrently=True
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(INDEX, table_name="source_view_selections", postgresql_concurrently=True)
