"""solusdev_136 hnsw embedding indexes

ADR-027 as amended 2026-08-07 (SYS-02): both pgvector embedding indexes move from
ivfflat (lists=100, trained on EMPTY tables — degenerate centroids until a manual
REINDEX nobody scheduled) to HNSW (m=16, ef_construction=64), which builds
incrementally and is correct when created empty. Drop+create is instant at the
current corpus (~0 rows), well inside the entrypoint migration budget
(SOLUS_MIGRATE_TIMEOUT_SECONDS, 120s). Any FUTURE vector-index change at >=10^5
rows must instead use CREATE INDEX CONCURRENTLY out-of-band.

Revision ID: e3a1c8f27b54
Revises: 92499d574b9f
Create Date: 2026-08-07 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3a1c8f27b54"
down_revision: str | None = "92499d574b9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("ix_graph_entity_embedding", "graph_entity"),
    ("ix_error_solution_embedding", "error_solution"),
)


def upgrade() -> None:
    for name, table in _INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(
            name,
            table,
            ["embedding"],
            unique=False,
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    for name, table in _INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(
            name,
            table,
            ["embedding"],
            unique=False,
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
