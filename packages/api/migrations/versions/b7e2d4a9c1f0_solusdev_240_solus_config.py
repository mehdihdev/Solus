"""solusdev-240 project .solus: `project` domain, retained artifacts, solus_entries

Revision ID: b7e2d4a9c1f0
Revises: c88cbf6c3388
Create Date: 2026-09-05 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d4a9c1f0"
down_revision: str | None = "c88cbf6c3388"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOMAIN_OLD = ("code", "electrical", "mechanical", "simulation", "runtime")
DOMAIN_NEW = (*DOMAIN_OLD, "project")
SECTIONS = ("hardware", "details", "errors", "docs", "code")
KINDS = ("text", "artifact", "sol")


def _recreate_domain_check(table: str, values: tuple[str, ...]) -> None:
    """The Domain enum is a VARCHAR + CHECK (`_enum_column`); alembic cannot
    autodetect a CHECK content change, so recreate it by hand on both tables."""
    op.drop_constraint("domain", table, type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint("domain", table, f"domain IN ({allowed})")


def _varchar_enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32, create_constraint=True)


def upgrade() -> None:
    _recreate_domain_check("graph_entity", DOMAIN_NEW)
    _recreate_domain_check("error_solution", DOMAIN_NEW)
    op.add_column(
        "artifacts",
        sa.Column("retained", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "solus_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("section", _varchar_enum("solussection", SECTIONS), nullable=False),
        sa.Column("kind", _varchar_enum("solusentrykind", KINDS), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_solus_entries_project_id", "solus_entries", ["project_id"])
    op.create_index("ix_solus_entries_deleted_at", "solus_entries", ["deleted_at"])
    op.create_index("ix_solus_entries_project_section", "solus_entries", ["project_id", "section"])


def downgrade() -> None:
    op.drop_table("solus_entries")
    op.drop_column("artifacts", "retained")
    op.execute("DELETE FROM graph_entity WHERE domain = 'project'")
    op.execute("DELETE FROM error_solution WHERE domain = 'project'")
    _recreate_domain_check("graph_entity", DOMAIN_OLD)
    _recreate_domain_check("error_solution", DOMAIN_OLD)
