"""solusdev-241 CORPUS C2: corpus_chunk, corpus_citation, corpus_release (ADR-036)

Revision ID: a9c0d1e2f3b4
Revises: e1f2a3b4c5d6
Create Date: 2026-09-06 14:00:00.000000

Global, tenant-free tables (no project/team/user column, no FK to them). Every
categorical column is a VARCHAR + CHECK enum; prose is bounded; citations are a
typed child table. Written only by `solus_api.corpus.ingest`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "a9c0d1e2f3b4"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOMAINS = ("mechanical", "electrical", "software", "systems", "robotics")
TOPICS = (
    "gdt", "fits_tolerances", "fasteners", "material_selection", "machining_constraints",
    "bearings_shafts", "mechanisms",
    "trace_width_current", "clearance_creepage", "decoupling", "grounding", "emi_basics",
    "power_design", "wire_gauge", "connector_selection", "signal_integrity", "bus_addressing",
    "analog_frontend", "motor_drive_electrical", "pcb_layout_basics",
    "embedded_patterns", "real_time_constraints", "embedded_testing", "ros_conventions",
    "build_and_toolchain", "serial_protocols", "firmware_deployment",
    "power_budget", "thermal_budget", "safety_interlocks", "enclosure_ingress",
    "cabling_harness", "system_integration",
    "actuator_selection", "kinematics_basics", "dynamics_basics", "sensor_fusion_basics",
    "control_tuning", "perception_basics", "simulation_fidelity", "locomotion_basics",
)  # fmt: skip
KINDS = ("principle", "procedure", "rule_of_thumb", "reference_value", "pitfall", "glossary")
AUDIENCES = ("fundamentals", "reference")
DERIVATIONS = ("verbatim", "summary", "facts_extracted", "solus_original")
SOURCE_CLASSES = (
    "solus_authored", "us_government_work", "open_license_permissive",
    "open_license_restricted", "vendor_documentation", "datasheet", "standards_body",
    "open_source_project_docs", "academic_paper",
)  # fmt: skip
SOURCE_LICENSES = (
    "CC0-1.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0", "MIT", "BSD-2-Clause", "BSD-3-Clause",
    "Apache-2.0", "ISC", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND-4.0", "CC-BY-ND-4.0", "GFDL-1.3-only", "GPL-2.0-only", "GPL-3.0-only",
    "public-domain-us-gov", "vendor-terms", "datasheet-terms", "standard-summary",
    "arxiv-nonexclusive", "solus-proprietary", "unknown",
)  # fmt: skip
CONFIDENCE_BASES = (
    "standard_derived", "vendor_stated", "government_published", "peer_reviewed",
    "solus_measured", "rule_of_thumb", "consensus",
)  # fmt: skip
DRAFTINGS = ("human", "llm_assisted")
STATUSES = ("draft", "active", "superseded", "withdrawn")
LICENSES = ("solus-proprietary",)
CITATION_ROLES = ("further_reading", "checked_against")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "corpus_chunk",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("domain", _enum("corpusdomain", DOMAINS), nullable=False),
        sa.Column("topic", _enum("topic", TOPICS), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", _enum("kind", KINDS), nullable=False),
        sa.Column("audience", _enum("audience", AUDIENCES), nullable=False),
        sa.Column("applicability", postgresql.ARRAY(sa.String(length=48)), nullable=False),
        sa.Column("derivation", _enum("derivation", DERIVATIONS), nullable=False),
        sa.Column("source_class", _enum("sourceclass", SOURCE_CLASSES), nullable=False),
        sa.Column("source_title", sa.String(length=200), nullable=False),
        sa.Column("source_publisher", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.String(length=400), nullable=True),
        sa.Column("source_locator", sa.String(length=200), nullable=False),
        sa.Column("source_license", _enum("sourcelicense", SOURCE_LICENSES), nullable=False),
        sa.Column("accessed_at", sa.Date(), nullable=False),
        sa.Column("attribution", sa.String(length=600), nullable=False),
        sa.Column("license", _enum("license", LICENSES), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_basis", _enum("confidencebasis", CONFIDENCE_BASES), nullable=False),
        sa.Column("drafting", _enum("drafting", DRAFTINGS), nullable=False),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.Date(), nullable=False),
        sa.Column("status", _enum("status", STATUSES), nullable=False),
        sa.Column("supersedes", sa.String(length=120), nullable=True),
        sa.Column("related", postgresql.ARRAY(sa.String(length=120)), nullable=False),
        sa.Column("corpus_version", sa.String(length=32), nullable=False),
        sa.Column("revised_in", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=72), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_corpus_chunk_confidence"),
        sa.CheckConstraint("char_length(body) <= 6000", name="ck_corpus_chunk_body_cap"),
        sa.CheckConstraint("status <> 'withdrawn' OR body = ''", name="ck_corpus_chunk_withdrawn"),
        sa.CheckConstraint("cardinality(applicability) <= 16", name="ck_corpus_chunk_applicability"),
        sa.CheckConstraint("cardinality(related) <= 12", name="ck_corpus_chunk_related"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_corpus_chunk_serve", "corpus_chunk", ["status", "domain", "topic"])
    op.create_index(
        "ix_corpus_chunk_embedding",
        "corpus_chunk",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "corpus_citation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.String(length=120), nullable=False),
        sa.Column("role", _enum("citationrole", CITATION_ROLES), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column("identifier", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=400), nullable=True),
        sa.CheckConstraint("position >= 0 AND position < 8", name="ck_corpus_citation_position"),
        sa.ForeignKeyConstraint(["chunk_id"], ["corpus_chunk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id", "role", "position", name="uq_corpus_citation_position"),
    )
    op.create_index("ix_corpus_citation_chunk_id", "corpus_citation", ["chunk_id"])
    op.create_table(
        "corpus_release",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version", sa.String(length=32), nullable=False),
        sa.Column("policy_revision", sa.String(length=200), nullable=False),
        sa.Column("released_at", sa.Date(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=72), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corpus_version"),
    )


def downgrade() -> None:
    op.drop_table("corpus_release")
    op.drop_index("ix_corpus_citation_chunk_id", table_name="corpus_citation")
    op.drop_table("corpus_citation")
    op.drop_index("ix_corpus_chunk_embedding", table_name="corpus_chunk")
    op.drop_index("ix_corpus_chunk_serve", table_name="corpus_chunk")
    op.drop_table("corpus_chunk")
