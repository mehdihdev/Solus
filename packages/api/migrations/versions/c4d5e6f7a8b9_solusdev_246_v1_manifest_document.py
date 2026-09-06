"""SOLUSDEV-246 (STORE ST2 real-run fix): store v1 manifests as authored.

Versions published between the ST1 contract bump and this fix were stored as a
bare `model_dump`, so a schema_version 1 manifest carried the defaulted v2 tables
(`backend`/`graph`/`tools`) — which its own re-parse rejects as unknown fields on
install and on the desktop. Strip them from every stored v1 manifest; a v1
manifest can never legitimately carry those keys, so this is lossless.

Revision ID: c4d5e6f7a8b9
Revises: b3f1c2d4e5a6
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b3f1c2d4e5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE extension_versions "
            "SET manifest = (manifest - 'backend') - 'graph' - 'tools' "
            "WHERE manifest->>'schema_version' = '1' "
            "AND (manifest ? 'backend' OR manifest ? 'graph' OR manifest ? 'tools')"
        )
    )


def downgrade() -> None:
    # Nothing to restore: the stripped keys were defaults a v1 manifest never had.
    pass
