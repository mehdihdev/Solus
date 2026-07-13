"""SOLUSDEV-59 FP-02: graph_entity.canonical_key + per-project idempotency index.

Canonical part entities (kind="canonical_part", origin="fingerprint", source_id
NULL) are PROJECT-scoped: the matcher's uuid5 canonical_id is project-agnostic
and would collide as a global PK, so the uuid7 PK stays (ADR-027 untouched) and
idempotent upsert keys on (project_id, canonical_key) among live rows. The
canonical_key IS NOT NULL guard is required: the index is composite with the
always-present project_id, so without it two same-project rows with NULL keys
would both be indexed. A cross-project/global parts library is deliberately out
of scope (cross-tenant isolation).

Revision ID: 9b0d77b7acd2
Revises: 8d4f2a91c6e3
Create Date: 2026-07-12 11:38:12.292453
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b0d77b7acd2"
down_revision: str | None = "8d4f2a91c6e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("graph_entity", sa.Column("canonical_key", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_graph_entity_project_canonical_key",
        "graph_entity",
        ["project_id", "canonical_key"],
        unique=True,
        postgresql_where=sa.text("canonical_key IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_graph_entity_project_canonical_key", table_name="graph_entity")
    op.drop_column("graph_entity", "canonical_key")
