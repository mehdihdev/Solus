"""SOLUSDEV-251: additive config subject/version and reviewed operation storage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a25100000001"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("solus_entries", sa.Column("configured_entity_id", sa.Uuid(), nullable=True))
    op.add_column(
        "solus_entries",
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_solus_config_subject",
        "solus_entries",
        "graph_entity",
        ["configured_entity_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "hardware_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "user_id", "idempotency_key", name="uq_hardware_operation_scope"
        ),
        sa.CheckConstraint(
            "octet_length(response::text) <= 65536", name="ck_hardware_operation_response_size"
        ),
    )
    op.create_index("ix_hardware_operations_expires_at", "hardware_operations", ["expires_at"])


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM solus_entries WHERE payload->>'schema_version' = '2')"
        )
    ):
        raise RuntimeError(
            "Hardware v2 data cannot be represented by the v1 schema; "
            "export and resolve it before downgrade"
        )
    op.drop_table("hardware_operations")
    op.drop_constraint("fk_solus_config_subject", "solus_entries", type_="foreignkey")
    op.drop_column("solus_entries", "config_version")
    op.drop_column("solus_entries", "configured_entity_id")
