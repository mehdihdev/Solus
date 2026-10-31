"""SOLUSDEV-321 P8: `proposal_outcomes` — every decision on a SOL proposal, as data.

Revision ID: a32100000001
Revises: a32000000006
Create Date: 2026-10-30

One row per decision: a card approved (`accepted`), rejected, expired or found `stale`, an owned
routine Build auto-ran (`accepted_auto`); `edited` is reserved. A stale row says why
(`stale_reason`: `diverged`, `quota` or `no_preview`). Each row names the tool, a digest of
what was proposed, the entities it named, each source's change token at that moment
(`design_signals`), the deciding user and the machine the decision came from — identifiers and
digests, never the arguments. `user_id` is the decider, SET NULL when the account goes (as
`conversations.created_by` is); only they are shown the row's machine, turn and digest (R146). The
`(project_id, created_at)` index serves `GET /projects/{id}/outcomes`, and the two foreign keys a
delete reaches through are indexed. `credit_ledger (user_id, created_at)` serves
`GET /projects/{id}/usage/turns` (M9): one person's usage rows, newest first. The ledger takes a
write on every debit, so that index is built concurrently, first, in its own autocommit block, and
`if_not_exists` lets a run that fails after it be run again. The downgrade drops all of it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a32100000001"
down_revision: str | None = "a32000000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "proposal_outcomes"
PROJECT_INDEX = "ix_proposal_outcomes_project_created"
#: The foreign keys an account or a conversation delete reaches through (`ix_<table>_<column>`).
FK_COLUMNS = ("user_id", "conversation_turn_id")
DECISIONS = "('accepted', 'rejected', 'edited', 'accepted_auto', 'expired', 'stale')"
#: Why the gate found a card stale (M190): null for every other decision, and for a stale card
#: whose reason the decide path cannot tell.
STALE_REASONS = "('diverged', 'quota', 'no_preview')"
LEDGER = "credit_ledger"
LEDGER_INDEX = "ix_credit_ledger_user_created"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            LEDGER_INDEX,
            LEDGER,
            ["user_id", "created_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
    op.create_table(
        TABLE,
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_turn_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_turns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("proposal_digest", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("entity_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("design_signals", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("machine_id", sa.Uuid(), nullable=True),
        sa.Column("stale_reason", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"decision IN {DECISIONS}", name="ck_proposal_outcomes_decision"),
        sa.CheckConstraint(
            f"stale_reason IS NULL OR stale_reason IN {STALE_REASONS}",
            name="ck_proposal_outcomes_stale_reason",
        ),
    )
    op.create_index(PROJECT_INDEX, TABLE, ["project_id", "created_at"])
    for column in FK_COLUMNS:
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])


def downgrade() -> None:
    for column in reversed(FK_COLUMNS):
        op.drop_index(f"ix_{TABLE}_{column}", table_name=TABLE)
    op.drop_index(PROJECT_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
    with op.get_context().autocommit_block():
        op.drop_index(LEDGER_INDEX, table_name=LEDGER, postgresql_concurrently=True, if_exists=True)
