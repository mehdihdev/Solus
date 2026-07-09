"""add graph_entity modality_hints

Decision B (SOLUSDEV-72): the connector `EntityOut` regains a dedicated
`modality_hints` channel (the bridge to the multimodal fingerprint matcher,
W0-06). It lands in its own JSONB column on `graph_entity` — kept separate from
`attrs` so the matcher queries it directly. Additive; existing rows default to
`{}`.

Revision ID: 62682120a0a7
Revises: 9aeb5f29b0bc
Create Date: 2026-07-08 02:10:50.793806
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "62682120a0a7"
down_revision: str | None = "9aeb5f29b0bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "graph_entity",
        sa.Column(
            "modality_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("graph_entity", "modality_hints")
