"""SOLUSDEV-320: `solus_entries.subsection` and the widened section CHECK.

Revision ID: a32000000002
Revises: a32000000001

The five `.solus` sections become seven with subsections (docs/api/solus.md §1). This
revision is DDL only: the nullable `subsection` column and a CHECK `solussection` that
holds the old and the new vocabularies while a32000000003 moves the rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a32000000002"
down_revision: str | None = "a32000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SECTIONS = ("hardware", "details", "errors", "docs", "code")
NEW_SECTIONS = (
    "goals",
    "constraints",
    "documentation",
    "errors",
    "environment",
    "members",
    "history",
)
BOTH = (*OLD_SECTIONS, *(s for s in NEW_SECTIONS if s not in OLD_SECTIONS))


def _section_check(values: Sequence[str]) -> None:
    op.drop_constraint("solussection", "solus_entries", type_="check")
    op.create_check_constraint(
        "solussection", "solus_entries", sa.column("section").in_(list(values))
    )


def upgrade() -> None:
    op.add_column("solus_entries", sa.Column("subsection", sa.String(length=32), nullable=True))
    _section_check(BOTH)


def downgrade() -> None:
    _section_check(OLD_SECTIONS)
    op.drop_column("solus_entries", "subsection")
