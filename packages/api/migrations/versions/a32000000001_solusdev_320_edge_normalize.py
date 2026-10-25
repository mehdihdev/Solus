"""SOLUSDEV-320: normalize graph_edge domain_pair, origins and evidence."""

import sys
from collections.abc import Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "a32000000001"
down_revision: str | None = "a31300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The revision runs from both repository-root pytest and API-root Alembic.
    # Resolve this frozen sibling directly, without depending on the process cwd.
    name = "solus_edge_normalize_320"
    spec = spec_from_file_location(name, Path(__file__).resolve().parents[1] / "edge_normalize.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.normalize_edges(op.get_bind())
    malformed = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM graph_edge WHERE domain_pair !~ '^[a-z]+<->[a-z]+$'")
    )
    if malformed:
        raise RuntimeError(f"{malformed} graph_edge rows still carry a malformed domain_pair")


def downgrade() -> None:
    # Data-only normalisation; the old spellings carried no information worth restoring.
    pass
