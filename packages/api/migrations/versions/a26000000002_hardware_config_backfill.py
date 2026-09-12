"""SOLUSDEV-260: backfill independent hardware subjects before constraints."""

import sys
from collections.abc import Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "a26000000002"
down_revision: str | None = "a25100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The revision runs from both repository-root pytest and API-root Alembic.
    # Resolve this frozen sibling directly, without depending on the process cwd.
    name = "solus_hardware_backfill_260"
    spec = spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "hardware_config_backfill.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.upgrade_data(op.get_bind())


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM solus_entries WHERE kind='config' "
            "AND payload->>'schema_version'='2')"
        )
    ):
        raise RuntimeError(
            "Independent hardware v2 state cannot be represented in v1; "
            "restore the reviewed backup instead"
        )
