"""Merge SOLUSDEV-240 (`project` domain) and SOLUSDEV-246 (`workspace` domain).

Both branches recreated the `domain` CHECK on `graph_entity` and `error_solution`
with THEIR five-plus-one list, so whichever ran last would have dropped the other
value. This merge point recreates both constraints with the full seven-value
vocabulary (ADR-027 as amended 2026-09-05 and 2026-09-06). Downgrade recreates
the pre-branch five so both parent chains can continue downward cleanly.

Revision ID: e6f7a8b9c0d1
Revises: 2cd33377eeb0, d5e6f7a8b9c0
Create Date: 2026-09-06
"""

from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = ("2cd33377eeb0", "d5e6f7a8b9c0")
branch_labels = None
depends_on = None

DOMAIN_BASE = ("code", "electrical", "mechanical", "simulation", "runtime")
DOMAIN_ALL = (*DOMAIN_BASE, "project", "workspace")
TABLES = ("graph_entity", "error_solution")


def _recreate(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint("domain", table, type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint("domain", table, f"domain IN ({allowed})")


def upgrade() -> None:
    for table in TABLES:
        _recreate(table, DOMAIN_ALL)


def downgrade() -> None:
    # Each parent branch's own downgrade re-asserts its five-plus-one list; the
    # widest common state to hand back is the union, so leave it in place.
    pass
