"""SOLUSDEV-246 (STORE ST2, security review MEDIUM-2): singletons are unique.

`solus:workspace` and `solus:live_bench` are one-per-project and `solus:widget`
is one-per-(project, slug); check-then-insert alone lets two concurrent installs
(or an install racing a reconcile) create duplicates that nothing prunes. Partial
unique indexes make the invariant the database's; the writer catches the
IntegrityError under a savepoint and adopts the winner.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-06
"""

from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

SINGLETONS = "uq_graph_entity_workspace_singleton"
WIDGETS = "uq_graph_entity_workspace_widget_slug"


def upgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX {SINGLETONS} ON graph_entity (project_id, kind) "
        "WHERE kind IN ('solus:workspace', 'solus:live_bench') "
        "AND domain = 'workspace' AND origin = 'system' AND deleted_at IS NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {WIDGETS} ON graph_entity (project_id, (attrs->>'slug')) "
        "WHERE kind = 'solus:widget' AND domain = 'workspace' AND origin = 'system' "
        "AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {WIDGETS}")
    op.execute(f"DROP INDEX IF EXISTS {SINGLETONS}")
