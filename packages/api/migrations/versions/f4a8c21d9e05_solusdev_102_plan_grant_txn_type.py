"""solusdev-102 plan_grant credit transaction type

Widen the `credittxntype` CHECK on credit_ledger to admit 'plan_grant' —
the one-time starting-credit grant applied when a paid plan first activates
(ADR-023/024, amended 2026-08-08; models.CreditTxnType.PLAN_GRANT). The enum
is stored as a portable VARCHAR with a CHECK (models._enum_column), so adding
a Python enum member requires this DDL to keep inserts legal.

Revision ID: f4a8c21d9e05
Revises: 1827bb0b37b6
Create Date: 2026-08-08 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a8c21d9e05"
down_revision: str | None = "1827bb0b37b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VALUES = ("purchase", "usage", "trial_grant", "refund", "adjustment")
_NEW_VALUES = ("purchase", "usage", "trial_grant", "plan_grant", "refund", "adjustment")


def _values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint("credittxntype", "credit_ledger", type_="check")
    op.create_check_constraint(
        "credittxntype",
        "credit_ledger",
        sa.text(f"type IN ({_values_sql(_NEW_VALUES)})"),
    )


def downgrade() -> None:
    # The ledger is append-only and never deleted (ADR-024): reclassify the
    # grants as generic adjustments instead of destroying financial records,
    # preserving the plan in attrs for auditability.
    op.execute("UPDATE credit_ledger SET type = 'adjustment' WHERE type = 'plan_grant'")
    op.drop_constraint("credittxntype", "credit_ledger", type_="check")
    op.create_check_constraint(
        "credittxntype",
        "credit_ledger",
        sa.text(f"type IN ({_values_sql(_OLD_VALUES)})"),
    )
