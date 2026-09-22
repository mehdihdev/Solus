"""SOLUSDEV-261 approved Code/Isaac terminal execution knowledge categories.

Only CHECK constraints change; rows and the shared-store ingestion boundary do
not. Vocabulary is frozen here rather than imported from evolving contracts.
PostgreSQL transactional DDL keeps each replacement atomic. The table lock also
fences the downgrade's existence check against concurrent new-value inserts.
Lock acquisition is bounded to five seconds and each statement to thirty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a26100000001"
down_revision: str | None = "a26000000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TOOLS = ("fusion", "onshape", "solidworks", "autocad", "kicad", "altium", "spice")
OLD_SURFACES = ("toolbar", "menu", "context_menu", "panel", "dialog", "keyboard", "status_bar")
OLD_EFFECTS = (
    "create_feature",
    "modify_feature",
    "delete_feature",
    "select",
    "navigate",
    "measure",
    "toggle_visibility",
    "import",
    "export",
    "undo",
    "settings",
)


def _lock() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
    op.execute(sa.text("LOCK TABLE tool_knowledge IN ACCESS EXCLUSIVE MODE"))


def _replace(tools: tuple[str, ...], surfaces: tuple[str, ...], effects: tuple[str, ...]) -> None:
    for name, column, values in (
        ("toolfamily", "tool", tools),
        ("uisurface", "surface", surfaces),
        ("controleffect", "effect", effects),
    ):
        op.drop_constraint(name, "tool_knowledge", type_="check")
        op.create_check_constraint(name, "tool_knowledge", sa.column(column).in_(values))


def upgrade() -> None:
    _lock()
    _replace(
        OLD_TOOLS + ("code", "isaac"), OLD_SURFACES + ("terminal",), OLD_EFFECTS + ("execute",)
    )


def downgrade() -> None:
    _lock()
    knowledge = sa.table(
        "tool_knowledge", sa.column("tool"), sa.column("surface"), sa.column("effect")
    )
    used = (
        op.get_bind()
        .execute(
            sa.select(sa.literal(1))
            .select_from(knowledge)
            .where(
                sa.or_(
                    knowledge.c.tool.in_(("code", "isaac")),
                    knowledge.c.surface == "terminal",
                    knowledge.c.effect == "execute",
                )
            )
            .limit(1)
        )
        .first()
    )
    if used is not None:
        raise RuntimeError("Cannot downgrade while rows use new tool knowledge enum values")
    _replace(OLD_TOOLS, OLD_SURFACES, OLD_EFFECTS)
