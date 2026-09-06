"""SOLUSDEV-246 (STORE ST2): the sixth graph domain, `workspace`.

ADR-027 amendment 2026-09-06. `graph_entity.domain` and `error_solution.domain`
share the portable VARCHAR + CHECK enum named `domain`; alembic cannot detect a
CHECK content change, so both constraints are dropped and recreated here — the
same move `9aeb5f29b0bc` made when `runtime` arrived. Downgrade refuses while any
workspace-domain row exists: the layer is removed by the install lifecycle, not
by a schema rollback.

Revision ID: b3f1c2d4e5a6
Revises: 9a1c4e7d2b30
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "b3f1c2d4e5a6"
down_revision = "9a1c4e7d2b30"
branch_labels = None
depends_on = None

DOMAIN_OLD = ("code", "electrical", "mechanical", "simulation", "runtime")
# `project` (SOLUSDEV-240, migration b7e2d4a9c1f0 on a sibling branch) is included so
# this step never DROPS a value a database already holds when it runs AFTER that
# branch: a CHECK may be wider than the code's enum, never narrower than the data.
DOMAIN_NEW = (*DOMAIN_OLD, "project", "workspace")
TABLES = ("graph_entity", "error_solution")


def _recreate(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint("domain", table, type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint("domain", table, f"domain IN ({allowed})")


def upgrade() -> None:
    for table in TABLES:
        _recreate(table, DOMAIN_NEW)


def downgrade() -> None:
    for table in TABLES:
        present = (
            op.get_bind()
            .execute(
                sa.text(f"SELECT 1 FROM {table} WHERE domain = 'workspace' LIMIT 1")  # noqa: S608 — constant table name
            )
            .first()
        )
        if present is not None:
            raise RuntimeError(
                f"{table} still holds workspace-domain rows; uninstall the extensions first"
            )
    for table in TABLES:
        _recreate(table, DOMAIN_OLD)
