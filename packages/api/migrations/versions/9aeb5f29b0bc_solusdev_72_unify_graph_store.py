"""SOLUSDEV-72 unify graph store

Decision A: collapse the two parallel graph schemas into ONE `graph_entity` /
`graph_edge` pair (ADR-027 names) that absorbs the connector-runtime operational
columns (source_id / external_ref / origin / version). The standalone
`entities` / `relations` tables are removed; `kind` and `relation_type` become
free strings; the `Domain` enum gains `runtime`.

Everything is dev/test data, so this DROPS and RECREATES rather than migrating
rows. Drop the local dev DB before upgrading (this migration drops tables).

Revision ID: 9aeb5f29b0bc
Revises: f027db9277c2
Create Date: 2026-07-07 11:16:59.967293
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "9aeb5f29b0bc"
down_revision: str | None = "f027db9277c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical Domain vocabulary (A2): connector "software" reconciled to "code".
DOMAIN_NEW = ("code", "electrical", "mechanical", "simulation", "runtime")
DOMAIN_OLD = ("code", "electrical", "mechanical", "simulation")
ENTITY_KIND_OLD = ("code_file", "component", "part", "cad_body", "canonical_part")
RELATION_TYPE_OLD = ("references", "soldered_to", "mounted_on", "same_as")


def _domain_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="domain", native_enum=False, length=32, create_constraint=True)


def _recreate_error_solution_domain_check(values: tuple[str, ...]) -> None:
    """error_solution shares the Domain enum; keep its CHECK in step (alembic
    can't autodetect native-enum CHECK content changes)."""
    op.drop_constraint("domain", "error_solution", type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint("domain", "error_solution", f"domain IN ({allowed})")


def _create_unified_graph_entity() -> None:
    op.create_table(
        "graph_entity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),  # free string
        sa.Column("domain", _domain_enum(DOMAIN_NEW), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("canonical_part_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_connector", sa.String(length=64), nullable=True),
        sa.Column("external_ref", sa.String(length=512), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canonical_part_id"], ["graph_entity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_entity_project_id", "graph_entity", ["project_id"])
    op.create_index("ix_graph_entity_canonical_part_id", "graph_entity", ["canonical_part_id"])
    op.create_index("ix_graph_entity_source_id", "graph_entity", ["source_id"])
    op.create_index("ix_graph_entity_kind", "graph_entity", ["kind"])
    op.create_index("ix_graph_entity_deleted_at", "graph_entity", ["deleted_at"])
    op.create_index("ix_graph_entity_project_kind", "graph_entity", ["project_id", "kind"])
    op.create_index(
        "uq_graph_entity_source_ref",
        "graph_entity",
        ["source_id", "external_ref"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_graph_entity_embedding",
        "graph_entity",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def _create_unified_graph_edge() -> None:
    op.create_table(
        "graph_edge",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("src_id", sa.Uuid(), nullable=False),
        sa.Column("dst_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),  # free string
        sa.Column("domain_pair", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dst_id"], ["graph_entity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["src_id"], ["graph_entity.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_edge_project_id", "graph_edge", ["project_id"])
    op.create_index("ix_graph_edge_source_id", "graph_edge", ["source_id"])
    op.create_index("ix_graph_edge_src_id", "graph_edge", ["src_id"])
    op.create_index("ix_graph_edge_dst_id", "graph_edge", ["dst_id"])
    op.create_index("ix_graph_edge_deleted_at", "graph_edge", ["deleted_at"])
    op.create_index(
        "uq_graph_edge_source_edge",
        "graph_edge",
        ["source_id", "src_id", "dst_id", "relation_type"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def upgrade() -> None:
    # Drop the standalone connector tables (relations FKs entities → drop first).
    op.drop_table("relations")
    op.drop_table("entities")
    # Drop + recreate the graph pair in the unified shape (graph_edge FKs
    # graph_entity → drop edge first, create entity first).
    op.drop_table("graph_edge")
    op.drop_table("graph_entity")
    _create_unified_graph_entity()
    _create_unified_graph_edge()
    _recreate_error_solution_domain_check(DOMAIN_NEW)


def _create_legacy_graph_entity() -> None:
    op.create_table(
        "graph_entity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                *ENTITY_KIND_OLD,
                name="entitykind",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("domain", _domain_enum(DOMAIN_OLD), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("canonical_part_id", sa.Uuid(), nullable=True),
        sa.Column("source_connector", sa.String(length=64), nullable=True),
        sa.Column("external_ref", sa.String(length=512), nullable=True),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canonical_part_id"], ["graph_entity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_entity_project_id", "graph_entity", ["project_id"])
    op.create_index("ix_graph_entity_canonical_part_id", "graph_entity", ["canonical_part_id"])
    op.create_index("ix_graph_entity_deleted_at", "graph_entity", ["deleted_at"])
    op.create_index(
        "ix_graph_entity_embedding",
        "graph_entity",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def _create_legacy_graph_edge() -> None:
    op.create_table(
        "graph_edge",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("src_id", sa.Uuid(), nullable=False),
        sa.Column("dst_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relation_type",
            sa.Enum(
                *RELATION_TYPE_OLD,
                name="relationtype",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("domain_pair", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dst_id"], ["graph_entity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["src_id"], ["graph_entity.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_edge_project_id", "graph_edge", ["project_id"])
    op.create_index("ix_graph_edge_src_id", "graph_edge", ["src_id"])
    op.create_index("ix_graph_edge_dst_id", "graph_edge", ["dst_id"])
    op.create_index("ix_graph_edge_deleted_at", "graph_edge", ["deleted_at"])


def _create_legacy_entities() -> None:
    op.create_table(
        "entities",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("source_key", sa.String(length=1024), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("properties", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "source_key", name="uq_entity_source_key"),
    )
    op.create_index("ix_entities_domain", "entities", ["domain"])
    op.create_index("ix_entities_project_id", "entities", ["project_id"])
    op.create_index("ix_entities_project_type", "entities", ["project_id", "type"])
    op.create_index("ix_entities_source_id", "entities", ["source_id"])
    op.create_index("ix_entities_type", "entities", ["type"])


def _create_legacy_relations() -> None:
    op.create_table(
        "relations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("from_entity_id", sa.Uuid(), nullable=False),
        sa.Column("to_entity_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("properties", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "from_entity_id", "to_entity_id", "type", name="uq_relation_edge"
        ),
    )
    op.create_index("ix_relations_from_entity_id", "relations", ["from_entity_id"])
    op.create_index("ix_relations_project_id", "relations", ["project_id"])
    op.create_index("ix_relations_source_id", "relations", ["source_id"])
    op.create_index("ix_relations_to_entity_id", "relations", ["to_entity_id"])
    op.create_index("ix_relations_type", "relations", ["type"])


def downgrade() -> None:
    _recreate_error_solution_domain_check(DOMAIN_OLD)
    op.drop_table("graph_edge")
    op.drop_table("graph_entity")
    _create_legacy_graph_entity()
    _create_legacy_graph_edge()
    _create_legacy_entities()
    _create_legacy_relations()
