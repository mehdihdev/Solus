"""solusdev-102 add altium source type

Adds `altium` to the `sources.type` value set (SOLUSDEV-102). `SourceType` is a
portable VARCHAR + named CHECK constraint (`_enum_column`, native_enum=False), so
widening it means rebuilding that `sourcetype` CHECK. Done via `batch_alter_table`
so it applies on both Postgres (RDS) and the SQLite test DB.

Revision ID: 5c2c022b4d39
Revises: 1257e0b34736
Create Date: 2026-07-09 03:08:50.143570
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c2c022b4d39"
down_revision: str | None = "1257e0b34736"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE = ("github", "gitlab", "kicad", "onshape", "ros")
_WITH_ALTIUM = (*_BASE, "altium")


def _source_type(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(
        *values,
        name="sourcetype",
        native_enum=False,
        length=32,
        create_constraint=True,
    )


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.alter_column(
            "type",
            existing_type=_source_type(_BASE),
            type_=_source_type(_WITH_ALTIUM),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.alter_column(
            "type",
            existing_type=_source_type(_WITH_ALTIUM),
            type_=_source_type(_BASE),
            existing_nullable=False,
        )
