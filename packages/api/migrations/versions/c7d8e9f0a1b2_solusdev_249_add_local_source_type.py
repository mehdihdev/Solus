"""solusdev-249 add local source type

Adds `local` to the `sources.type` value set (SOLUSDEV-249 / INTEGRATIONS I2 —
a working copy on one machine as a graph source). `SourceType` is a portable
VARCHAR + named CHECK (`_enum_column`, native_enum=False), so widening it means
rebuilding the `sourcetype` CHECK, via `batch_alter_table` for Postgres and the
SQLite test DB alike (same recipe as 5c2c022b4d39 for `altium`).

Revision ID: c7d8e9f0a1b2
Revises: b4c5d6e7f8a9
Create Date: 2026-09-07 09:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE = ("github", "gitlab", "kicad", "onshape", "ros", "altium")
_WITH_LOCAL = (*_BASE, "local")


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
            type_=_source_type(_WITH_LOCAL),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.alter_column(
            "type",
            existing_type=_source_type(_WITH_LOCAL),
            type_=_source_type(_BASE),
            existing_nullable=False,
        )
