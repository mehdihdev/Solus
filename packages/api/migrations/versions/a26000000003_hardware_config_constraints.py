"""SOLUSDEV-260: enforce hardware subject invariants after validated backfill."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a26000000003"
down_revision: str | None = "a26000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_solus_config_subject_live",
        "solus_entries",
        ["project_id", "configured_entity_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'config' AND deleted_at IS NULL"),
    )
    op.create_check_constraint(
        "ck_solus_config_subject",
        "solus_entries",
        "config_version >= 0 AND (kind = 'config' OR "
        "(configured_entity_id IS NULL AND config_version = 0))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_solus_config_subject", "solus_entries", type_="check")
    op.drop_index("uq_solus_config_subject_live", table_name="solus_entries")
